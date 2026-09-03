"""Contract tests for incident bundles: /incidents and its clip membership."""

from datetime import UTC, datetime

PROBLEM_TYPE = "application/problem+json"


class TestListAndCreate:
    def test_empty_library(self, client):
        body = client.get("/incidents").json()
        assert body["items"] == []
        assert body["_links"]["self"]["href"] == "/incidents"

    def test_create_starts_empty(self, client):
        response = client.post("/incidents", json={"title": "Go-around sequence"})

        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Go-around sequence"
        assert body["clips"] == []
        assert body["_links"]["self"]["href"] == f"/incidents/{body['id']}"

    def test_create_rejects_blank_title(self, client):
        response = client.post("/incidents", json={"title": ""})
        assert response.status_code == 422

    def test_list_is_newest_first_with_clip_counts(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        first = client.post("/incidents", json={"title": "First"}).json()
        second = client.post("/incidents", json={"title": "Second"}).json()
        client.post(f"/incidents/{first['id']}/clips", json={"recording_id": rec.id})

        body = client.get("/incidents").json()

        assert [item["id"] for item in body["items"]] == [second["id"], first["id"]]
        assert body["items"][1]["clip_count"] == 1
        assert body["items"][0]["clip_count"] == 0


class TestIncidentDetail:
    def test_unknown_incident_is_404(self, client):
        response = client.get("/incidents/999")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        assert response.json()["code"] == "incident_not_found"

    def test_delete_unknown_incident_is_404(self, client):
        assert client.delete("/incidents/999").status_code == 404


class TestClipMembership:
    def test_add_clips_in_order(self, client, seed):
        freq = seed.frequency()
        first = seed.recording(freq, started=datetime(2026, 7, 10, 9, 0, tzinfo=UTC))
        second = seed.recording(freq, started=datetime(2026, 7, 10, 9, 5, tzinfo=UTC))
        incident = client.post("/incidents", json={"title": "Sequence"}).json()

        r1 = client.post(f"/incidents/{incident['id']}/clips", json={"recording_id": first.id})
        assert r1.status_code == 201
        r2 = client.post(f"/incidents/{incident['id']}/clips", json={"recording_id": second.id})
        assert r2.status_code == 201

        detail = client.get(f"/incidents/{incident['id']}").json()
        assert [c["position"] for c in detail["clips"]] == [0, 1]
        assert [c["recording"]["id"] for c in detail["clips"]] == [first.id, second.id]

    def test_adding_the_same_clip_twice_is_a_conflict(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        incident = client.post("/incidents", json={"title": "Sequence"}).json()
        client.post(f"/incidents/{incident['id']}/clips", json={"recording_id": rec.id})

        response = client.post(f"/incidents/{incident['id']}/clips", json={"recording_id": rec.id})

        assert response.status_code == 409
        assert response.json()["code"] == "recording_already_in_incident"

    def test_add_clip_to_unknown_incident_is_404(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        response = client.post("/incidents/999/clips", json={"recording_id": rec.id})
        assert response.status_code == 404
        assert response.json()["code"] == "incident_not_found"

    def test_add_unknown_recording_is_404(self, client):
        incident = client.post("/incidents", json={"title": "Sequence"}).json()
        response = client.post(f"/incidents/{incident['id']}/clips", json={"recording_id": 999})
        assert response.status_code == 404
        assert response.json()["code"] == "recording_not_found"

    def test_remove_clip_closes_the_gap(self, client, seed):
        freq = seed.frequency()
        first = seed.recording(freq, started=datetime(2026, 7, 10, 9, 0, tzinfo=UTC))
        second = seed.recording(freq, started=datetime(2026, 7, 10, 9, 5, tzinfo=UTC))
        third = seed.recording(freq, started=datetime(2026, 7, 10, 9, 10, tzinfo=UTC))
        incident = client.post("/incidents", json={"title": "Sequence"}).json()
        for rec in (first, second, third):
            client.post(f"/incidents/{incident['id']}/clips", json={"recording_id": rec.id})

        response = client.delete(f"/incidents/{incident['id']}/clips/{second.id}")

        assert response.status_code == 200
        body = response.json()
        assert [c["recording"]["id"] for c in body["clips"]] == [first.id, third.id]
        assert [c["position"] for c in body["clips"]] == [0, 1]

    def test_remove_unknown_membership_is_404(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        incident = client.post("/incidents", json={"title": "Sequence"}).json()
        response = client.delete(f"/incidents/{incident['id']}/clips/{rec.id}")
        assert response.status_code == 404
        assert response.json()["code"] == "incident_clip_not_found"

    def test_delete_incident_removes_its_memberships(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        incident = client.post("/incidents", json={"title": "Sequence"}).json()
        client.post(f"/incidents/{incident['id']}/clips", json={"recording_id": rec.id})

        response = client.delete(f"/incidents/{incident['id']}")

        assert response.status_code == 204
        assert client.get(f"/incidents/{incident['id']}").status_code == 404
        # the clip itself survives the incident's deletion
        assert client.get(f"/recordings/{rec.id}").status_code == 200
