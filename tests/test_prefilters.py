"""Prefilter unit tests: keywords, guard frequency, duration outliers."""

from skywatch.db.enums import ClassificationCategory, FrequencyCategory
from skywatch.pipeline.prefilters import (
    DURATION_OUTLIER_FLAG,
    GUARD_FLAG,
    duration_is_outlier,
    keyword_flags,
    run_prefilters,
)


class TestKeywordFlags:
    def test_mayday(self):
        flags = keyword_flags("MAYDAY MAYDAY MAYDAY Speedbird four seven two engine failure")
        assert "keyword:mayday" in flags
        assert "keyword:engine failure" in flags

    def test_pan_pan(self):
        assert "keyword:pan pan" in keyword_flags("pan pan pan pan pan pan all stations")
        assert "keyword:pan pan" in keyword_flags("PAN-PAN, PAN-PAN")

    def test_emergency_squawk_codes(self):
        assert "keyword:7700" in keyword_flags("squawk 7700")
        assert "keyword:7600" in keyword_flags("we have you squawking 7600")
        assert "keyword:7500" in keyword_flags("confirm squawk 7500")

    def test_go_around(self):
        assert "keyword:go around" in keyword_flags("go around, I say again, go around")
        assert "keyword:go around" in keyword_flags("Ryanair 22 going around")
        assert "keyword:go around" in keyword_flags("executing a go-around")

    def test_fuel_and_medical(self):
        assert "keyword:minimum fuel" in keyword_flags("declaring minimum fuel")
        assert "keyword:fuel emergency" in keyword_flags("fuel emergency, request priority")
        assert "keyword:medical" in keyword_flags("medical emergency on board")

    def test_flags_deduped(self):
        assert keyword_flags("mayday mayday mayday").count("keyword:mayday") == 1

    def test_routine_text_has_no_flags(self):
        assert keyword_flags("cleared to land runway two two, wind two one zero at five") == []

    def test_plain_fuel_mention_not_flagged(self):
        # "fuel on board two hours" is routine; only distress fuel phrases flag.
        assert keyword_flags("fuel on board two hours forty") == []


class TestDurationOutlier:
    def test_needs_minimum_samples(self):
        assert duration_is_outlier(60.0, [5.0] * 5) is False

    def test_flags_far_outlier(self):
        recents = [4.0, 5.0, 6.0, 5.5, 4.5, 5.0, 6.0, 4.0, 5.0, 5.5]
        assert duration_is_outlier(60.0, recents) is True

    def test_normal_duration_not_flagged(self):
        recents = [4.0, 5.0, 6.0, 5.5, 4.5, 5.0, 6.0, 4.0, 5.0, 5.5]
        assert duration_is_outlier(6.5, recents) is False


class TestRunPrefilters:
    def test_mayday_is_interesting_emergency(self):
        verdict = run_prefilters(
            transcript_text="mayday mayday mayday engine failure",
            duration_s=9.9,
            freq_category=FrequencyCategory.TOWER,
        )
        assert verdict.is_interesting is True
        assert verdict.category is ClassificationCategory.EMERGENCY
        assert "keyword:mayday" in verdict.flags
        assert verdict.confidence >= 0.8

    def test_guard_frequency_flagged(self):
        verdict = run_prefilters(
            transcript_text="station calling on guard, check your frequency",
            duration_s=7.0,
            freq_category=FrequencyCategory.GUARD,
        )
        assert verdict.is_interesting is True
        assert verdict.category is ClassificationCategory.GUARD_ACTIVITY
        assert GUARD_FLAG in verdict.flags

    def test_duration_outlier_flagged_unusual(self):
        verdict = run_prefilters(
            transcript_text="a very long position report continues",
            duration_s=90.0,
            freq_category=FrequencyCategory.APPROACH,
            recent_durations=[5.0, 6.0, 4.0, 5.0, 6.0, 5.0, 4.5, 5.5, 6.0, 5.0],
        )
        assert DURATION_OUTLIER_FLAG in verdict.flags
        assert verdict.is_interesting is True
        assert verdict.category is ClassificationCategory.UNUSUAL

    def test_keyword_category_beats_guard_category(self):
        verdict = run_prefilters(
            transcript_text="mayday mayday relay on guard",
            duration_s=8.0,
            freq_category=FrequencyCategory.GUARD,
        )
        assert verdict.category is ClassificationCategory.EMERGENCY
        assert GUARD_FLAG in verdict.flags

    def test_no_flags_is_routine(self):
        verdict = run_prefilters(
            transcript_text="cleared to land runway two two",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
        )
        assert verdict.is_interesting is False
        assert verdict.category is ClassificationCategory.ROUTINE
        assert verdict.flags == []

    def test_missing_transcript_still_runs(self):
        verdict = run_prefilters(
            transcript_text=None,
            duration_s=2.0,
            freq_category=FrequencyCategory.GUARD,
        )
        assert GUARD_FLAG in verdict.flags
