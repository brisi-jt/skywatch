"""Retention pruner and disk guard tests.

The pruner deletes only ROUTINE audio past the retention window; interesting
audio is never deleted, database rows are always kept.
"""

from datetime import UTC, datetime, timedelta

from sqlmodel import select

from skywatch.db.enums import (
    ClassificationCategory,
    ClassificationSource,
    ClassificationStatus,
    FrequencyCategory,
    RecordingStage,
)
from skywatch.db.models import Classification, Frequency, Recording
from skywatch.pipeline.retention import check_disk, prune_routine_audio

NOW = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def _freq(session):
    freq = Frequency(
        label="Twr", mhz=123.805, facility="f", category=FrequencyCategory.TOWER, tuner_group=1
    )
    session.add(freq)
    session.commit()
    return freq


def _recording(session, data_root, freq, *, age_days, name, with_audio=True):
    rel = f"recordings/{name}.mp3"
    if with_audio:
        path = data_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
    started = NOW - timedelta(days=age_days)
    rec = Recording(
        freq_id=freq.id,
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=6),
        duration_s=6.0,
        file_path=rel,
        sample_rate=8000,
        stage=RecordingStage.CLASSIFIED,
    )
    session.add(rec)
    session.commit()
    return rec


def _classify(session, rec, *, interesting):
    session.add(
        Classification(
            recording_id=rec.id,
            is_interesting=interesting,
            category=ClassificationCategory.UNUSUAL
            if interesting
            else ClassificationCategory.ROUTINE,
            confidence=0.9,
            reason="test",
            source=ClassificationSource.PREFILTER,
            status=ClassificationStatus.FINAL,
        )
    )
    session.commit()


class TestPruner:
    def test_old_routine_audio_pruned_row_kept(self, session, tmp_path):
        freq = _freq(session)
        rec = _recording(session, tmp_path, freq, age_days=30, name="old_routine")
        _classify(session, rec, interesting=False)
        pruned = prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW)
        session.commit()
        assert pruned == 1
        assert not (tmp_path / rec.file_path).exists()
        session.refresh(rec)
        assert rec.audio_deleted_at is not None
        assert session.exec(select(Recording)).one().id == rec.id  # row survives

    def test_interesting_audio_never_pruned(self, session, tmp_path):
        freq = _freq(session)
        rec = _recording(session, tmp_path, freq, age_days=400, name="old_interesting")
        _classify(session, rec, interesting=True)
        assert prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW) == 0
        assert (tmp_path / rec.file_path).exists()
        assert rec.audio_deleted_at is None

    def test_latest_classification_wins(self, session, tmp_path):
        freq = _freq(session)
        rec = _recording(session, tmp_path, freq, age_days=30, name="upgraded")
        _classify(session, rec, interesting=False)
        _classify(session, rec, interesting=True)  # reclassified: history kept, latest wins
        assert prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW) == 0
        assert (tmp_path / rec.file_path).exists()

    def test_unclassified_audio_kept(self, session, tmp_path):
        freq = _freq(session)
        rec = _recording(session, tmp_path, freq, age_days=30, name="unclassified")
        assert prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW) == 0
        assert (tmp_path / rec.file_path).exists()

    def test_recent_routine_kept(self, session, tmp_path):
        freq = _freq(session)
        rec = _recording(session, tmp_path, freq, age_days=3, name="recent_routine")
        _classify(session, rec, interesting=False)
        assert prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW) == 0
        assert (tmp_path / rec.file_path).exists()

    def test_already_pruned_not_repruned(self, session, tmp_path):
        freq = _freq(session)
        rec = _recording(session, tmp_path, freq, age_days=30, name="twice")
        _classify(session, rec, interesting=False)
        assert prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW) == 1
        session.commit()
        assert prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW) == 0

    def test_missing_file_still_marked(self, session, tmp_path):
        freq = _freq(session)
        rec = _recording(session, tmp_path, freq, age_days=30, name="ghost", with_audio=False)
        _classify(session, rec, interesting=False)
        assert prune_routine_audio(session, data_root=tmp_path, retention_days=14, now=NOW) == 1
        session.commit()
        session.refresh(rec)
        assert rec.audio_deleted_at is not None


class TestDiskGuard:
    def test_healthy_disk(self, tmp_path):
        status = check_disk(tmp_path, min_free_gb=0.001)
        assert status.low is False
        assert status.free_gb > 0
        assert status.total_gb >= status.free_gb

    def test_low_disk(self, tmp_path):
        status = check_disk(tmp_path, min_free_gb=10**9)
        assert status.low is True
