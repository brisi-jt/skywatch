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


def freq(label: str, mhz: float, category: FrequencyCategory) -> Frequency:
    return Frequency(
        label=label,
        mhz=mhz,
        facility="Test",
        category=category,
        tuner_group=1,
    )


MULTICHANNEL_PLAN = [
    freq("Stansted Approach (Essex Radar)", 120.625, FrequencyCategory.APPROACH),
    freq("London Control (Clacton sector)", 118.48, FrequencyCategory.AREA_CONTROL),
    freq("London Control (Lambourne sector)", 118.825, FrequencyCategory.AREA_CONTROL),
]

SCAN_PLAN = MULTICHANNEL_PLAN + [
    freq("Guard 121.500", 121.5, FrequencyCategory.GUARD),
    freq("Stansted Tower", 123.805, FrequencyCategory.TOWER),
]

MULTICHANNEL = CaptureSettings(mode="multichannel")
SCAN = CaptureSettings(mode="scan")


def test_multichannel_matches_golden():
    rendered = render_conf(MULTICHANNEL_PLAN, MULTICHANNEL, recordings_dir=RECORDINGS_DIR)
    assert rendered == (GOLDEN_DIR / "rtl_airband_multichannel.conf").read_text()


def test_scan_matches_golden():
    rendered = render_conf(SCAN_PLAN, SCAN, recordings_dir=RECORDINGS_DIR)
    assert rendered == (GOLDEN_DIR / "rtl_airband_scan.conf").read_text()


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
