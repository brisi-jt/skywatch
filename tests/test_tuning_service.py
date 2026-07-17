"""TuningService: database-owned tuning values seeded once from config.yaml."""

from datetime import UTC, datetime

from skywatch.db.models import Setting
from skywatch.settings import CaptureSettings
from skywatch.tuning import (
    FACTORY_GAIN_DB,
    FACTORY_PPM,
    FACTORY_SQUELCH_SNR_DB,
    GAIN_KEY,
    LAST_APPLIED_AT_KEY,
    PPM_KEY,
    R820T_GAIN_STEPS_DB,
    SQUELCH_DEFAULT_KEY,
    TuningService,
    TuningValues,
    snap_gain_db,
)


class TestSeed:
    def test_seeds_missing_rows_from_capture_settings(self, session):
        service = TuningService(CaptureSettings(gain=29.7, squelch_snr_threshold=9, ppm=3))

        assert service.ensure_seeded(session) is True

        assert session.get(Setting, GAIN_KEY).value == "29.7"
        assert session.get(Setting, SQUELCH_DEFAULT_KEY).value == "9"
        assert session.get(Setting, PPM_KEY).value == "3"

    def test_seeding_twice_changes_nothing(self, session):
        first = TuningService(CaptureSettings(gain=29.7, squelch_snr_threshold=9, ppm=3))
        first.ensure_seeded(session)

        # a later start with edited yaml values must not overwrite the rows
        second = TuningService(CaptureSettings(gain=40.2, squelch_snr_threshold=20, ppm=-5))
        assert second.ensure_seeded(session) is False

        assert session.get(Setting, GAIN_KEY).value == "29.7"
        assert session.get(Setting, SQUELCH_DEFAULT_KEY).value == "9"
        assert session.get(Setting, PPM_KEY).value == "3"

    def test_database_wins_over_settings_after_seed(self, session):
        TuningService(CaptureSettings(gain=29.7)).ensure_seeded(session)

        values = TuningService(CaptureSettings(gain=48.0)).current(session)

        assert values.gain_db == 29.7

    def test_unseeded_reads_fall_back_to_settings(self, session):
        values = TuningService(CaptureSettings(gain=25.4, squelch_snr_threshold=8, ppm=-1)).current(
            session
        )

        assert values.gain_db == 25.4
        assert values.squelch_default_snr_db == 8.0
        assert values.ppm == -1
        assert values.squelch_overrides == {}


class TestGainSteps:
    def test_table_is_the_canonical_29_step_r820t_set(self):
        assert len(R820T_GAIN_STEPS_DB) == 29
        assert R820T_GAIN_STEPS_DB[0] == 0.0
        assert R820T_GAIN_STEPS_DB[-1] == 49.6
        assert list(R820T_GAIN_STEPS_DB) == sorted(set(R820T_GAIN_STEPS_DB))

    def test_snap_picks_the_nearest_real_step(self):
        assert snap_gain_db(33.0) == 32.8
        assert snap_gain_db(0.4) == 0.0
        assert snap_gain_db(49.6) == 49.6
        assert snap_gain_db(28.0) == 28.0

    def test_factory_defaults(self):
        assert FACTORY_GAIN_DB == 32.0
        assert FACTORY_SQUELCH_SNR_DB == 12.0
        assert FACTORY_PPM == 0


class TestStore:
    def test_store_round_trips_every_field(self, session):
        service = TuningService(CaptureSettings())
        applied_at = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
        values = TuningValues(
            gain_db=36.4,
            squelch_default_snr_db=10.0,
            ppm=-2,
            squelch_overrides={3: 8.0, 7: 15.5},
        )

        service.store(session, values, applied_at=applied_at)

        restored = service.current(session)
        assert restored.gain_db == 36.4
        assert restored.squelch_default_snr_db == 10.0
        assert restored.ppm == -2
        assert restored.squelch_overrides == {3: 8.0, 7: 15.5}
        assert service.last_applied_at(session) == applied_at

    def test_store_removes_overrides_absent_from_the_new_set(self, session):
        service = TuningService(CaptureSettings())
        now = datetime.now(UTC)
        service.store(
            session,
            TuningValues(
                gain_db=32.8, squelch_default_snr_db=12.0, ppm=0, squelch_overrides={3: 8.0}
            ),
            applied_at=now,
        )

        service.store(
            session,
            TuningValues(gain_db=32.8, squelch_default_snr_db=12.0, ppm=0, squelch_overrides={}),
            applied_at=now,
        )

        assert service.current(session).squelch_overrides == {}
        assert session.get(Setting, "tuning.squelch.3") is None

    def test_override_prefix_does_not_swallow_the_default_key(self, session):
        service = TuningService(CaptureSettings())
        service.store(
            session,
            TuningValues(
                gain_db=32.8, squelch_default_snr_db=12.0, ppm=0, squelch_overrides={3: 8.0}
            ),
            applied_at=datetime.now(UTC),
        )

        values = service.current(session)
        assert values.squelch_default_snr_db == 12.0
        assert values.squelch_overrides == {3: 8.0}


class TestBaseline:
    def test_no_baseline_until_saved(self, session):
        assert TuningService(CaptureSettings()).baseline(session) is None

    def test_baseline_round_trips(self, session):
        service = TuningService(CaptureSettings())
        values = TuningValues(
            gain_db=38.6, squelch_default_snr_db=14.0, ppm=1, squelch_overrides={5: 9.0}
        )

        service.save_baseline(session, values)

        restored = service.baseline(session)
        assert restored == values

    def test_saving_again_replaces_the_previous_baseline(self, session):
        service = TuningService(CaptureSettings())
        service.save_baseline(
            session,
            TuningValues(
                gain_db=38.6, squelch_default_snr_db=14.0, ppm=1, squelch_overrides={5: 9.0}
            ),
        )
        replacement = TuningValues(
            gain_db=20.7, squelch_default_snr_db=11.0, ppm=0, squelch_overrides={}
        )

        service.save_baseline(session, replacement)

        assert service.baseline(session) == replacement


class TestEffectiveCapture:
    def test_effective_capture_carries_database_values(self, session):
        service = TuningService(CaptureSettings(gain=32.0, squelch_snr_threshold=12, ppm=0))
        service.store(
            session,
            TuningValues(gain_db=44.5, squelch_default_snr_db=9.0, ppm=-3, squelch_overrides={}),
            applied_at=datetime.now(UTC),
        )

        effective = service.effective_capture(session)

        assert effective.gain == 44.5
        assert effective.squelch_snr_threshold == 9.0
        assert effective.ppm == -3
        # topology stays with pydantic settings
        assert effective.mode == "multichannel"
        assert effective.sample_rate_msps == 2.56

    def test_last_applied_at_is_none_before_any_apply(self, session):
        assert TuningService(CaptureSettings()).last_applied_at(session) is None
        assert session.get(Setting, LAST_APPLIED_AT_KEY) is None
