"""Watcher: clip files on disk become ``recordings`` rows, exactly once."""

import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlmodel import Session, select

from skywatch.capture.filenames import format_recording_filename
from skywatch.capture.replay import ReplaySource
from skywatch.capture.watcher import RecordingWatcher, ingest_recording, probe_mp3
from skywatch.db.enums import FrequencyCategory, RecordingStage
from skywatch.db.models import Frequency, Recording

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"

STARTED = datetime(2026, 7, 16, 9, 30, 5, tzinfo=UTC)


@pytest.fixture()
def tower(session: Session) -> Frequency:
    row = Frequency(
        label="Stansted Tower",
        mhz=123.805,
        facility="London Stansted",
        category=FrequencyCategory.TOWER,
        tuner_group=2,
        is_active=True,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def drop_fixture(data_root: Path, name: str, freq_hz: int, started=STARTED) -> Path:
    dest = data_root / "recordings" / format_recording_filename("replay", started, freq_hz)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES_DIR / name, dest)
    return dest


class TestProbeMp3:
    def test_rejects_non_mp3_bytes(self, tmp_path):
        junk = tmp_path / "junk.mp3"
        junk.write_bytes(b"\x00" * 4096)
        with pytest.raises(ValueError):
            probe_mp3(junk)

    def test_duration_close_to_ffmpeg_truth(self):
        # ffmpeg reports ~1.0 s for the blip clip; the frame walker must agree.
        info = probe_mp3(FIXTURES_DIR / "blip.mp3")
        assert info.duration_s == pytest.approx(1.0, abs=0.35)


class TestIngest:
    def test_creates_row_with_full_provenance(self, session, tower, tmp_path):
        path = drop_fixture(tmp_path, "routine_clearance.mp3", 123_805_000)
        row = ingest_recording(session, path=path, data_root=tmp_path)
        session.commit()

        assert row is not None
        expected = probe_mp3(path)
        assert row.freq_id == tower.id
        assert row.started_at_utc == STARTED
        assert row.duration_s == pytest.approx(expected.duration_s)
        assert row.ended_at_utc == STARTED + timedelta(seconds=row.duration_s)
        assert row.sample_rate == expected.sample_rate
        assert row.stage == RecordingStage.CAPTURED
        assert row.file_path == str(path.relative_to(tmp_path))
        assert not Path(row.file_path).is_absolute()

    def test_same_file_twice_does_not_duplicate(self, session, tower, tmp_path):
        path = drop_fixture(tmp_path, "routine_clearance.mp3", 123_805_000)
        first = ingest_recording(session, path=path, data_root=tmp_path)
        session.commit()
        second = ingest_recording(session, path=path, data_root=tmp_path)
        session.commit()

        assert first is not None
        assert second is None
        assert len(session.exec(select(Recording)).all()) == 1

    def test_unknown_frequency_is_skipped(self, session, tower, tmp_path):
        path = drop_fixture(tmp_path, "routine_clearance.mp3", 133_000_000)
        assert ingest_recording(session, path=path, data_root=tmp_path) is None
        assert session.exec(select(Recording)).all() == []

    def test_unparseable_filename_is_skipped(self, session, tower, tmp_path):
        path = tmp_path / "recordings" / "not_a_clip.mp3"
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES_DIR / "blip.mp3", path)
        assert ingest_recording(session, path=path, data_root=tmp_path) is None

    def test_corrupt_audio_is_skipped(self, session, tower, tmp_path):
        path = tmp_path / "recordings" / format_recording_filename("replay", STARTED, 123_805_000)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 2048)
        assert ingest_recording(session, path=path, data_root=tmp_path) is None

    def test_inactive_frequency_is_skipped(self, session, tmp_path):
        inactive = Frequency(
            label="Stansted Tower",
            mhz=123.805,
            facility="London Stansted",
            category=FrequencyCategory.TOWER,
            tuner_group=2,
            is_active=False,
        )
        session.add(inactive)
        session.commit()
        path = drop_fixture(tmp_path, "routine_clearance.mp3", 123_805_000)
        # the channel was switched off; a stray clip for it must not be revived
        assert ingest_recording(session, path=path, data_root=tmp_path) is None
        assert session.exec(select(Recording)).all() == []


class TestWatcherIntegration:
    def wait_for_rows(self, engine, count, timeout=10.0) -> list[Recording]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with Session(engine) as s:
                rows = s.exec(select(Recording)).all()
            if len(rows) >= count:
                return rows
            time.sleep(0.05)
        return rows

    def test_replayed_fixtures_become_recordings_rows(self, engine, session, tower, tmp_path):
        recordings_dir = tmp_path / "recordings"
        recordings_dir.mkdir()
        watcher = RecordingWatcher(
            engine,
            recordings_dir,
            data_root=tmp_path,
            settle_seconds=0.2,
            poll_interval=0.05,
        )
        watcher.start()
        try:
            replay = ReplaySource(
                [FIXTURES_DIR / "routine_clearance.mp3", FIXTURES_DIR / "mayday.mp3"],
                recordings_dir,
                freqs_hz=[123_805_000],
                pacing_s=0,
            )
            dropped = replay.run_once()
            rows = self.wait_for_rows(engine, len(dropped))
        finally:
            watcher.stop()

        assert len(rows) == len(dropped)
        by_path = {row.file_path: row for row in rows}
        for path in dropped:
            row = by_path[str(path.relative_to(tmp_path))]
            assert row.freq_id == tower.id
            assert row.stage == RecordingStage.CAPTURED
            assert row.duration_s > 0

    def test_failed_ingest_is_retried_not_dropped(
        self, engine, session, tower, tmp_path, monkeypatch
    ):
        import skywatch.capture.watcher as watcher_module

        calls = {"n": 0}
        real_ingest = watcher_module.ingest_recording

        def flaky_ingest(session, *, path, data_root):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient database error")
            return real_ingest(session, path=path, data_root=data_root)

        monkeypatch.setattr(watcher_module, "ingest_recording", flaky_ingest)

        recordings_dir = tmp_path / "recordings"
        recordings_dir.mkdir()
        watcher = RecordingWatcher(
            engine,
            recordings_dir,
            data_root=tmp_path,
            settle_seconds=0.1,
            poll_interval=0.05,
        )
        watcher.start()
        try:
            drop_fixture(tmp_path, "routine_clearance.mp3", 123_805_000)
            rows = self.wait_for_rows(engine, 1)
        finally:
            watcher.stop()

        # the first attempt raised; the clip was re-queued and ingested on retry
        assert len(rows) == 1
        assert calls["n"] >= 2

    def test_scan_existing_picks_up_files_dropped_before_start(
        self, engine, session, tower, tmp_path
    ):
        drop_fixture(tmp_path, "routine_clearance.mp3", 123_805_000)
        watcher = RecordingWatcher(
            engine,
            tmp_path / "recordings",
            data_root=tmp_path,
            settle_seconds=0.2,
            poll_interval=0.05,
        )
        watcher.start()
        try:
            rows = self.wait_for_rows(engine, 1)
        finally:
            watcher.stop()
        assert len(rows) == 1
