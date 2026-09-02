"""Callsign verbalization and its threading into the transcription stage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from skywatch.db.enums import FlightDataSource, FrequencyCategory, RecordingStage
from skywatch.db.models import AircraftMatch, Frequency, Recording, Transcript, utcnow
from skywatch.pipeline.stages.transcribe import callsign_hotwords
from skywatch.providers.asr.verbalize import verbalize_callsign, verbalize_callsigns
from skywatch.providers.flightdata.airlines import Airline, AirlineDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent


def _directory() -> AirlineDirectory:
    return AirlineDirectory.load(REPO_ROOT / "content" / "airlines.dat")


class TestVerbalize:
    def test_known_airline_uses_radio_name(self):
        assert verbalize_callsign("BAW2761", _directory()) == "speedbird two seven six one"

    def test_easyjet_and_ryanair(self):
        directory = _directory()
        assert verbalize_callsign("EZY815", directory) == "easy eight one five"
        assert verbalize_callsign("RYR4KP", directory) == "ryanair four kilo papa"

    def test_unknown_operator_prefix_falls_back_to_phonetic(self):
        # A prefix with no directory entry is spelled phonetically.
        directory = AirlineDirectory({})
        assert verbalize_callsign("ZZZ12", directory) == "zulu zulu zulu one two"

    def test_no_directory_spells_everything(self):
        assert verbalize_callsign("BAW2761", None) == "bravo alpha whiskey two seven six one"

    def test_unparseable_returns_none(self):
        directory = _directory()
        assert verbalize_callsign("", directory) is None
        assert verbalize_callsign(None, directory) is None
        assert verbalize_callsign("12-34", directory) is None

    def test_radio_name_lowercased_from_airline(self):
        directory = AirlineDirectory({"ABC": Airline("Ace Air", "ABC", "AA", radio="ACE")})
        assert verbalize_callsign("ABC9", directory) == "ace nine"

    def test_verbalize_many_dedups_and_preserves_order(self):
        directory = _directory()
        forms = verbalize_callsigns(["BAW1", "BAW1", None, "EZY2", "bad-one"], directory)
        assert forms == ["speedbird one", "easy two"]


class TestHotwordThreading:
    def _recording_with_matches(self, session: Session, callsigns: list[str]) -> int:
        freq = Frequency(
            label="Twr", mhz=123.805, facility="f", category=FrequencyCategory.TOWER, tuner_group=1
        )
        session.add(freq)
        session.commit()
        started = datetime.now(UTC)
        rec = Recording(
            freq_id=freq.id,
            started_at_utc=started,
            ended_at_utc=started + timedelta(seconds=8),
            duration_s=8.0,
            file_path="recordings/x.mp3",
            sample_rate=8000,
            stage=RecordingStage.TRANSCRIBING,
        )
        session.add(rec)
        session.commit()
        for rank, callsign in enumerate(callsigns, start=1):
            session.add(
                AircraftMatch(
                    recording_id=rec.id,
                    source=FlightDataSource.OPENSKY,
                    icao24=f"aa{rank:04x}",
                    callsign=callsign,
                    lat=51.7,
                    lon=0.1,
                    distance_km=3.0,
                    match_confidence=0.8,
                    rank=rank,
                    queried_at=utcnow(),
                )
            )
        session.commit()
        return rec.id

    def test_hotwords_present_when_candidates_exist(self, session):
        rec_id = self._recording_with_matches(session, ["BAW2761", "EZY815"])
        hotwords = callsign_hotwords(session, rec_id, _directory())
        assert hotwords == ["speedbird two seven six one", "easy eight one five"]

    def test_hotwords_empty_when_no_candidates(self, session):
        rec_id = self._recording_with_matches(session, [])
        assert callsign_hotwords(session, rec_id, _directory()) == []


class _RecordingASR:
    """A fake engine that records the biasing arguments it received."""

    from skywatch.db.enums import AsrEngine as _Engine

    def __init__(self):
        self.hotwords = "unset"
        self.initial_prompt = "unset"

    def transcribe(self, audio_path, *, hotwords=None, initial_prompt=None):
        from skywatch.providers.asr.base import TranscriptionResult

        self.hotwords = hotwords
        self.initial_prompt = initial_prompt
        return TranscriptionResult(
            text="cleared to land",
            avg_logprob=-0.3,
            language="en",
            engine=self._Engine.FASTER_WHISPER,
            model="fake",
        )


def _worker_with_asr(engine, tmp_path, asr, *, callsign_boost=True):
    from skywatch.pipeline.worker import PipelineWorker

    return PipelineWorker(
        engine,
        data_root=tmp_path,
        asr_engine=asr,
        classifier_chain=[],
        enricher=None,
        daily_call_cap=900,
        retention_days=14,
        min_free_disk_gb=0.001,
        airlines=_directory(),
        callsign_boost=callsign_boost,
    )


class TestWorkerThreadsHotwords:
    def test_worker_passes_verbalized_hotwords(self, engine, tmp_path):
        with Session(engine) as session:
            rec_id = TestHotwordThreading()._recording_with_matches(session, ["BAW2761"])
        asr = _RecordingASR()
        _worker_with_asr(engine, tmp_path, asr)._transcribe_pass()
        assert asr.hotwords == ["speedbird two seven six one"]
        assert "speedbird two seven six one" in asr.initial_prompt
        with Session(engine) as session:
            assert session.get(Recording, rec_id).stage is RecordingStage.TRANSCRIBED

    def test_worker_passes_no_hotwords_when_absent(self, engine, tmp_path):
        with Session(engine) as session:
            TestHotwordThreading()._recording_with_matches(session, [])
        asr = _RecordingASR()
        _worker_with_asr(engine, tmp_path, asr)._transcribe_pass()
        assert asr.hotwords is None
        assert asr.initial_prompt is None

    def test_boost_disabled_skips_hotwords(self, engine, tmp_path):
        with Session(engine) as session:
            TestHotwordThreading()._recording_with_matches(session, ["BAW2761"])
        asr = _RecordingASR()
        _worker_with_asr(engine, tmp_path, asr, callsign_boost=False)._transcribe_pass()
        assert asr.hotwords is None


def test_faster_whisper_forwards_hotwords_to_model(monkeypatch, tmp_path):
    """The faster-whisper engine passes hotwords/initial_prompt to the model."""
    from skywatch.providers.asr.faster_whisper import FasterWhisperEngine

    captured = {}

    class _Segment:
        text = "speedbird"
        start = 0.0
        end = 1.0
        avg_logprob = -0.3
        words = []

    class _Info:
        language = "en"

    class _Model:
        def transcribe(self, path, **kwargs):
            captured.update(kwargs)
            return [_Segment()], _Info()

    engine = FasterWhisperEngine(model="base.en")
    monkeypatch.setattr(engine, "_load", lambda: _Model())
    audio = tmp_path / "clip.mp3"
    audio.write_bytes(b"fake")
    engine.transcribe(audio, hotwords=["speedbird one"], initial_prompt="callsigns: speedbird one")
    assert captured["hotwords"] == "speedbird one"
    assert captured["initial_prompt"] == "callsigns: speedbird one"
    assert captured["word_timestamps"] is True


def test_transcript_written_when_boosted(session, seed, tmp_path):
    """Sanity: the boosted path still produces a stored transcript."""
    freq = seed.frequency()
    recording = seed.recording(freq, stage="transcribing")
    asr = _RecordingASR()
    from skywatch.pipeline.stages.transcribe import run_transcribe

    run_transcribe(session, recording, engine=asr, data_root=tmp_path, hotwords=["speedbird one"])
    session.commit()
    assert session.exec(select(Transcript)).one().text == "cleared to land"
