from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from skywatch.db.engine import create_db_engine, session_scope
from skywatch.db.enums import FrequencyCategory, FrequencyMode, RecordingStage
from skywatch.db.models import Frequency, Recording

T0 = datetime(2026, 7, 1, 9, 30, 0, tzinfo=UTC)


def test_engine_enables_wal_mode(engine):
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"


def test_engine_enforces_foreign_keys(engine):
    with pytest.raises(IntegrityError), Session(engine) as s:
        s.add(
            Recording(
                freq_id=12345,
                started_at_utc=T0,
                ended_at_utc=T0,
                duration_s=1.0,
                file_path="recordings/x.mp3",
                sample_rate=8000,
                stage=RecordingStage.CAPTURED,
            )
        )
        s.commit()


def test_engine_creates_parent_directory(tmp_path):
    db_path = tmp_path / "nested" / "dir" / "station.db"
    create_db_engine(db_path)
    assert db_path.parent.is_dir()


def _guard_frequency() -> Frequency:
    return Frequency(
        label="Guard 121.500",
        mhz=121.5,
        mode=FrequencyMode.AM,
        facility="International aeronautical emergency",
        category=FrequencyCategory.GUARD,
        description="Distress frequency.",
        is_active=True,
        tuner_group=1,
        verified=True,
    )


def test_session_scope_commits_on_success(engine):
    with session_scope(engine) as s:
        s.add(_guard_frequency())

    with Session(engine) as s:
        assert s.exec(select(Frequency)).one().label == "Guard 121.500"


def test_session_scope_rolls_back_on_error(engine):
    with pytest.raises(RuntimeError), session_scope(engine) as s:
        s.add(_guard_frequency())
        raise RuntimeError("boom")

    with Session(engine) as s:
        assert s.exec(select(Frequency)).first() is None
