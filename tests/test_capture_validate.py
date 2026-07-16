"""Mode-aware frequency-plan validation for the capture layer."""

import pytest

from skywatch.capture.validate import (
    USABLE_WINDOW_MHZ,
    pick_centerfreq,
    validate_frequencies,
)
from skywatch.db.enums import FrequencyCategory
from skywatch.db.models import Frequency


def freq(label: str, mhz: float) -> Frequency:
    return Frequency(
        label=label,
        mhz=mhz,
        facility="Test",
        category=FrequencyCategory.TOWER,
        tuner_group=1,
    )


GROUP_ONE = [
    freq("Clacton", 118.48),
    freq("Lambourne", 118.825),
    freq("Approach", 120.625),
]


class TestMultichannel:
    def test_fitting_set_is_ok_with_suggested_centerfreq(self):
        result = validate_frequencies(GROUP_ONE, "multichannel")
        assert result.ok
        assert result.errors == []
        assert result.suggested_centerfreq_mhz == pytest.approx(119.5525)

    def test_boundary_span_exactly_usable_window_fits(self):
        plan = [freq("lo", 120.0), freq("hi", 120.0 + USABLE_WINDOW_MHZ)]
        result = validate_frequencies(plan, "multichannel")
        assert result.ok

    def test_span_just_over_usable_window_fails(self):
        result = validate_frequencies([freq("lo", 120.0), freq("hi", 122.5)], "multichannel")
        assert not result.ok
        assert result.suggested_centerfreq_mhz is None

    def test_no_fit_error_names_offenders_and_suggests_centerfreq(self):
        freqs = GROUP_ONE + [
            freq("Guard", 121.5),
            freq("Ground", 121.73),
            freq("Stapleford", 122.8),
            freq("North Weald", 123.525),
            freq("Tower", 123.805),
        ]
        result = validate_frequencies(freqs, "multichannel")
        assert not result.ok
        message = " ".join(result.errors)
        # The best 2.4 MHz window keeps the five 121.5-123.805 channels;
        # the three low ones are the offenders to deactivate.
        offenders = ("Clacton (118.480 MHz)", "Lambourne (118.825 MHz)", "Approach (120.625 MHz)")
        for offender in offenders:
            assert offender in message
        assert "122.6525" in message  # centerfreq for the surviving window
        assert "scan" in message  # points at the mode escape hatch

    def test_offenders_listed_in_result(self):
        freqs = GROUP_ONE + [freq("Tower", 123.805)]
        result = validate_frequencies(freqs, "multichannel")
        assert not result.ok
        assert result.offenders == ["Tower"]

    def test_empty_plan_is_an_error(self):
        result = validate_frequencies([], "multichannel")
        assert not result.ok
        assert result.errors


class TestScan:
    def test_any_spread_is_valid_with_concurrency_warning(self):
        freqs = GROUP_ONE + [freq("Tower", 123.805)]
        result = validate_frequencies(freqs, "scan")
        assert result.ok
        assert result.errors == []
        assert any("miss" in w for w in result.warnings)

    def test_empty_plan_is_an_error(self):
        result = validate_frequencies([], "scan")
        assert not result.ok


class TestPickCenterfreq:
    def test_midpoint_of_span(self):
        assert pick_centerfreq([118.48, 118.825, 120.625]) == pytest.approx(119.5525)

    def test_single_frequency_nudges_off_the_dc_spike(self):
        center = pick_centerfreq([121.5])
        assert abs(center - 121.5) >= 0.025

    def test_midpoint_collision_with_a_channel_nudges(self):
        center = pick_centerfreq([121.0, 121.5, 122.0])
        assert all(abs(center - f) >= 0.025 for f in (121.0, 121.5, 122.0))
        # every channel still inside the usable window around the new centre
        assert all(abs(center - f) <= USABLE_WINDOW_MHZ / 2 for f in (121.0, 121.5, 122.0))
