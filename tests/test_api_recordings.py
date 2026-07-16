"""Contract tests for the recordings library routes."""

from datetime import UTC, datetime, timedelta

from skywatch.db.enums import (
    ClassificationCategory,
    FeedbackVerdict,
    RecordingStage,
)

PROBLEM_TYPE = "application/problem+json"


class TestListRecordings:
    def test_lists_newest_first_with_summary_fields(self, client, seed):
        freq = seed.frequency()
        older = seed.recording(freq, started=datetime(2026, 7, 10, 9, 0, tzinfo=UTC))
        newer = seed.recording(freq, started=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))
        seed.transcript(newer, text="Mayday mayday mayday, Speedbird 472.")
        seed.classification(newer, is_interesting=True)
        seed.match(newer)
        seed.feedback(newer, FeedbackVerdict.UP)

        response = client.get("/recordings")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert [item["id"] for item in body["items"]] == [newer.id, older.id]
        first = body["items"][0]
        assert first["frequency"]["label"] == "Stansted Tower"
        assert first["transcript_snippet"].startswith("Mayday")
        assert first["classification"]["is_interesting"] is True
        assert first["top_match"]["callsign"] == "BAW2761"
        assert first["feedback"] == {"up": 1, "down": 0}
        assert first["audio_available"] is True
        assert first["_links"]["self"]["href"] == f"/recordings/{newer.id}"
        assert first["_links"]["audio"]["href"] == f"/recordings/{newer.id}/audio"
        # a clip with nothing attached yet is still a complete summary
        second = body["items"][1]
        assert second["transcript_snippet"] is None
        assert second["classification"] is None
        assert second["top_match"] is None

    def test_filters(self, client, seed):
        tower = seed.frequency("Stansted Tower", 123.805)
        guard = seed.frequency("Guard", 121.5)
        routine = seed.recording(tower, started=datetime(2026, 7, 10, 9, 0, tzinfo=UTC))
        seed.classification(routine, is_interesting=False)
        exciting = seed.recording(guard, started=datetime(2026, 7, 12, 9, 0, tzinfo=UTC))
        seed.classification(
            exciting, is_interesting=True, category=ClassificationCategory.GUARD_ACTIVITY
        )
        seed.match(exciting)

        by_freq = client.get("/recordings", params={"freq_id": guard.id}).json()
        assert [i["id"] for i in by_freq["items"]] == [exciting.id]

        interesting = client.get("/recordings", params={"interesting": "true"}).json()
        assert [i["id"] for i in interesting["items"]] == [exciting.id]

        by_category = client.get("/recordings", params={"category": "guard_activity"}).json()
        assert [i["id"] for i in by_category["items"]] == [exciting.id]

        with_match = client.get("/recordings", params={"has_match": "true"}).json()
        assert [i["id"] for i in with_match["items"]] == [exciting.id]

        without_match = client.get("/recordings", params={"has_match": "false"}).json()
        assert [i["id"] for i in without_match["items"]] == [routine.id]

        dated = client.get(
            "/recordings", params={"from_date": "2026-07-11", "to_date": "2026-07-12"}
        ).json()
        assert [i["id"] for i in dated["items"]] == [exciting.id]

    def test_reclassification_history_uses_latest_verdict(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        seed.classification(rec, is_interesting=False)
        seed.classification(rec, is_interesting=True)

        interesting = client.get("/recordings", params={"interesting": "true"}).json()
        assert [i["id"] for i in interesting["items"]] == [rec.id]
        assert client.get("/recordings", params={"interesting": "false"}).json()["items"] == []

    def test_pagination_and_page_links(self, client, seed):
        freq = seed.frequency()
        base = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)
        ids = [seed.recording(freq, started=base + timedelta(minutes=i)).id for i in range(5)]

        page = client.get("/recordings", params={"limit": 2, "offset": 2}).json()
        assert page["total"] == 5
        assert page["limit"] == 2
        assert page["offset"] == 2
        assert [i["id"] for i in page["items"]] == [ids[2], ids[1]]
        assert "offset=4" in page["_links"]["next"]["href"]
        assert "offset=0" in page["_links"]["prev"]["href"]

    def test_offset_beyond_end_returns_empty_page(self, client, seed):
        freq = seed.frequency()
        seed.recording(freq)
        page = client.get("/recordings", params={"limit": 50, "offset": 100}).json()
        assert page["items"] == []
        assert page["total"] == 1
        assert "next" not in page["_links"]

    def test_limit_bounds_are_validation_problems(self, client):
        for params in ({"limit": 0}, {"limit": 1000}, {"offset": -1}):
            response = client.get("/recordings", params=params)
            assert response.status_code == 422
            assert response.headers["content-type"].startswith(PROBLEM_TYPE)
            assert response.json()["code"] == "validation_error"


