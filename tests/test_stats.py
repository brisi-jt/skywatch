"""Station stats: aggregate counts, the busiest-hour grid, top airlines."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from skywatch.db.enums import ClassificationCategory

UTC_ZONE = ZoneInfo("UTC")


class TestBuildStats:
    def _build(self, session, **kwargs):
        from skywatch.api.services.stats import build_stats

        kwargs.setdefault("tz", UTC_ZONE)
        return build_stats(session, **kwargs)

    def test_empty_station_is_a_zeroed_shape(self, session):
        result = self._build(session, today=date(2026, 8, 15))

        assert result.window_days == 30
        assert result.days_covered == 0
        assert result.total_count == 0
        assert result.interesting_rate is None
        assert result.go_around_count == 0
        assert len(result.daily_counts) == 30
        assert all(d.total_count == 0 and d.interesting_count == 0 for d in result.daily_counts)
        assert result.heat_frequencies == []
        assert result.hourly_heat == []
        assert result.top_airlines == []
        assert result.links["self"].href == "/stats"

    def test_daily_counts_and_interesting_rate(self, session, seed):
        freq = seed.frequency()
        today = date(2026, 8, 15)
        day_a = seed.recording(freq, started=datetime(2026, 8, 14, 9, 0, tzinfo=UTC))
        seed.classification(day_a, is_interesting=True)
        day_a_routine = seed.recording(freq, started=datetime(2026, 8, 14, 10, 0, tzinfo=UTC))
        seed.classification(day_a_routine, is_interesting=False)
        day_b = seed.recording(freq, started=datetime(2026, 8, 13, 8, 0, tzinfo=UTC))
        seed.classification(day_b, is_interesting=False)

        result = self._build(session, today=today)

        assert result.total_count == 3
        assert result.days_covered == 2
        assert result.interesting_rate == round(1 / 3, 4)
        by_date = {d.date: d for d in result.daily_counts}
        assert by_date[date(2026, 8, 14)].total_count == 2
        assert by_date[date(2026, 8, 14)].interesting_count == 1
        assert by_date[date(2026, 8, 13)].total_count == 1
        assert by_date[date(2026, 8, 13)].interesting_count == 0

    def test_window_excludes_recordings_older_than_the_window(self, session, seed):
        freq = seed.frequency()
        today = date(2026, 8, 15)
        # 2026-07-01 is 45 days before 2026-08-15: outside the 30-day window.
        old = seed.recording(freq, started=datetime(2026, 7, 1, 12, 0, tzinfo=UTC))
        seed.classification(old, is_interesting=True)

        result = self._build(session, today=today)

        assert result.total_count == 0
        assert result.days_covered == 0
        assert date(2026, 7, 1) not in {d.date for d in result.daily_counts}

    def test_reclassification_counts_only_the_latest_verdict(self, session, seed):
        freq = seed.frequency()
        today = date(2026, 8, 15)
        rec = seed.recording(freq, started=datetime(2026, 8, 14, 9, 0, tzinfo=UTC))
        seed.classification(rec, is_interesting=True)
        seed.classification(rec, is_interesting=False)  # a later re-look flips the verdict

        result = self._build(session, today=today)

        assert result.total_count == 1
        assert result.interesting_rate == 0.0

    def test_go_around_count_only_counts_that_category(self, session, seed):
        freq = seed.frequency()
        today = date(2026, 8, 15)
        go_around = seed.recording(freq, started=datetime(2026, 8, 14, 9, 0, tzinfo=UTC))
        seed.classification(
            go_around, is_interesting=True, category=ClassificationCategory.GO_AROUND
        )
        emergency = seed.recording(freq, started=datetime(2026, 8, 14, 10, 0, tzinfo=UTC))
        seed.classification(
            emergency, is_interesting=True, category=ClassificationCategory.EMERGENCY
        )

        result = self._build(session, today=today)

        assert result.go_around_count == 1

    def test_heat_grid_buckets_by_local_hour_and_frequency(self, session, seed):
        tower = seed.frequency(label="Stansted Tower", mhz=123.805)
        ground = seed.frequency(label="Stansted Ground", mhz=121.805)
        today = date(2026, 8, 15)
        for _ in range(3):
            seed.recording(tower, started=datetime(2026, 8, 14, 8, 30, tzinfo=UTC))
        seed.recording(ground, started=datetime(2026, 8, 14, 20, 15, tzinfo=UTC))

        result = self._build(session, today=today)

        cells = {(c.freq_id, c.hour): c.count for c in result.hourly_heat}
        assert cells[(tower.id, 8)] == 3
        assert cells[(ground.id, 20)] == 1
        assert {f.id for f in result.heat_frequencies} == {tower.id, ground.id}

    def test_heat_grid_honours_the_station_timezone(self, session, seed):
        freq = seed.frequency()
        today = date(2026, 8, 15)
        # 2026-08-14T23:30Z is 2026-08-15T00:30+01:00 (BST) — the next local hour.
        seed.recording(freq, started=datetime(2026, 8, 14, 23, 30, tzinfo=UTC))

        result = self._build(session, tz=ZoneInfo("Europe/London"), today=today)

        hours = {c.hour for c in result.hourly_heat}
        assert hours == {0}

    def test_top_airlines_ranked_by_count(self, session, seed):
        freq = seed.frequency()
        today = date(2026, 8, 15)
        for _ in range(2):
            rec = seed.recording(freq, started=datetime(2026, 8, 14, 9, 0, tzinfo=UTC))
            seed.match(rec, airline_name="Ryanair")
        rec = seed.recording(freq, started=datetime(2026, 8, 14, 10, 0, tzinfo=UTC))
        seed.match(rec, airline_name="British Airways")
        # a rank-2 (non-top) match must not count
        rec_two = seed.recording(freq, started=datetime(2026, 8, 14, 11, 0, tzinfo=UTC))
        seed.match(rec_two, airline_name="British Airways")
        seed.match(rec_two, rank=2, airline_name="Wizz Air")

        result = self._build(session, today=today)

        assert [a.airline_name for a in result.top_airlines] == ["Ryanair", "British Airways"]
        assert [a.count for a in result.top_airlines] == [2, 2]

    def test_no_top_match_is_skipped_not_null_bucketed(self, session, seed):
        freq = seed.frequency()
        today = date(2026, 8, 15)
        seed.recording(freq, started=datetime(2026, 8, 14, 9, 0, tzinfo=UTC))  # no match at all

        result = self._build(session, today=today)

        assert result.top_airlines == []


class TestStatsRoute:
    def test_stats_route_returns_the_built_shape(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        seed.classification(rec, is_interesting=True)

        response = client.get("/stats")

        assert response.status_code == 200
        body = response.json()
        assert body["_links"]["self"]["href"] == "/stats"
        assert body["total_count"] == 1
        assert body["window_days"] == 30
