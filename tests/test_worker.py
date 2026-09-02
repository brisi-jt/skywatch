"""Pipeline worker state-machine tests: staging, retries, resume, disk guard."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from skywatch.capture.source import SourceStatus
from skywatch.db.enums import (
    AsrEngine,
    ClassificationSource,
    ClassificationStatus,
    FrequencyCategory,
    RecordingStage,
)
from skywatch.db.models import (
    AircraftMatch,
    Classification,
    Frequency,
    Recording,
    Setting,
    Transcript,
)
from skywatch.pipeline.retention import (
    CAPTURE_PAUSED_KEY,
    DEEP_TUNE_ACTIVE_KEY,
    DEEP_TUNE_HEARTBEAT_TTL_S,
)
from skywatch.pipeline.worker import PipelineWorker, queue_depths
from skywatch.providers.asr.base import ASRError, TranscriptionResult
from skywatch.providers.flightdata.opensky import OpenSkyError
from test_classify import FakeClassifier, _routine_verdict


class FakeASR:
    def __init__(self, *, error=False, texts=None):
        self._error = error
        self._texts = texts or {}
        self.calls = 0
        self.paths: list[Path] = []

    def transcribe(
        self, audio_path: Path, *, hotwords=None, initial_prompt=None
    ) -> TranscriptionResult:
        self.calls += 1
        self.paths.append(audio_path)
        self.last_hotwords = hotwords
        if self._error:
            raise ASRError("decode failed")
        key = audio_path.name.split("_")[0]
        return TranscriptionResult(
            text=self._texts.get(key, "cleared to land runway two two"),
            avg_logprob=-0.3,
            language="en",
            engine=AsrEngine.FASTER_WHISPER,
            model="fake",
        )


class FakeEnricher:
    def __init__(self, *, error=False):
        self._error = error
        self.calls = 0

    def enrich(self, session, recording, freq_category):
        self.calls += 1
        if self._error:
            raise OpenSkyError("opensky down")
        return []


class FakeSource:
    def __init__(self):
        self.starts = 0
        self.stops = 0
        self.running = True

    def start(self):
        self.starts += 1
        self.running = True

    def stop(self):
        self.stops += 1
        self.running = False

    def status(self):
        return SourceStatus(running=self.running, detail="fake")


def _seed_recording(engine, *, stage=RecordingStage.CAPTURED, name="clip", data_root=None):
    with Session(engine) as session:
        freq = session.exec(select(Frequency)).first()
        if freq is None:
            freq = Frequency(
                label="Twr",
                mhz=123.805,
                facility="f",
                category=FrequencyCategory.TOWER,
                tuner_group=1,
            )
            session.add(freq)
            session.commit()
        started = datetime.now(UTC)
        rel = f"recordings/{name}_20260716_120000_123805000.mp3"
        if data_root is not None:
            path = data_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"audio")
        rec = Recording(
            freq_id=freq.id,
            started_at_utc=started,
            ended_at_utc=started + timedelta(seconds=8),
            duration_s=8.0,
            file_path=rel,
            sample_rate=8000,
            stage=stage,
        )
        session.add(rec)
        session.commit()
        return rec.id


def _worker(engine, tmp_path, **kwargs):
    defaults = dict(
        data_root=tmp_path,
        asr_engine=FakeASR(),
        classifier_chain=[],
        enricher=None,
        daily_call_cap=900,
        retention_days=14,
        min_free_disk_gb=0.001,
        max_attempts=3,
        backoff_base_s=0.0,
    )
    defaults.update(kwargs)
    return PipelineWorker(engine, **defaults)


def _stage(engine, rec_id) -> RecordingStage:
    with Session(engine) as session:
        return session.get(Recording, rec_id).stage


class TestResume:
    def test_in_flight_stages_reset_on_startup(self, engine, tmp_path):
        enriching = _seed_recording(engine, stage=RecordingStage.ENRICHING, name="a")
        classifying = _seed_recording(engine, stage=RecordingStage.CLASSIFYING, name="b")
        worker = _worker(engine, tmp_path)
        worker.reset_in_flight()
        assert _stage(engine, enriching) is RecordingStage.CAPTURED
        assert _stage(engine, classifying) is RecordingStage.TRANSCRIBED


class TestLifecycle:
    def test_offline_capture_to_classified(self, engine, tmp_path):
        rec_id = _seed_recording(engine, data_root=tmp_path)
        worker = _worker(engine, tmp_path)
        for _ in range(5):
            worker.tick()
        assert _stage(engine, rec_id) is RecordingStage.CLASSIFIED
        with Session(engine) as session:
            transcript = session.exec(select(Transcript)).one()
            assert transcript.recording_id == rec_id
            row = session.exec(select(Classification)).one()
            assert row.source is ClassificationSource.PREFILTER
            assert row.status is ClassificationStatus.FINAL
            assert session.exec(select(AircraftMatch)).all() == []

    def test_flagged_clips_classified_first(self, engine, tmp_path):
        _seed_recording(engine, stage=RecordingStage.CAPTURED, name="routine", data_root=tmp_path)
        _seed_recording(engine, stage=RecordingStage.CAPTURED, name="mayday", data_root=tmp_path)
        seen: list[str] = []

        class RecordingClassifier(FakeClassifier):
            def classify(self, request):
                seen.append(request.transcript)
                return super().classify(request)

        clf = RecordingClassifier(_routine_verdict())
        asr = FakeASR(texts={"mayday": "mayday mayday mayday", "routine": "cleared to land"})
        worker = _worker(engine, tmp_path, asr_engine=asr, classifier_chain=[clf])
        for _ in range(6):
            worker.tick()
        assert seen[0] == "mayday mayday mayday"


class TestEnrichFailures:
    def test_enrich_failure_never_blocks_slow_path(self, engine, tmp_path):
        rec_id = _seed_recording(engine, data_root=tmp_path)
        enricher = FakeEnricher(error=True)
        worker = _worker(engine, tmp_path, enricher=enricher, max_attempts=2)
        for _ in range(8):
            worker.tick()
        assert _stage(engine, rec_id) is RecordingStage.CLASSIFIED
        assert enricher.calls == 2  # retried, then gave up without blocking
        with Session(engine) as session:
            rec = session.get(Recording, rec_id)
            assert "enrich" in (rec.stage_error or "")

    def test_enrich_retry_respects_backoff(self, engine, tmp_path):
        rec_id = _seed_recording(engine, data_root=tmp_path)
        now = {"t": 1000.0}
        enricher = FakeEnricher(error=True)
        worker = _worker(
            engine,
            tmp_path,
            enricher=enricher,
            max_attempts=3,
            backoff_base_s=60.0,
            monotonic=lambda: now["t"],
        )
        worker.tick()
        assert enricher.calls == 1
        assert _stage(engine, rec_id) is RecordingStage.FAILED_ENRICH
        worker.tick()  # backoff not elapsed
        assert enricher.calls == 1
        now["t"] += 61
        worker.tick()
        assert enricher.calls == 2


class TestSlowPathFailures:
    def test_transcribe_failure_becomes_terminal(self, engine, tmp_path):
        rec_id = _seed_recording(engine, data_root=tmp_path)
        asr = FakeASR(error=True)
        worker = _worker(engine, tmp_path, asr_engine=asr, max_attempts=2)
        for _ in range(6):
            worker.tick()
        assert _stage(engine, rec_id) is RecordingStage.FAILED_TRANSCRIBE
        assert asr.calls == 2
        with Session(engine) as session:
            assert "decode failed" in session.get(Recording, rec_id).stage_error


class TestBackfill:
    def test_deferred_rows_picked_up_when_budget_returns(self, engine, tmp_path):
        rec_id = _seed_recording(engine, data_root=tmp_path)
        clf = FakeClassifier(_routine_verdict())
        worker = _worker(engine, tmp_path, classifier_chain=[clf], daily_call_cap=0)
        for _ in range(5):
            worker.tick()
        with Session(engine) as session:
            row = session.exec(select(Classification)).one()
            assert row.status is ClassificationStatus.DEFERRED
        worker.daily_call_cap = 900  # quota reset
        for _ in range(3):
            worker.tick()
        with Session(engine) as session:
            rows = session.exec(select(Classification).order_by(Classification.id)).all()
            assert len(rows) == 2
            assert rows[-1].status is ClassificationStatus.FINAL
            assert rows[-1].source is ClassificationSource.LLM
        assert _stage(engine, rec_id) is RecordingStage.CLASSIFIED


class TestDiskGuardAndStatus:
    def test_low_disk_pauses_capture(self, engine, tmp_path):
        source = FakeSource()
        worker = _worker(engine, tmp_path, capture_source=source, min_free_disk_gb=10**9)
        worker.tick()
        assert source.stops == 1
        with Session(engine) as session:
            paused = session.get(Setting, CAPTURE_PAUSED_KEY)
            assert paused is not None
            assert paused.value == "1"
        snapshot = worker.status_snapshot()
        assert snapshot["disk"]["low"] is True
        assert snapshot["capture"]["paused_for_disk"] is True

    def test_capture_resumes_when_disk_recovers(self, engine, tmp_path):
        source = FakeSource()
        source.running = False
        with Session(engine) as session:
            session.add(Setting(key=CAPTURE_PAUSED_KEY, value="1"))
            session.commit()
        worker = _worker(engine, tmp_path, capture_source=source, min_free_disk_gb=0.001)
        worker.tick()
        assert source.starts == 1
        with Session(engine) as session:
            assert session.get(Setting, CAPTURE_PAUSED_KEY).value == "0"

    def test_disk_recovery_defers_while_deep_tune_holds_receiver(self, engine, tmp_path):
        source = FakeSource()
        source.running = False
        with Session(engine) as session:
            session.add(Setting(key=CAPTURE_PAUSED_KEY, value="1"))
            session.add(Setting(key=DEEP_TUNE_ACTIVE_KEY, value="1"))  # fresh heartbeat
            session.commit()
        worker = _worker(engine, tmp_path, capture_source=source, min_free_disk_gb=0.001)
        worker.tick()
        # the dongle is held by the deep tune session; the worker must NOT
        # start rtl_airband on top of it — it defers to that session's exit
        assert source.starts == 0
        with Session(engine) as session:
            # the pause is cleared (disk is fine); resume is simply deferred
            assert session.get(Setting, CAPTURE_PAUSED_KEY).value == "0"

    def test_disk_recovery_ignores_stale_deep_tune_flag(self, engine, tmp_path):
        from sqlalchemy import update

        source = FakeSource()
        source.running = False
        with Session(engine) as session:
            session.add(Setting(key=CAPTURE_PAUSED_KEY, value="1"))
            session.add(Setting(key=DEEP_TUNE_ACTIVE_KEY, value="1"))
            session.commit()
            stale = datetime.now(UTC) - timedelta(seconds=DEEP_TUNE_HEARTBEAT_TTL_S + 30)
            session.exec(
                update(Setting).where(Setting.key == DEEP_TUNE_ACTIVE_KEY).values(updated_at=stale)
            )
            session.commit()
        worker = _worker(engine, tmp_path, capture_source=source, min_free_disk_gb=0.001)
        worker.tick()
        # a crashed API leaves a stale flag; past the TTL it must not block resume
        assert source.starts == 1

    def test_status_snapshot_shape(self, engine, tmp_path):
        _seed_recording(engine, data_root=tmp_path)
        worker = _worker(engine, tmp_path)
        snapshot = worker.status_snapshot()
        assert snapshot["queues"]["captured"] == 1
        assert "budget" in snapshot
        assert set(snapshot["disk"]) >= {"free_gb", "total_gb", "low", "min_free_gb"}

    def test_queue_depths_counts_stages(self, engine, tmp_path):
        _seed_recording(engine, stage=RecordingStage.CAPTURED, name="a")
        _seed_recording(engine, stage=RecordingStage.TRANSCRIBING, name="b")
        _seed_recording(engine, stage=RecordingStage.TRANSCRIBING, name="c")
        with Session(engine) as session:
            depths = queue_depths(session)
        assert depths["captured"] == 1
        assert depths["transcribing"] == 2
        assert depths["classified"] == 0