class TestRecordingDetail:
    def test_full_provenance(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq, stage=RecordingStage.CLASSIFIED)
        seed.transcript(rec, text="Going around, Speedbird 472.")
        seed.classification(rec, is_interesting=False)
        seed.classification(rec, is_interesting=True, category=ClassificationCategory.GO_AROUND)
        seed.match(rec, rank=1)
        seed.match(rec, rank=2, callsign="RYR815B", match_confidence=0.4)
        seed.feedback(rec, FeedbackVerdict.UP, note="great catch")

        response = client.get(f"/recordings/{rec.id}")

        assert response.status_code == 200
        body = response.json()
        assert body["id"] == rec.id
        assert body["sample_rate"] == 8000
        assert body["file_path"] == rec.file_path
        assert body["transcript"]["text"] == "Going around, Speedbird 472."
        assert body["transcript"]["engine"] == "faster_whisper"
        # newest classification first; the full history is preserved
        assert [c["is_interesting"] for c in body["classifications"]] == [True, False]
        assert body["classification"]["category"] == "go_around"
        assert [m["rank"] for m in body["matches"]] == [1, 2]
        assert body["feedback_entries"][0]["note"] == "great catch"
        assert body["_links"]["reclassify"]["href"] == f"/recordings/{rec.id}/reclassify"
        assert body["_links"]["feedback"]["href"] == f"/recordings/{rec.id}/feedback"

    def test_unknown_recording_is_a_problem_404(self, client):
        response = client.get("/recordings/999")
        assert response.status_code == 404
        assert response.json()["code"] == "recording_not_found"


class TestAudio:
    def test_streams_mp3(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq, audio_bytes=b"0123456789")

        response = client.get(f"/recordings/{rec.id}/audio")

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mpeg"
        assert response.content == b"0123456789"

    def test_supports_range_requests(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq, audio_bytes=b"0123456789")

        response = client.get(f"/recordings/{rec.id}/audio", headers={"Range": "bytes=2-5"})

        assert response.status_code == 206
        assert response.content == b"2345"
        assert response.headers["content-range"] == "bytes 2-5/10"

    def test_pruned_audio_is_410(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq, audio_deleted=True)

        response = client.get(f"/recordings/{rec.id}/audio")

        assert response.status_code == 410
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        assert response.json()["code"] == "audio_deleted"

    def test_missing_file_is_404(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)  # row exists, no file on disk

        response = client.get(f"/recordings/{rec.id}/audio")

        assert response.status_code == 404
        assert response.json()["code"] == "audio_file_missing"

    def test_unknown_recording_is_404(self, client):
        response = client.get("/recordings/999/audio")
        assert response.status_code == 404
        assert response.json()["code"] == "recording_not_found"


class TestReclassify:
    def test_queues_a_classified_clip_for_reclassification(self, client, seed, session):
        freq = seed.frequency()
        rec = seed.recording(freq, stage=RecordingStage.CLASSIFIED)
        seed.transcript(rec)
        seed.classification(rec, is_interesting=False)

        response = client.post(f"/recordings/{rec.id}/reclassify")

        assert response.status_code == 202
        assert response.json()["stage"] == "transcribed"
        session.expire_all()
        from skywatch.db.models import Recording

        assert session.get(Recording, rec.id).stage == RecordingStage.TRANSCRIBED

    def test_already_queued_clip_is_a_no_op(self, client, seed, session):
        freq = seed.frequency()
        rec = seed.recording(freq, stage=RecordingStage.TRANSCRIBED)
        seed.transcript(rec)

        response = client.post(f"/recordings/{rec.id}/reclassify")

        assert response.status_code == 202
        session.expire_all()
        from skywatch.db.models import Recording

        assert session.get(Recording, rec.id).stage == RecordingStage.TRANSCRIBED

    def test_untranscribed_clip_is_a_problem_409(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq, stage=RecordingStage.CAPTURED)

        response = client.post(f"/recordings/{rec.id}/reclassify")

        assert response.status_code == 409
        assert response.json()["code"] == "recording_not_classifiable"

    def test_unknown_recording_is_404(self, client):
        response = client.post("/recordings/999/reclassify")
        assert response.status_code == 404


class TestFeedback:
    def test_records_a_verdict(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)

        response = client.post(
            f"/recordings/{rec.id}/feedback",
            json={"verdict": "up", "note": "worth hearing"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["verdict"] == "up"
        assert body["note"] == "worth hearing"
        assert body["_links"]["recording"]["href"] == f"/recordings/{rec.id}"
        detail = client.get(f"/recordings/{rec.id}").json()
        assert detail["feedback"] == {"up": 1, "down": 0}

    def test_invalid_verdict_is_a_validation_problem(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        response = client.post(f"/recordings/{rec.id}/feedback", json={"verdict": "meh"})
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"

    def test_unknown_recording_is_404(self, client):
        response = client.post("/recordings/999/feedback", json={"verdict": "up"})
        assert response.status_code == 404
