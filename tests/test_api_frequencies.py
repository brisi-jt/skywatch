"""Contract tests for the frequency-plan routes."""

PROBLEM_TYPE = "application/problem+json"


class TestListFrequencies:
    def test_lists_plan_ordered_by_mhz_with_links(self, client, seed):
        tower = seed.frequency("Stansted Tower", 123.805, is_active=True)
        guard = seed.frequency("Guard", 121.5, is_active=False, verified=True)

        response = client.get("/frequencies")

        assert response.status_code == 200
        body = response.json()
        assert body["_links"]["self"]["href"] == "/frequencies"
        items = body["items"]
        assert [item["mhz"] for item in items] == [121.5, 123.805]
        assert items[0]["verified"] is True
        # an inactive row offers activate; an active row offers deactivate
        assert "activate" in items[0]["_links"]
        assert "deactivate" not in items[0]["_links"]
        assert items[1]["_links"]["deactivate"]["href"] == (f"/frequencies/{tower.id}/deactivate")
        assert items[0]["_links"]["recordings"]["href"] == (f"/recordings?freq_id={guard.id}")

    def test_empty_plan_lists_nothing(self, client):
        response = client.get("/frequencies")
        assert response.status_code == 200
        assert response.json()["items"] == []


class TestActivate:
    def test_activate_updates_db_and_restarts_capture(self, client, station, seed, session):
        freq = seed.frequency("Guard", 121.5, is_active=False)

        response = client.post(f"/frequencies/{freq.id}/activate")

        assert response.status_code == 200
        body = response.json()
        assert body["frequency"]["is_active"] is True
        assert body["capture_restarted"] is True
        assert station.source.calls == ["stop", "start"]
        session.expire_all()
        from skywatch.db.models import Frequency

        assert session.get(Frequency, freq.id).is_active is True

    def test_activate_is_idempotent(self, client, station, seed):
        freq = seed.frequency("Guard", 121.5, is_active=True)
        response = client.post(f"/frequencies/{freq.id}/activate")
        assert response.status_code == 200
        assert response.json()["capture_restarted"] is False
        assert station.source.calls == []

    def test_unknown_frequency_is_a_problem_404(self, client):
        response = client.post("/frequencies/999/activate")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        body = response.json()
        assert body["code"] == "frequency_not_found"
        assert body["status"] == 404

    def test_window_conflict_is_a_problem_409_with_structured_fields(
        self, client, station, seed, session
    ):
        seed.frequency("Clacton", 118.48, is_active=True)
        seed.frequency("Lambourne", 118.825, is_active=True)
        seed.frequency("Approach", 120.625, is_active=True)
        far = seed.frequency("Tower", 123.805, is_active=False)

        response = client.post(f"/frequencies/{far.id}/activate")

        assert response.status_code == 409
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        body = response.json()
        assert body["code"] == "window_conflict"
        assert body["offenders"] == ["Tower"]
        assert body["suggested_centerfreq_mhz"] is not None
        assert "scan" in body["detail"]
        # the conflict left the plan untouched and capture alone
        session.expire_all()
        from skywatch.db.models import Frequency

        assert session.get(Frequency, far.id).is_active is False
        assert station.source.calls == []

    def test_scan_mode_activation_returns_concurrency_warning(
        self, engine, tmp_path, monkeypatch, seed
    ):
        from fastapi.testclient import TestClient

        from conftest import FakeCaptureSource
        from skywatch.api.app import create_app
        from skywatch.api.services.capture import CaptureController
        from skywatch.settings import CaptureSettings, Settings

        monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
        settings = Settings(
            data_root=tmp_path / "data",
            capture=CaptureSettings(mode="scan"),
            _env_file=None,
        )
        source = FakeCaptureSource()
        capture = CaptureController(engine=engine, settings=settings, source=source)
        app = create_app(settings, engine=engine, capture=capture)
        seed.frequency("Clacton", 118.48, is_active=True)
        far = seed.frequency("Tower", 123.805, is_active=False)

        with TestClient(app) as scan_client:
            response = scan_client.post(f"/frequencies/{far.id}/activate")

        assert response.status_code == 200
        assert any("miss" in warning for warning in response.json()["warnings"])


class TestDeactivate:
    def test_deactivate_updates_db_and_restarts_capture(self, client, station, seed, session):
        seed.frequency("Guard", 121.5, is_active=True)
        tower = seed.frequency("Stansted Tower", 123.805, is_active=True)

        response = client.post(f"/frequencies/{tower.id}/deactivate")

        assert response.status_code == 200
        assert response.json()["frequency"]["is_active"] is False
        assert station.source.calls == ["stop", "start"]

    def test_deactivating_the_last_frequency_stops_capture(self, client, station, seed):
        only = seed.frequency("Guard", 121.5, is_active=True)

        response = client.post(f"/frequencies/{only.id}/deactivate")

        assert response.status_code == 200
        body = response.json()
        assert body["capture_restarted"] is False
        assert any("no active frequencies" in w for w in body["warnings"])
        assert station.source.calls == ["stop"]

    def test_deactivate_is_idempotent(self, client, station, seed):
        freq = seed.frequency("Guard", 121.5, is_active=False)
        response = client.post(f"/frequencies/{freq.id}/deactivate")
        assert response.status_code == 200
        assert station.source.calls == []

    def test_unknown_frequency_is_a_problem_404(self, client):
        response = client.post("/frequencies/999/deactivate")
        assert response.status_code == 404
        assert response.json()["code"] == "frequency_not_found"
