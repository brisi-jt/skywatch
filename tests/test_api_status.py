"""Contract tests for GET /status and the station status builder."""

from skywatch.db.enums import RecordingStage
from skywatch.db.models import Setting
from skywatch.pipeline.retention import CAPTURE_PAUSED_KEY


class TestStatusRoute:
    def test_fresh_station_shape(self, client):
        response = client.get("/status")

        assert response.status_code == 200
        body = response.json()
        # null until the first-run naming dialog has been completed
        assert body["station_name"] is None
        # the dashboard reads its display timezone from here, not a hardcode
        assert body["timezone"] == "Europe/London"
        capture = body["capture"]
        assert capture["source"] == "replay"
        assert capture["mode"] == "multichannel"
        assert capture["running"] is True
        assert capture["paused_for_disk"] is False
        assert capture["dongle_present"] is None
        assert set(body["queues"]) == {stage.value for stage in RecordingStage}
        assert all(count == 0 for count in body["queues"].values())
        disk = body["disk"]
        assert disk["free_gb"] > 0
        assert disk["min_free_gb"] == 2.0
        assert disk["low"] is False
        budgets = body["budgets"]
        assert budgets["llm"]["provider"] == "gemini"
        assert budgets["llm"]["daily_cap"] == 900
        assert budgets["llm"]["calls_today"] == 0
        assert budgets["opensky"]["daily_cap"] == 3000
        trace = body["trace"]
        assert trace["rendered_conf"]["state"] == "not_applicable"
        assert trace["process"]["running"] is True
        assert body["_links"]["self"]["href"] == "/status"

    def test_reflects_station_name_queues_and_pause_flag(self, client, seed, session):
        session.add(Setting(key="station_name", value="My Airband Station"))
        session.add(Setting(key=CAPTURE_PAUSED_KEY, value="1"))
        session.commit()
        freq = seed.frequency()
        seed.recording(freq, stage=RecordingStage.CAPTURED)
        seed.recording(freq, stage=RecordingStage.CLASSIFIED)

        body = client.get("/status").json()

        assert body["station_name"] == "My Airband Station"
        assert body["capture"]["paused_for_disk"] is True
        assert body["queues"]["captured"] == 1
        assert body["queues"]["classified"] == 1
        assert body["capture"]["centerfreq_mhz"] is not None
        assert body["trace"]["db_intent"]["channels"][0]["label"] == "Stansted Tower"


class TestLiveTrace:
    def _live_status(self, engine, tmp_path, monkeypatch, seed, *, write_conf):
        from conftest import FakeCaptureSource
        from skywatch.api.services.capture import CaptureController
        from skywatch.api.services.status import build_status
        from skywatch.settings import CaptureSettings, Settings

        monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
        data_root = tmp_path / "data"
        settings = Settings(
            data_root=data_root, capture=CaptureSettings(source="live"), _env_file=None
        )
        seed.frequency("Guard", 121.5, is_active=True)
        controller = CaptureController(engine=engine, settings=settings, source=FakeCaptureSource())
        if write_conf is not None:
            controller.conf_path.parent.mkdir(parents=True, exist_ok=True)
            controller.conf_path.write_text(write_conf(engine, settings, controller))
        return build_status(seed.session, settings=settings, capture=controller)

    def test_conf_missing(self, engine, tmp_path, monkeypatch, seed):
        status = self._live_status(engine, tmp_path, monkeypatch, seed, write_conf=None)
        assert status.trace.rendered_conf.state == "missing"

    def test_conf_matches_db_intent(self, engine, tmp_path, monkeypatch, seed):
        def render(engine, settings, controller):
            # mirror what LiveSDRSource.write_conf produces: the plan plus
            # database tuning values and the stats file location
            from sqlmodel import Session, select

            from skywatch.db.models import Frequency
            from skywatch.tuning import TuningService

            with Session(engine) as s:
                active = list(s.exec(select(Frequency).where(Frequency.is_active)).all())
                return TuningService(settings.capture).render(
                    s,
                    active,
                    recordings_dir=settings.capture.output_dir.resolve(),
                    stats_filepath=controller.stats_filepath,
                )

        status = self._live_status(engine, tmp_path, monkeypatch, seed, write_conf=render)
        assert status.trace.rendered_conf.state == "match"

    def test_stale_conf_flagged(self, engine, tmp_path, monkeypatch, seed):
        status = self._live_status(
            engine, tmp_path, monkeypatch, seed, write_conf=lambda *a: "# old conf\n"
        )
        assert status.trace.rendered_conf.state == "stale"
