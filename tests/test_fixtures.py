"""The committed tier-1 fixture clips and the script that generates them.

The clips themselves are committed, so their shape is asserted on every
platform; regenerating them needs macOS ``say`` plus ``ffmpeg`` and is
covered by a smoke test that skips where those tools are absent.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from skywatch.capture.watcher import probe_mp3

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "fixtures"

EXPECTED_CLIPS = {
    "mayday.mp3",
    "routine_clearance.mp3",
    "guard_121500.mp3",
    "blip.mp3",
}


def test_all_fixture_clips_committed():
    present = {p.name for p in FIXTURES_DIR.glob("*.mp3")}
    assert present >= EXPECTED_CLIPS


@pytest.mark.parametrize("name", sorted(EXPECTED_CLIPS))
def test_fixture_clips_are_8khz_mono_mp3(name):
    info = probe_mp3(FIXTURES_DIR / name)
    assert info.sample_rate == 8000
    assert info.channels == 1
    assert info.duration_s > 0


def test_blip_is_shorter_than_classifier_floor():
    assert probe_mp3(FIXTURES_DIR / "blip.mp3").duration_s < 1.5


def test_speech_clips_are_longer_than_classifier_floor():
    for name in EXPECTED_CLIPS - {"blip.mp3"}:
        assert probe_mp3(FIXTURES_DIR / name).duration_s > 1.5, name


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("ffmpeg") is None or shutil.which("say") is None,
    reason="fixture generation needs macOS `say` and ffmpeg",
)
def test_make_fixtures_script_regenerates_clips(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "make_fixtures.py"),
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    for name in EXPECTED_CLIPS:
        info = probe_mp3(tmp_path / name)
        assert info.sample_rate == 8000
    assert probe_mp3(tmp_path / "blip.mp3").duration_s < 1.5
