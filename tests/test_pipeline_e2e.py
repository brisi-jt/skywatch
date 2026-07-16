"""End-to-end replay test: fixture clips in, classified + enriched rows out.

Everything external is mocked (respx); ASR is a fake engine keyed off the
replay template name, so the full stage machine runs offline and fast.
"""

import json
from pathlib import Path

import httpx
import pytest
import respx
from sqlmodel import Session, select

from skywatch.capture.replay import ReplaySource
from skywatch.capture.watcher import ingest_recording
from skywatch.db.enums import (
    ApiProvider,
    AsrEngine,
    ClassificationCategory,
    ClassificationSource,
    ClassificationStatus,
    FrequencyCategory,
    RecordingStage,
)
from skywatch.db.models import AircraftMatch, Classification, Frequency, Recording
from skywatch.pipeline import budget
from skywatch.pipeline.worker import PipelineWorker
from skywatch.providers.asr.base import TranscriptionResult
from skywatch.providers.flightdata.airlines import AirlineDirectory
from skywatch.providers.flightdata.opensky import (
    STATES_URL,
    TOKEN_URL,
    OpenSkyClient,
    OpenSkyEnricher,
)
from skywatch.providers.llm.gemini import GeminiClassifier

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "fixtures"
RECEIVER_LAT, RECEIVER_LON = 51.5, -0.1

TRANSCRIPTS = {
    "mayday": "MAYDAY MAYDAY MAYDAY Speedbird four seven two engine failure returning",
    "routine": "Ryanair eight one five bravo cleared to land runway two two",
    "guard": "aircraft calling on one two one decimal five, check your frequency",
    "blip": "roger",
}

CLIP_PLAN = [
    ("mayday", "mayday.mp3", 123_805_000),
    ("routine", "routine_clearance.mp3", 123_805_000),
    ("guard", "guard_121500.mp3", 121_500_000),
    ("blip", "blip.mp3", 123_805_000),
]


class TemplateASR:
    """Maps the replay template prefix of each clip to a canned transcript."""

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        key = audio_path.name.split("_")[0]
        return TranscriptionResult(
            text=TRANSCRIPTS[key],
            avg_logprob=-0.25,
            language="en",
            engine=AsrEngine.FASTER_WHISPER,
            model="fake-base.en",
        )


def _seed_frequencies(session: Session) -> None:
    session.add(
        Frequency(
            label="Stansted Tower",
            mhz=123.805,
            facility="London Stansted",
            category=FrequencyCategory.TOWER,
            tuner_group=1,
            is_active=True,
        )
    )
    session.add(
        Frequency(
            label="Guard 121.500",
            mhz=121.5,
            facility="Emergency",
            category=FrequencyCategory.GUARD,
            tuner_group=1,
            is_active=True,
            verified=True,
        )
    )
    session.commit()


def _drop_and_ingest(engine, data_root: Path) -> dict[str, int]:
    """Replay each fixture into the watched tree and ingest it; returns ids."""
    recordings_dir = data_root / "recordings"
    for template, fixture, freq_hz in CLIP_PLAN:
        ReplaySource(
            [FIXTURES / fixture],
            recordings_dir,
            freqs_hz=[freq_hz],
            template=template,
            pacing_s=0,
        ).run_once()
    ids: dict[str, int] = {}
    with Session(engine) as session:
        for path in sorted(recordings_dir.rglob("*.mp3")):
            row = ingest_recording(session, path=path, data_root=data_root)
            assert row is not None, f"ingest refused {path.name}"
            session.commit()
            ids[path.name.split("_")[0]] = row.id
    assert set(ids) == {"mayday", "routine", "guard", "blip"}
    return ids


def _gemini_user_text(request: httpx.Request) -> str:
    """Only the per-clip user prompt — the system prompt legitimately
    teaches the model distress vocabulary, so matching the whole body
    would flag every request."""
    payload = json.loads(request.content)
    return payload["contents"][0]["parts"][0]["text"].lower()


