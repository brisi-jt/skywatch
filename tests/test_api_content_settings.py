"""Contract tests for the docs routes, /settings, and app-level plumbing."""

PROBLEM_TYPE = "application/problem+json"


class TestDocs:
    def test_serves_runbook_markdown(self, client, station):
        (station.content_dir / "RUNBOOK.md").write_text("# Runbook\n\nTurn it on.\n")

        response = client.get("/runbook")

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "runbook"
        assert body["markdown"].startswith("# Runbook")
        assert body["_links"]["self"]["href"] == "/runbook"

    def test_serves_glossary_markdown(self, client, station):
        (station.content_dir / "GLOSSARY.md").write_text("# Glossary\n\n**Squawk**: code.\n")
        body = client.get("/glossary").json()
        assert body["name"] == "glossary"
        assert "Squawk" in body["markdown"]

    def test_missing_document_is_a_problem_404(self, client):
        response = client.get("/runbook")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        assert response.json()["code"] == "document_not_found"


class TestSettings:
    def test_get_settings_before_naming(self, client):
        response = client.get("/settings")
        assert response.status_code == 200
        body = response.json()
        assert body["station_name"] is None
        assert body["_links"]["self"]["href"] == "/settings"

    def test_patch_station_name_round_trips(self, client):
        response = client.patch("/settings", json={"station_name": "My Airband Station"})

        assert response.status_code == 200
        assert response.json()["station_name"] == "My Airband Station"
        assert client.get("/settings").json()["station_name"] == "My Airband Station"
        assert client.get("/status").json()["station_name"] == "My Airband Station"

    def test_rename_overwrites(self, client):
        client.patch("/settings", json={"station_name": "First"})
        client.patch("/settings", json={"station_name": "Second"})
        assert client.get("/settings").json()["station_name"] == "Second"

    def test_unknown_key_is_a_problem_400(self, client):
        response = client.patch("/settings", json={"volume": "11"})

        assert response.status_code == 400
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        body = response.json()
        assert body["code"] == "unknown_setting_key"
        assert body["unknown_keys"] == ["volume"]
        assert "station_name" in body["allowed_keys"]

    def test_internal_keys_are_not_writable(self, client):
        from skywatch.pipeline.retention import CAPTURE_PAUSED_KEY

        response = client.patch("/settings", json={CAPTURE_PAUSED_KEY: "0"})
        assert response.status_code == 400
        assert response.json()["code"] == "unknown_setting_key"

    def test_blank_name_is_a_problem_422(self, client):
        response = client.patch("/settings", json={"station_name": "   "})
        assert response.status_code == 422
        assert response.json()["code"] == "invalid_setting_value"


class TestAppPlumbing:
    def test_unknown_path_is_a_problem_404(self, client):
        response = client.get("/nope")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        assert response.json()["code"] == "not_found"

    def test_cors_is_permissive_for_dashboard_dev(self, client):
        response = client.get("/status", headers={"Origin": "http://localhost:3000"})
        assert response.headers["access-control-allow-origin"] == "*"

    def test_docs_render(self, client):
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200

    def test_dashboard_static_mount_when_build_exists(self, engine, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient

        from skywatch.api.app import create_app
        from skywatch.settings import Settings

        monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
        static_dir = tmp_path / "out"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html><body>dashboard</body></html>")
        settings = Settings(data_root=tmp_path / "data", _env_file=None)
        app = create_app(settings, engine=engine, static_dir=static_dir)

        with TestClient(app) as static_client:
            response = static_client.get("/")
            assert response.status_code == 200
            assert "dashboard" in response.text
            # API routes still win over the static mount
            assert static_client.get("/status").status_code == 200
