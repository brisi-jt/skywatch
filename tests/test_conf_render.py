"""Golden-file tests for the generated rtl_airband.conf.

The conf is a build artifact: given the same frequency plan and settings it
must render byte-identical output, so the goldens under ``tests/golden/``
are the review surface for any renderer change.
"""

from pathlib import Path

import pytest

from skywatch.capture.conf_render import render_conf
from skywatch.db.enums import FrequencyCategory
from skywatch.db.models import Frequency
from skywatch.settings import CaptureSettings

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
RECORDINGS_DIR = Path("/data/recordings")
STATS_FILEPATH = Path("/data/stats/rtl_airband_stats.txt")


def freq(label: str, mhz: float, category: FrequencyCategory, freq_id: int | None = None):
    return Frequency(
        id=freq_id,
        label=label,
        mhz=mhz,
        facility="Test",
        category=category,
        tuner_group=1,
    )


MULTICHANNEL_PLAN = [
    freq("Stansted Approach (Essex Radar)", 120.625, FrequencyCategory.APPROACH, freq_id=1),
    freq("London Control (Clacton sector)", 118.48, FrequencyCategory.AREA_CONTROL, freq_id=2),
    freq("London Control (Lambourne sector)", 118.825, FrequencyCategory.AREA_CONTROL, freq_id=3),
]

SCAN_PLAN = MULTICHANNEL_PLAN + [
    freq("Guard 121.500", 121.5, FrequencyCategory.GUARD, freq_id=4),
    freq("Stansted Tower", 123.805, FrequencyCategory.TOWER, freq_id=5),
]

MULTICHANNEL = CaptureSettings(mode="multichannel")
SCAN = CaptureSettings(mode="scan")


def test_multichannel_matches_golden():
    rendered = render_conf(
        MULTICHANNEL_PLAN,
        MULTICHANNEL,
        recordings_dir=RECORDINGS_DIR,
        stats_filepath=STATS_FILEPATH,
    )
    assert rendered == (GOLDEN_DIR / "rtl_airband_multichannel.conf").read_text()


def test_scan_matches_golden():
    rendered = render_conf(
        SCAN_PLAN, SCAN, recordings_dir=RECORDINGS_DIR, stats_filepath=STATS_FILEPATH
    )
    assert rendered == (GOLDEN_DIR / "rtl_airband_scan.conf").read_text()


def test_tuned_multichannel_matches_golden():
    """Correction and a per-channel squelch override render alongside the defaults."""
    tuned = CaptureSettings(mode="multichannel", gain=38.6, ppm=-2)
    rendered = render_conf(
        MULTICHANNEL_PLAN,
        tuned,
        recordings_dir=RECORDINGS_DIR,
        squelch_overrides={2: 8.0},
        stats_filepath=STATS_FILEPATH,
    )
    assert rendered == (GOLDEN_DIR / "rtl_airband_multichannel_tuned.conf").read_text()


def test_zero_ppm_renders_no_correction_line():
    rendered = render_conf(MULTICHANNEL_PLAN, MULTICHANNEL, recordings_dir=RECORDINGS_DIR)
    assert "correction" not in rendered


def test_no_stats_filepath_renders_no_stats_line():
    rendered = render_conf(MULTICHANNEL_PLAN, MULTICHANNEL, recordings_dir=RECORDINGS_DIR)
    assert "stats_filepath" not in rendered


def test_override_for_a_frequency_outside_the_plan_is_ignored():
    with_stray = render_conf(
        MULTICHANNEL_PLAN,
        MULTICHANNEL,
        recordings_dir=RECORDINGS_DIR,
        squelch_overrides={99: 3.0},
    )
    without = render_conf(MULTICHANNEL_PLAN, MULTICHANNEL, recordings_dir=RECORDINGS_DIR)
    assert with_stray == without


def test_rendering_is_deterministic_regardless_of_input_order():
    a = render_conf(MULTICHANNEL_PLAN, MULTICHANNEL, recordings_dir=RECORDINGS_DIR)
    b = render_conf(list(reversed(MULTICHANNEL_PLAN)), MULTICHANNEL, recordings_dir=RECORDINGS_DIR)
    assert a == b


def test_multichannel_render_rejects_an_unfittable_plan():
    with pytest.raises(ValueError, match="usable"):
        render_conf(SCAN_PLAN, MULTICHANNEL, recordings_dir=RECORDINGS_DIR)


def test_render_rejects_empty_plan():
    with pytest.raises(ValueError):
        render_conf([], SCAN, recordings_dir=RECORDINGS_DIR)
