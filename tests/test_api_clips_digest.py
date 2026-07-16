"""Contract tests for /clips/interesting and /digest."""

from datetime import UTC, datetime

from skywatch.db.enums import FeedbackVerdict


class TestInterestingClips:
    def test_lists_only_interesting_newest_first(self, client, seed):
        freq = seed.frequency()
        routine = seed.recording(freq, started=datetime(2026, 7, 10, 9, 0, tzinfo=UTC))
        seed.classification(routine, is_interesting=False)
        first = seed.recording(freq, started=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))
        seed.classification(first, is_interesting=True)
        second = seed.recording(freq, started=datetime(2026, 7, 11, 10, 0, tzinfo=UTC))
        seed.classification(second, is_interesting=True)

        response = client.get("/clips/interesting")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert [item["id"] for item in body["items"]] == [second.id, first.id]
        assert body["_links"]["self"]["href"].startswith("/clips/interesting")

    def test_empty_library(self, client):
        body = client.get("/clips/interesting").json()
        assert body["items"] == []
        assert body["total"] == 0


class TestDigest:
    def test_days_summary(self, client, seed):
        freq = seed.frequency()
        # 2026-07-10 in Europe/London is BST (UTC+1): the local day runs
        # 2026-07-09T23:00Z .. 2026-07-10T23:00Z.
        routine = seed.recording(freq, started=datetime(2026, 7, 10, 8, 0, tzinfo=UTC))
        seed.classification(routine, is_interesting=False)
        exciting = seed.recording(freq, started=datetime(2026, 7, 10, 22, 30, tzinfo=UTC))
        seed.classification(exciting, is_interesting=True)
        other_day = seed.recording(freq, started=datetime(2026, 7, 10, 23, 30, tzinfo=UTC))
        seed.classification(other_day, is_interesting=True)
        # all-time favourite from months earlier
        favourite = seed.recording(freq, started=datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
        seed.classification(favourite, is_interesting=True)
        seed.feedback(favourite, FeedbackVerdict.UP)
        seed.feedback(favourite, FeedbackVerdict.UP)

        response = client.get("/digest", params={"date": "2026-07-10"})

        assert response.status_code == 200
        body = response.json()
        assert body["date"] == "2026-07-10"
        assert body["total_count"] == 2
        assert body["interesting_count"] == 1
        assert [item["id"] for item in body["interesting"]] == [exciting.id]
        assert [item["id"] for item in body["greatest_hits"]] == [favourite.id]
        assert body["greatest_hits"][0]["feedback"]["up"] == 2
        links = body["_links"]
        assert links["self"]["href"] == "/digest?date=2026-07-10"
        assert links["previous_day"]["href"] == "/digest?date=2026-07-09"
        assert links["next_day"]["href"] == "/digest?date=2026-07-11"

    def test_empty_day_shape(self, client):
        body = client.get("/digest", params={"date": "2000-01-01"}).json()
        assert body["total_count"] == 0
        assert body["interesting_count"] == 0
        assert body["interesting"] == []
        assert body["greatest_hits"] == []

    def test_defaults_to_today(self, client):
        response = client.get("/digest")
        assert response.status_code == 200
        # today's digest never links forward to a day that hasn't happened
        assert "next_day" not in response.json()["_links"]

    def test_bad_date_is_a_validation_problem(self, client):
        response = client.get("/digest", params={"date": "not-a-date"})
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