def _gemini_responder(request: httpx.Request) -> httpx.Response:
    if "mayday" in _gemini_user_text(request):
        verdict = (
            '{"is_interesting": true, "category": "emergency", "confidence": 0.96,'
            ' "reason": "distress call with engine failure"}'
        )
    else:
        verdict = (
            '{"is_interesting": false, "category": "routine", "confidence": 0.9,'
            ' "reason": "standard phraseology"}'
        )
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": verdict}]}}]})


def _states_payload():
    def state(icao, callsign, lon, lat, alt_m):
        row = [icao, callsign, "United Kingdom", None, None, lon, lat, alt_m, False, 120.0]
        row += [None] * 7
        return row

    return {
        "time": 1_752_600_000,
        "states": [
            state("4009f9", "BAW472  ", 0.05, 51.70, 900.0),
            state("4ca7b4", "RYR815B ", 0.30, 51.90, 3500.0),
        ],
    }


def _worker(engine, data_root, *, chain, enricher, daily_call_cap=900):
    return PipelineWorker(
        engine,
        data_root=data_root,
        asr_engine=TemplateASR(),
        classifier_chain=chain,
        enricher=enricher,
        daily_call_cap=daily_call_cap,
        retention_days=14,
        min_free_disk_gb=0.001,
        max_attempts=3,
        backoff_base_s=0.0,
    )


def _run_to_completion(engine, worker, ids, *, ticks=10):
    for _ in range(ticks):
        worker.tick()
        with Session(engine) as session:
            stages = {session.get(Recording, rec_id).stage for rec_id in ids.values()}
        if stages == {RecordingStage.CLASSIFIED}:
            return
    raise AssertionError(f"pipeline did not settle; stages: {stages}")


def _latest_classification(session, rec_id) -> Classification:
    rows = session.exec(
        select(Classification)
        .where(Classification.recording_id == rec_id)
        .order_by(Classification.id)
    ).all()
    assert rows, f"no classification for recording {rec_id}"
    return rows[-1]


def _enricher(bucket_seconds=600):
    return OpenSkyEnricher(
        OpenSkyClient("cid", "secret"),
        receiver_lat=RECEIVER_LAT,
        receiver_lon=RECEIVER_LON,
        radius_km=40,
        bucket_seconds=bucket_seconds,
        daily_credit_cap=3000,
        airlines=AirlineDirectory.load(REPO_ROOT / "content" / "airlines.dat"),
    )


@respx.mock
def test_replay_end_to_end(engine, tmp_path):
    token_route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})
    )
    states_route = respx.get(STATES_URL).mock(
        return_value=httpx.Response(200, json=_states_payload())
    )
    gemini_route = respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        side_effect=_gemini_responder
    )

    with Session(engine) as session:
        _seed_frequencies(session)
    ids = _drop_and_ingest(engine, tmp_path)

    chain = [GeminiClassifier(api_key="test-key", model="gemini-2.5-flash-lite")]
    worker = _worker(engine, tmp_path, chain=chain, enricher=_enricher())
    _run_to_completion(engine, worker, ids)

    with Session(engine) as session:
        # Mayday: prefilter flags it, LLM confirms — interesting emergency.
        mayday = _latest_classification(session, ids["mayday"])
        assert mayday.is_interesting is True
        assert mayday.category is ClassificationCategory.EMERGENCY
        assert "keyword:mayday" in mayday.prefilter_flags
        assert mayday.source is ClassificationSource.LLM
        assert mayday.model == "gemini-2.5-flash-lite"
        assert mayday.status is ClassificationStatus.FINAL

        # Routine clearance stays routine.
        routine = _latest_classification(session, ids["routine"])
        assert routine.is_interesting is False
        assert routine.category is ClassificationCategory.ROUTINE
        assert routine.status is ClassificationStatus.FINAL

        # Guard clip: LLM said routine, but the prefilter verdict is only
        # ever upgraded — voice on guard stays flagged.
        guard = _latest_classification(session, ids["guard"])
        assert guard.is_interesting is True
        assert guard.category is ClassificationCategory.GUARD_ACTIVITY
        assert "guard_frequency" in guard.prefilter_flags

        # Blip: under the LLM floor, classified by prefilters alone.
        blip = _latest_classification(session, ids["blip"])
        assert blip.source is ClassificationSource.PREFILTER
        assert blip.status is ClassificationStatus.FINAL
        assert blip.is_interesting is False

        # Enrichment: every clip got candidates from the mocked OpenSky.
        for rec_id in ids.values():
            matches = session.exec(
                select(AircraftMatch).where(AircraftMatch.recording_id == rec_id)
            ).all()
            assert matches, f"no aircraft matches for recording {rec_id}"
            top = min(matches, key=lambda m: m.rank)
            assert top.callsign == "BAW472"
            assert top.airline_name == "British Airways"
            assert top.flight_number_guess == "BA472"

        # OAuth token fetched once; the 30 s bucket cache collapsed the
        # states lookups to fewer calls than clips.
        assert token_route.call_count == 1
        assert states_route.call_count < len(ids)

        # Blip never reached the LLM: one call each for the other three.
        assert gemini_route.call_count == 3
        for call in gemini_route.calls:
            assert "roger" not in _gemini_user_text(call.request)

        # Budget accounting matches the traffic.
        from datetime import UTC, datetime

        today = datetime.now(UTC).date()
        assert budget.calls_today(session, ApiProvider.GEMINI, today) == 3
        assert budget.calls_today(session, ApiProvider.OPENSKY, today) == states_route.call_count


