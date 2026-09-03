"""Notable days: station-local days ranked by weighted interestingness."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from skywatch.db.enums import ClassificationCategory

UTC_ZONE = ZoneInfo("UTC")


class TestBuildNotableDays:
    def _build(self, session, **kwargs):
        from skywatch.api.services.digest import build_notable_days

        kwargs.setdefault("tz", UTC_ZONE)
        return build_notable_days(session, **kwargs)

    def test_empty_station_has_no_notable_days(self, session):
        result = self._build(session)
        assert result.items == []

    def test_emergency_day_outranks_a_day_with_more_routine_interesting_clips(self, session, seed):
        freq = seed.frequency()
        quiet_but_busy_day = date(2026, 8, 10)
        for hour in range(4):
            rec = seed.recording(freq, started=datetime(2026, 8, 10, 9 + hour, 0, tzinfo=UTC))
            seed.classification(rec, is_interesting=True, category=ClassificationCategory.UNUSUAL)
        emergency_day = date(2026, 8, 11)
        rec = seed.recording(freq, started=datetime(2026, 8, 11, 9, 0, tzinfo=UTC))
        seed.classification(rec, is_interesting=True, category=ClassificationCategory.EMERGENCY)

        result = self._build(session, limit=10)

        assert [item.date for item in result.items] == [emergency_day, quiet_but_busy_day]
        assert result.items[0].score > result.items[1].score

    def test_routine_and_non_interesting_clips_do_not_count(self, session, seed):
        freq = seed.frequency()
        rec = seed.recording(freq, started=datetime(2026, 8, 10, 9, 0, tzinfo=UTC))
        seed.classification(rec, is_interesting=False)

        result = self._build(session)

        assert result.items == []

    def test_reclassification_uses_only_the_latest_verdict(self, session, seed):
        freq = seed.frequency()
        rec = seed.recording(freq, started=datetime(2026, 8, 10, 9, 0, tzinfo=UTC))
        seed.classification(rec, is_interesting=True, category=ClassificationCategory.EMERGENCY)
        seed.classification(rec, is_interesting=False)  # downgraded on a re-look

        result = self._build(session)

        assert result.items == []

    def test_limit_caps_the_number_of_days_returned(self, session, seed):
        freq = seed.frequency()
        for day in range(5):
            rec = seed.recording(freq, started=datetime(2026, 8, 1 + day, 9, 0, tzinfo=UTC))
            seed.classification(rec, is_interesting=True, category=ClassificationCategory.UNUSUAL)

        result = self._build(session, limit=2)

        assert len(result.items) == 2

    def test_ties_break_by_most_recent_day_first(self, session, seed):
        freq = seed.frequency()
        earlier = seed.recording(freq, started=datetime(2026, 8, 1, 9, 0, tzinfo=UTC))
        seed.classification(earlier, is_interesting=True, category=ClassificationCategory.UNUSUAL)
        later = seed.recording(freq, started=datetime(2026, 8, 5, 9, 0, tzinfo=UTC))
        seed.classification(later, is_interesting=True, category=ClassificationCategory.UNUSUAL)

        result = self._build(session)

        assert [item.date for item in result.items] == [date(2026, 8, 5), date(2026, 8, 1)]


class TestNotableDaysRoute:
    def test_route_returns_the_built_shape(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        seed.classification(rec, is_interesting=True, category=ClassificationCategory.EMERGENCY)

        response = client.get("/digest/notable")

        assert response.status_code == 200
        body = response.json()
        assert body["items"][0]["interesting_count"] == 1
        assert "_links" in body
