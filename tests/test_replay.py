"""ReplaySource: fixture clips into the watched directory, rtl_airband-shaped."""

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skywatch.capture.filenames import parse_recording_filename
from skywatch.capture.replay import ReplaySource

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = [
    REPO_ROOT / "fixtures" / "routine_clearance.mp3",
    REPO_ROOT / "fixtures" / "mayday.mp3",
]

TOWER_HZ = 123_805_000
GUARD_HZ = 121_500_000


def test_run_once_drops_every_fixture_with_parseable_names(tmp_path):
    source = ReplaySource(
        FIXTURES, tmp_path, freqs_hz=[TOWER_HZ, GUARD_HZ], pacing_s=0, backdate_s=5
    )
    dropped = source.run_once()

    assert len(dropped) == len(FIXTURES)
    for path, fixture, freq_hz in zip(dropped, FIXTURES, [TOWER_HZ, GUARD_HZ], strict=True):
        parsed = parse_recording_filename(path.name)
        assert parsed is not None
        assert parsed.freq_hz == freq_hz
        assert parsed.started_at_utc <= datetime.now(UTC)
        assert path.read_bytes() == fixture.read_bytes()


def test_drops_land_in_dated_subdirectories(tmp_path):
    source = ReplaySource(FIXTURES, tmp_path, freqs_hz=[TOWER_HZ], pacing_s=0)
    dropped = source.run_once()
    for path in dropped:
        rel = path.relative_to(tmp_path)
        parsed = parse_recording_filename(path.name)
        assert parsed is not None
        assert rel.parts[:3] == (
            f"{parsed.started_at_utc.year:04d}",
            f"{parsed.started_at_utc.month:02d}",
            f"{parsed.started_at_utc.day:02d}",
        )


def test_flat_layout_when_dated_subdirs_disabled(tmp_path):
    source = ReplaySource(FIXTURES, tmp_path, freqs_hz=[TOWER_HZ], pacing_s=0, dated_subdirs=False)
    dropped = source.run_once()
    for path in dropped:
        assert path.parent == tmp_path


def test_same_second_same_freq_drops_get_unique_names(tmp_path):
    source = ReplaySource(FIXTURES, tmp_path, freqs_hz=[GUARD_HZ], pacing_s=0)
    dropped = source.run_once()
    assert len({p.name for p in dropped}) == len(FIXTURES)


def test_freqs_cycle_when_fewer_than_fixtures(tmp_path):
    source = ReplaySource(FIXTURES * 2, tmp_path, freqs_hz=[TOWER_HZ, GUARD_HZ], pacing_s=0)
    dropped = source.run_once()
    freqs = [parse_recording_filename(p.name).freq_hz for p in dropped]
    assert freqs == [TOWER_HZ, GUARD_HZ, TOWER_HZ, GUARD_HZ]


def test_start_stop_status_lifecycle(tmp_path):
    source = ReplaySource(FIXTURES, tmp_path, freqs_hz=[TOWER_HZ], pacing_s=0.05)
    assert source.status().running is False

    source.start()
    deadline = time.monotonic() + 5
    while source.status().running and time.monotonic() < deadline:
        time.sleep(0.02)
    source.stop()

    assert source.status().running is False
    assert len(list(tmp_path.rglob("*.mp3"))) == len(FIXTURES)


def test_stop_interrupts_a_looping_source(tmp_path):
    source = ReplaySource(FIXTURES, tmp_path, freqs_hz=[TOWER_HZ], pacing_s=0.05, loop=True)
    source.start()
    time.sleep(0.2)
    source.stop()
    assert source.status().running is False
    assert list(tmp_path.rglob("*.mp3"))  # dropped at least one before stopping


def test_rejects_empty_inputs(tmp_path):
    with pytest.raises(ValueError):
        ReplaySource([], tmp_path, freqs_hz=[TOWER_HZ])
    with pytest.raises(ValueError):
        ReplaySource(FIXTURES, tmp_path, freqs_hz=[])
