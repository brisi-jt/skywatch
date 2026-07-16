from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel

from skywatch.db.engine import create_db_engine
from skywatch.db.enums import (
    AsrEngine,
    ClassificationCategory,
    ClassificationSource,
    ClassificationStatus,
    FeedbackVerdict,
    FlightDataSource,
    FrequencyCategory,
    RecordingStage,
)
from skywatch.db.models import (
    AircraftMatch,
    Classification,
    Feedback,
    Frequency,
    Recording,
    Transcript,
    utcnow,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def engine(tmp_path):
    import skywatch.db.models  # noqa: F401  (register tables on the shared metadata)

    eng = create_db_engine(tmp_path / "station.db")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


class Seeder:
    """Builds persisted rows for tests with sensible defaults."""

    def __init__(self, session: Session, data_root: Path | None = None) -> None:
        self.session = session
        self.data_root = data_root

    def frequency(self, label="Stansted Tower", mhz=123.805, **kwargs) -> Frequency:
        defaults = dict(
            facility="Stansted",
            category=FrequencyCategory.TOWER,
            is_active=True,
            tuner_group=1,
            verified=False,
        )
        defaults.update(kwargs)
        row = Frequency(label=label, mhz=mhz, **defaults)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def recording(
        self,
        freq: Frequency,
        *,
        started: datetime | None = None,
        duration_s: float = 6.0,
        stage: RecordingStage = RecordingStage.CLASSIFIED,
        audio_bytes: bytes | None = None,
        audio_deleted: bool = False,
        **kwargs,
    ) -> Recording:
        started = started or (utcnow() - timedelta(minutes=5))
        file_path = kwargs.pop(
            "file_path",
            f"recordings/{started:%Y/%m/%d}/clip_{started:%Y%m%d_%H%M%S}"
            f"_{round(freq.mhz * 1e6)}.mp3",
        )
        if audio_bytes is not None:
            assert self.data_root is not None, "seeder needs data_root to write audio"
            target = self.data_root / file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(audio_bytes)
        row = Recording(
            freq_id=freq.id,
            started_at_utc=started,
            ended_at_utc=started + timedelta(seconds=duration_s),
            duration_s=duration_s,
            file_path=file_path,
            sample_rate=8000,
            stage=stage,
            audio_deleted_at=utcnow() if audio_deleted else None,
            **kwargs,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def transcript(self, recording: Recording, text="Tower, good morning.", **kwargs) -> Transcript:
        defaults = dict(engine=AsrEngine.FASTER_WHISPER, model="base.en", avg_logprob=-0.3)
        defaults.update(kwargs)
        row = Transcript(recording_id=recording.id, text=text, **defaults)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def classification(self, recording: Recording, *, is_interesting=False, **kwargs):
        defaults = dict(
            category=(
                ClassificationCategory.EMERGENCY
                if is_interesting
                else ClassificationCategory.ROUTINE
            ),
            confidence=0.9,
            reason="test verdict",
            source=ClassificationSource.PREFILTER,
            prefilter_flags=[],
            status=ClassificationStatus.FINAL,
        )
        defaults.update(kwargs)
        row = Classification(recording_id=recording.id, is_interesting=is_interesting, **defaults)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def match(self, recording: Recording, *, rank=1, **kwargs) -> AircraftMatch:
        defaults = dict(
            source=FlightDataSource.OPENSKY,
            icao24="4009f9",
            callsign="BAW2761",
            airline_name="British Airways",
            flight_number_guess="BA2761",
            lat=51.7,
            lon=0.1,
            alt_ft=3200.0,
            gs_kt=180.0,
            distance_km=3.1,
            match_confidence=0.8,
            queried_at=utcnow(),
        )
        defaults.update(kwargs)
        row = AircraftMatch(recording_id=recording.id, rank=rank, **defaults)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def feedback(self, recording: Recording, verdict=FeedbackVerdict.UP, note=None) -> Feedback:
        row = Feedback(recording_id=recording.id, verdict=verdict, note=note)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row


class FakeCaptureSource:
    """CaptureSource double that records lifecycle calls."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.running = True

    def start(self) -> None:
        self.calls.append("start")
        self.running = True

    def stop(self) -> None:
        self.calls.append("stop")
        self.running = False

    def status(self):
        from skywatch.capture.source import SourceStatus

        return SourceStatus(running=self.running, detail="fake source")


@pytest.fixture()
def station(engine, tmp_path, monkeypatch):
    """A wired API app over the test engine with a fake capture source."""
    from skywatch.api.app import create_app
    from skywatch.api.services.capture import CaptureController
    from skywatch.settings import Settings

    monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
    data_root = tmp_path / "data"
    data_root.mkdir()
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    settings = Settings(data_root=data_root, _env_file=None)
    source = FakeCaptureSource()
    capture = CaptureController(engine=engine, settings=settings, source=source)
    app = create_app(
        settings,
        engine=engine,
        capture=capture,
        content_dir=content_dir,
        ws_poll_interval=0.05,
    )
    return SimpleNamespace(
        app=app,
        engine=engine,
        settings=settings,
        source=source,
        content_dir=content_dir,
        data_root=data_root,
    )


@pytest.fixture()
def client(station) -> Iterator:
    from fastapi.testclient import TestClient

    with TestClient(station.app) as c:
        yield c


@pytest.fixture()
def seed(session, tmp_path) -> Seeder:
    return Seeder(session, data_root=tmp_path / "data")
