"""Wiring for the launchd deployment topology.

When rtl_airband runs as the com.skywatch.rtl-airband launchd service, both
the worker and the API must supervise it through launchctl in the gui
domain — spawning their own child process would put two rtl_airband
instances on one dongle.
"""

import os

from skywatch.settings import Settings


def make_settings(tmp_path, monkeypatch, **capture_overrides):
    monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
    capture = {"source": "live", **capture_overrides}
    return Settings(data_root=tmp_path / "data", capture=capture, _env_file=None)


class TestSupervisorSetting:
    def test_defaults_to_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
        assert Settings(_env_file=None).capture.supervisor == "subprocess"

    def test_launchctl_selectable(self, tmp_path, monkeypatch):
        settings = make_settings(tmp_path, monkeypatch, supervisor="launchctl")
        assert settings.capture.supervisor == "launchctl"


class TestCaptureControllerWiring:
    def test_live_launchctl_supervises_the_gui_domain_service(self, engine, tmp_path, monkeypatch):
        from skywatch.api.services.capture import CaptureController

        settings = make_settings(tmp_path, monkeypatch, supervisor="launchctl")
        controller = CaptureController(engine=engine, settings=settings)

        source = controller.source
        assert source is not None
        assert source._supervisor == "launchctl"
        assert source._launchd_target == f"gui/{os.getuid()}/com.skywatch.rtl-airband"

    def test_live_default_stays_subprocess(self, engine, tmp_path, monkeypatch):
        from skywatch.api.services.capture import CaptureController

        settings = make_settings(tmp_path, monkeypatch)
        controller = CaptureController(engine=engine, settings=settings)

        assert controller.source._supervisor == "subprocess"


class TestWorkerWiring:
    def test_build_worker_live_launchctl(self, engine, tmp_path, monkeypatch):
        from skywatch.pipeline.worker import build_worker

        settings = make_settings(
            tmp_path,
            monkeypatch,
            supervisor="launchctl",
            output_dir=tmp_path / "data" / "recordings",
        )
        worker = build_worker(settings, engine=engine)

        source = worker._capture_source
        assert source._supervisor == "launchctl"
        assert source._launchd_target == f"gui/{os.getuid()}/com.skywatch.rtl-airband"