@respx.mock
def test_cap_exhaustion_defers_then_backfills(engine, tmp_path):
    gemini_route = respx.post(url__regex=r"https://generativelanguage\.googleapis\.com/.*").mock(
        side_effect=_gemini_responder
    )
    with Session(engine) as session:
        _seed_frequencies(session)
    ids = _drop_and_ingest(engine, tmp_path)

    chain = [GeminiClassifier(api_key="test-key", model="gemini-2.5-flash-lite")]
    worker = _worker(engine, tmp_path, chain=chain, enricher=None, daily_call_cap=0)
    _run_to_completion(engine, worker, ids)

    assert gemini_route.call_count == 0
    with Session(engine) as session:
        for key in ("mayday", "routine", "guard"):
            row = _latest_classification(session, ids[key])
            assert row.status is ClassificationStatus.DEFERRED, key
            assert row.source is ClassificationSource.PREFILTER
        # Deferral never loses the prefilter signal.
        assert _latest_classification(session, ids["mayday"]).is_interesting is True

    # Quota reset: the backfill pass re-runs deferred clips through the LLM.
    worker.daily_call_cap = 900
    for _ in range(4):
        worker.tick()

    assert gemini_route.call_count == 3
    with Session(engine) as session:
        for key in ("mayday", "routine", "guard"):
            row = _latest_classification(session, ids[key])
            assert row.status is ClassificationStatus.FINAL, key
            assert row.source is ClassificationSource.LLM
        assert _latest_classification(session, ids["mayday"]).is_interesting is True
        assert _latest_classification(session, ids["routine"]).is_interesting is False
        # Blip stays prefilter-final; backfill does not touch it.
        assert _latest_classification(session, ids["blip"]).source is (
            ClassificationSource.PREFILTER
        )


@respx.mock  # no routes registered: any HTTP call would error the test
def test_full_offline_mode_completes(engine, tmp_path):
    with Session(engine) as session:
        _seed_frequencies(session)
    ids = _drop_and_ingest(engine, tmp_path)

    worker = _worker(engine, tmp_path, chain=[], enricher=None)
    _run_to_completion(engine, worker, ids)

    with Session(engine) as session:
        for rec_id in ids.values():
            row = _latest_classification(session, rec_id)
            assert row.status is ClassificationStatus.FINAL
            assert row.source is ClassificationSource.PREFILTER
        assert _latest_classification(session, ids["mayday"]).is_interesting is True
        assert _latest_classification(session, ids["guard"]).is_interesting is True
        assert _latest_classification(session, ids["routine"]).is_interesting is False
        assert session.exec(select(AircraftMatch)).all() == []


@pytest.mark.usefixtures("engine")
def test_worker_entry_point_registered():
    import tomllib

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["scripts"]["skywatch-worker"] == ("skywatch.pipeline.worker:main")
