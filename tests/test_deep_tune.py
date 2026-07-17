"""Deep Tune: off-air spectrum sessions.

Everything runs against injectable IQ sources and clocks — no test touches
real SDR hardware. The DSP tests feed a deterministic synthetic carrier and
assert the peak lands in the right bin; the lifecycle tests drive the
session loop with a fake monotonic clock so ten-minute timeouts run in
milliseconds.
"""

import threading
from types import SimpleNamespace

import numpy as np
import pytest

from skywatch.api.services.deep_tune import (
    DEEP_TUNE_IDLE_TIMEOUT_S,
    DEEP_TUNE_WARNING_S,
    DeepTuneChannel,
    DeepTuneConfig,
    DeepTuneManager,
    DeepTuneNotActive,
    PyRtlSdrSourceFactory,
    build_frame,
)

SAMPLE_RATE_MSPS = 2.56
FS_HZ = SAMPLE_RATE_MSPS * 1e6


def synthetic_iq(
    n: int,
    *,
    offset_hz: float,
    amplitude: float = 1.0,
    noise: float = 0.01,
    seed: int = 7,
) -> np.ndarray:
    """A carrier ``offset_hz`` from centre plus gaussian noise, complex64."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / FS_HZ
    carrier = amplitude * np.exp(2j * np.pi * offset_hz * t)
    floor = noise * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    return (carrier + floor).astype(np.complex64)


def config_for(channels_mhz: list[tuple[int, str, float]], center_mhz: float) -> DeepTuneConfig:
    return DeepTuneConfig(
        center_mhz=center_mhz,
        sample_rate_msps=SAMPLE_RATE_MSPS,
        device_index=0,
        gain_db=32.8,
        ppm=0,
        channels=[DeepTuneChannel(freq_id=i, label=lbl, mhz=mhz) for i, lbl, mhz in channels_mhz],
    )


class TestSpectrumFrame:
    """PSD frames from a deterministic synthetic carrier."""

    def test_peak_lands_in_the_carrier_bin(self):
        nfft = 1024
        offset_hz = 200_000.0
        config = config_for([(1, "Tower", 123.905 + 0.2)], center_mhz=123.905)
        frame = build_frame(synthetic_iq(65536, offset_hz=offset_hz), config, nfft=nfft)

        db = frame["db"]
        assert len(db) == nfft
        bin_hz = frame["bin_hz"]
        expected_bin = round(nfft / 2 + offset_hz / bin_hz)
        peak_bin = int(np.argmax(db))
        assert abs(peak_bin - expected_bin) <= 1

        # axis metadata describes the full tuner window around centre
        assert frame["start_mhz"] == pytest.approx(123.905 - SAMPLE_RATE_MSPS / 2, abs=1e-6)
        assert frame["stop_mhz"] == pytest.approx(123.905 + SAMPLE_RATE_MSPS / 2, abs=1e-6)
        assert bin_hz == pytest.approx(FS_HZ / nfft, rel=1e-6)
        assert frame["ts"]

    def test_channel_on_carrier_reads_hot_and_quiet_channel_does_not(self):
        config = config_for(
            [(1, "On carrier", 123.905 + 0.2), (2, "Quiet", 123.905 - 0.5)],
            center_mhz=123.905,
        )
        frame = build_frame(synthetic_iq(65536, offset_hz=200_000.0), config, nfft=1024)

        hot, quiet = frame["channels"]
        assert hot["freq_id"] == 1
        assert hot["power_db"] > frame["noise_floor_db"] + 20
        assert hot["snr_db"] == pytest.approx(hot["power_db"] - frame["noise_floor_db"], abs=0.2)
        assert quiet["power_db"] < hot["power_db"] - 20

    def test_channel_outside_the_window_reads_null(self):
        config = config_for([(1, "Far away", 130.0)], center_mhz=123.905)
        frame = build_frame(synthetic_iq(65536, offset_hz=0.0), config, nfft=1024)

        (channel,) = frame["channels"]
        assert channel["power_db"] is None
        assert channel["snr_db"] is None

    def test_db_values_are_rounded_to_one_decimal(self):
        config = config_for([(1, "Tower", 123.905 + 0.2)], center_mhz=123.905)
        frame = build_frame(synthetic_iq(65536, offset_hz=200_000.0), config, nfft=256)
        assert all(round(value, 1) == value for value in frame["db"])


# -- session lifecycle doubles ---------------------------------------------------


class FakeClock:
    """A monotonic clock whose sleep() jumps time and fires scheduled hooks."""

    def __init__(self) -> None:
        self.now = 0.0
        self._scheduled: list[tuple[float, object]] = []

    def __call__(self) -> float:
        return self.now

    def at(self, when: float, callback) -> None:
        self._scheduled.append((when, callback))
        self._scheduled.sort(key=lambda item: item[0])

    def sleep(self, seconds: float) -> None:
        target = self.now + seconds
        while self._scheduled and self._scheduled[0][0] <= target:
            when, callback = self._scheduled.pop(0)
            self.now = when
            callback()
        self.now = target


class ImmediateThread:
    """Runs the target synchronously so lifecycle tests are deterministic."""

    def __init__(self, target=None, args=(), daemon=None) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)

    def join(self, timeout=None) -> None:
        pass

    def is_alive(self) -> bool:
        return False


class ZeroIQSource:
    """Silent spectrum; optionally blows up after a set number of reads."""

    def __init__(self, log: list[str], *, fail_on_read: int | None = None) -> None:
        self._log = log
        self._fail_on_read = fail_on_read
        self.reads = 0
        self.closed = False

    def read(self, n: int) -> np.ndarray:
        self.reads += 1
        if self._fail_on_read is not None and self.reads >= self._fail_on_read:
            raise RuntimeError("the dongle vanished mid-read")
        return np.zeros(n, dtype=np.complex64)

    def close(self) -> None:
        self.closed = True
        self._log.append("close")


class RecordingFactory:
    def __init__(self, log: list[str], *, fail_on_read: int | None = None) -> None:
        self._log = log
        self._fail_on_read = fail_on_read
        self.source: ZeroIQSource | None = None

    def availability(self) -> str | None:
        return None

    def open(self, config: DeepTuneConfig) -> ZeroIQSource:
        self._log.append("open")
        self.source = ZeroIQSource(self._log, fail_on_read=self._fail_on_read)
        return self.source


def make_manager(
    *,
    clock: FakeClock,
    log: list[str],
    events: list[dict],
    clients_connected=lambda: True,
    fail_on_read: int | None = None,
    frame_interval_s: float = 5.0,
):
    factory = RecordingFactory(log, fail_on_read=fail_on_read)
    manager = DeepTuneManager(
        source_factory=factory,
        publish=events.append,
        stop_capture=lambda: log.append("stop_capture"),
        restart_capture=lambda: log.append("restart_capture"),
        clients_connected=clients_connected,
        clock=clock,
        sleep=clock.sleep,
        thread_factory=ImmediateThread,
        frame_interval_s=frame_interval_s,
        samples_per_frame=2048,
        nfft=256,
    )
    return manager, factory


def default_config() -> DeepTuneConfig:
    return config_for([(1, "Tower", 123.805)], center_mhz=123.905)


def events_of(events: list[dict], event_type: str) -> list[dict]:
    return [event["payload"] for event in events if event["type"] == event_type]


class TestSessionLifecycle:
    def test_idle_timeout_warns_then_exits_and_restarts_capture(self):
        clock, log, events = FakeClock(), [], []
        manager, factory = make_manager(clock=clock, log=log, events=events)

        manager.start(default_config())  # ImmediateThread: runs to auto-exit

        states = events_of(events, "deep_tune.state")
        assert [s["state"] for s in states] == ["started", "warning", "stopped"]
        warning = states[1]
        assert warning["seconds_remaining"] == pytest.approx(DEEP_TUNE_WARNING_S, abs=5.0)
        assert states[2]["reason"] == "idle_timeout"
        assert clock.now == pytest.approx(DEEP_TUNE_IDLE_TIMEOUT_S, abs=5.0)

        # capture stopped before the device opened, restarted after close
        assert log.index("stop_capture") < log.index("open")
        assert log.index("close") < log.index("restart_capture")
        assert not manager.active
        # frames flowed while the session ran, and none after the stop event
        assert events_of(events, "spectrum.frame")
        assert events[-1]["type"] == "deep_tune.state"

    def test_ping_resets_the_idle_clock(self):
        clock, log, events = FakeClock(), [], []
        manager, _ = make_manager(clock=clock, log=log, events=events)
        clock.at(300.0, manager.ping)

        manager.start(default_config())

        states = events_of(events, "deep_tune.state")
        assert states[-1]["reason"] == "idle_timeout"
        assert clock.now == pytest.approx(300.0 + DEEP_TUNE_IDLE_TIMEOUT_S, abs=5.0)

    def test_ws_drop_exits_within_the_presence_window(self):
        clock, log, events = FakeClock(), [], []
        manager, _ = make_manager(
            clock=clock, log=log, events=events, clients_connected=lambda: False
        )

        manager.start(default_config())

        states = events_of(events, "deep_tune.state")
        assert states[-1]["state"] == "stopped"
        assert states[-1]["reason"] == "connection_lost"
        assert clock.now <= 35.0
        assert "restart_capture" in log

    def test_read_loop_exception_still_restarts_capture(self):
        clock, log, events = FakeClock(), [], []
        manager, factory = make_manager(clock=clock, log=log, events=events, fail_on_read=3)

        manager.start(default_config())

        states = events_of(events, "deep_tune.state")
        assert states[-1]["reason"] == "error"
        assert "restart_capture" in log
        assert factory.source is not None and factory.source.closed
        assert not manager.active

    def test_device_open_failure_restarts_capture(self):
        clock, log, events = FakeClock(), [], []

        class BrokenFactory:
            def availability(self):
                return None

            def open(self, config):
                log.append("open")
                raise OSError("usb claim failed")

        manager = DeepTuneManager(
            source_factory=BrokenFactory(),
            publish=events.append,
            stop_capture=lambda: log.append("stop_capture"),
            restart_capture=lambda: log.append("restart_capture"),
            clients_connected=lambda: True,
            clock=clock,
            sleep=clock.sleep,
            thread_factory=ImmediateThread,
        )
        manager.start(default_config())

        assert log == ["stop_capture", "open", "restart_capture"]
        states = events_of(events, "deep_tune.state")
        assert states[-1]["state"] == "stopped"
        assert states[-1]["reason"] == "error"
        assert not manager.active

    def test_stop_when_inactive_raises(self):
        clock, log, events = FakeClock(), [], []
        manager, _ = make_manager(clock=clock, log=log, events=events)
        with pytest.raises(DeepTuneNotActive):
            manager.stop()
        with pytest.raises(DeepTuneNotActive):
            manager.ping()

    def test_requested_stop_from_another_thread(self):
        """A real-thread session exits promptly on stop() and restarts capture."""
        log: list[str] = []
        events: list[dict] = []
        started = threading.Event()

        def publish(event: dict) -> None:
            events.append(event)
            if event["type"] == "spectrum.frame":
                started.set()

        factory = RecordingFactory(log)
        manager = DeepTuneManager(
            source_factory=factory,
            publish=publish,
            stop_capture=lambda: log.append("stop_capture"),
            restart_capture=lambda: log.append("restart_capture"),
            clients_connected=lambda: True,
            frame_interval_s=0.01,
            samples_per_frame=2048,
            nfft=256,
        )
        manager.start(default_config())
        assert started.wait(timeout=5.0)
        assert manager.active
        manager.stop()

        assert not manager.active
        assert "restart_capture" in log
        states = events_of(events, "deep_tune.state")
        assert states[-1]["state"] == "stopped"
        assert states[-1]["reason"] == "requested"


class TestPyRtlSdrFactory:
    def test_missing_pyrtlsdr_reads_as_unavailable(self):
        def import_module(name: str):
            raise ImportError(f"No module named {name!r}")

        factory = PyRtlSdrSourceFactory(import_module=import_module)
        reason = factory.availability()
        assert reason is not None
        assert "not installed" in reason

    def test_present_pyrtlsdr_reads_as_available(self):
        factory = PyRtlSdrSourceFactory(import_module=lambda name: SimpleNamespace())
        assert factory.availability() is None


# -- API surface -------------------------------------------------------------------


class SyntheticAPISource:
    """Carrier on the first configured channel; used by the API-level tests."""

    def __init__(self, config: DeepTuneConfig, factory: "SyntheticAPIFactory") -> None:
        self._config = config
        self._factory = factory

    def read(self, n: int) -> np.ndarray:
        offset_hz = (self._config.channels[0].mhz - self._config.center_mhz) * 1e6
        return synthetic_iq(n, offset_hz=offset_hz)

    def close(self) -> None:
        self._factory.closed += 1


class SyntheticAPIFactory:
    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason
        self.opened: list[DeepTuneConfig] = []
        self.closed = 0

    def availability(self) -> str | None:
        return self.reason

    def open(self, config: DeepTuneConfig) -> SyntheticAPISource:
        self.opened.append(config)
        return SyntheticAPISource(config, self)


@pytest.fixture()
def live_station(engine, tmp_path, monkeypatch):
    """A live-mode station app with a fake capture source and synthetic IQ."""
    from conftest import FakeCaptureSource
    from skywatch.api.app import create_app
    from skywatch.api.services.capture import CaptureController
    from skywatch.settings import CaptureSettings, Settings

    monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
    data_root = tmp_path / "data"
    data_root.mkdir()
    settings = Settings(
        data_root=data_root,
        capture=CaptureSettings(source="live"),
        _env_file=None,
    )
    source = FakeCaptureSource()
    capture = CaptureController(engine=engine, settings=settings, source=source)
    iq_factory = SyntheticAPIFactory()
    app = create_app(
        settings,
        engine=engine,
        capture=capture,
        content_dir=tmp_path / "no-content",
        static_dir=tmp_path / "no-static",
        ws_poll_interval=0.05,
        deep_tune_factory=iq_factory,
    )
    return SimpleNamespace(
        app=app, engine=engine, settings=settings, source=source, iq_factory=iq_factory
    )


@pytest.fixture()
def live_client(live_station):
    from fastapi.testclient import TestClient

    with TestClient(live_station.app) as c:
        yield c


class TestDeepTuneAPI:
    def test_start_stops_capture_and_reports_the_session(self, live_client, live_station, seed):
        seed.frequency()
        live_station.source.calls.clear()

        response = live_client.post("/tuning/deep-tune/start")

        assert response.status_code == 200
        body = response.json()
        assert body["deep_tune"]["active"] is True
        assert body["deep_tune"]["started_at"] is not None
        remaining = body["deep_tune"]["seconds_remaining_before_timeout"]
        assert remaining is not None and remaining <= DEEP_TUNE_IDLE_TIMEOUT_S
        assert body["center_mhz"] is not None
        assert body["span_mhz"] == pytest.approx(2.56)
        assert live_station.source.calls[0] == "stop"
        links = body["_links"]
        assert links["stop"]["href"] == "/tuning/deep-tune/stop"
        assert links["ping"]["href"] == "/tuning/deep-tune/ping"

        # session state surfaces on /tuning and /status
        tuning = live_client.get("/tuning").json()
        assert tuning["deep_tune"]["active"] is True
        status_body = live_client.get("/status").json()
        assert status_body["capture"]["deep_tune_active"] is True

        live_client.post("/tuning/deep-tune/stop")

    def test_double_start_conflicts(self, live_client, seed):
        seed.frequency()
        assert live_client.post("/tuning/deep-tune/start").status_code == 200

        response = live_client.post("/tuning/deep-tune/start")

        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "deep_tune_active"

        live_client.post("/tuning/deep-tune/stop")

    def test_stop_restarts_capture(self, live_client, live_station, seed):
        seed.frequency()
        live_client.post("/tuning/deep-tune/start")
        live_station.source.calls.clear()

        response = live_client.post("/tuning/deep-tune/stop")

        assert response.status_code == 200
        body = response.json()
        assert body["deep_tune"]["active"] is False
        assert body["deep_tune"]["started_at"] is None
        # the exit path restarted capture: stop then start onto the plan
        assert live_station.source.calls == ["stop", "start"]
        assert live_station.iq_factory.closed == 1
        assert live_client.get("/status").json()["capture"]["deep_tune_active"] is False

    def test_stop_when_inactive_is_a_problem(self, live_client):
        response = live_client.post("/tuning/deep-tune/stop")
        assert response.status_code == 409
        assert response.json()["code"] == "deep_tune_not_active"

    def test_ping_keeps_the_session_alive(self, live_client, seed):
        seed.frequency()
        assert live_client.post("/tuning/deep-tune/ping").status_code == 409

        live_client.post("/tuning/deep-tune/start")
        response = live_client.post("/tuning/deep-tune/ping")

        assert response.status_code == 200
        assert response.json()["deep_tune"]["active"] is True

        live_client.post("/tuning/deep-tune/stop")

    def test_apply_is_rejected_while_deep_tune_holds_the_receiver(self, live_client, seed):
        seed.frequency()
        live_client.post("/tuning/deep-tune/start")

        response = live_client.post(
            "/tuning/apply",
            json={"gain_db": 32.8, "squelch_default_snr_db": 12.0, "ppm": 0},
        )

        assert response.status_code == 409
        assert response.json()["code"] == "deep_tune_active"

        live_client.post("/tuning/deep-tune/stop")

    def test_frequency_activate_is_rejected_while_deep_tune_holds_the_receiver(
        self, live_client, live_station, seed, session
    ):
        seed.frequency()
        idle = seed.frequency("Guard", 121.5, is_active=False)
        live_client.post("/tuning/deep-tune/start")
        live_station.source.calls.clear()

        response = live_client.post(f"/frequencies/{idle.id}/activate")

        assert response.status_code == 409
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json()["code"] == "deep_tune_active"
        # the plan and capture were left alone
        session.expire_all()
        from skywatch.db.models import Frequency

        assert session.get(Frequency, idle.id).is_active is False
        assert live_station.source.calls == []

        live_client.post("/tuning/deep-tune/stop")

    def test_frequency_deactivate_is_rejected_while_deep_tune_holds_the_receiver(
        self, live_client, live_station, seed, session
    ):
        active = seed.frequency()
        live_client.post("/tuning/deep-tune/start")
        live_station.source.calls.clear()

        response = live_client.post(f"/frequencies/{active.id}/deactivate")

        assert response.status_code == 409
        assert response.json()["code"] == "deep_tune_active"
        session.expire_all()
        from skywatch.db.models import Frequency

        assert session.get(Frequency, active.id).is_active is True
        assert live_station.source.calls == []

        live_client.post("/tuning/deep-tune/stop")

    def test_replay_station_has_nothing_to_tune(self, client, seed):
        seed.frequency()
        response = client.post("/tuning/deep-tune/start")

        assert response.status_code == 503
        body = response.json()
        assert body["code"] == "deep_tune_unavailable"
        assert "replay" in body["detail"]

    def test_missing_pyrtlsdr_is_a_handled_problem(self, engine, tmp_path, monkeypatch, seed):
        from fastapi.testclient import TestClient

        from conftest import FakeCaptureSource
        from skywatch.api.app import create_app
        from skywatch.api.services.capture import CaptureController
        from skywatch.settings import CaptureSettings, Settings

        seed.frequency()
        monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
        settings = Settings(
            data_root=tmp_path / "data", capture=CaptureSettings(source="live"), _env_file=None
        )
        source = FakeCaptureSource()
        capture = CaptureController(engine=engine, settings=settings, source=source)

        def import_module(name: str):
            raise ImportError(f"No module named {name!r}")

        app = create_app(
            settings,
            engine=engine,
            capture=capture,
            content_dir=tmp_path / "no-content",
            static_dir=tmp_path / "no-static",
            deep_tune_factory=PyRtlSdrSourceFactory(import_module=import_module),
        )
        with TestClient(app) as bare_client:
            response = bare_client.post("/tuning/deep-tune/start")

        assert response.status_code == 503
        assert response.json()["code"] == "deep_tune_unavailable"
        assert "not installed" in response.json()["detail"]
        # capture was never touched: the availability check comes first
        assert source.calls == []

    def test_no_active_frequencies_cannot_start(self, live_client, seed):
        seed.frequency(is_active=False)
        response = live_client.post("/tuning/deep-tune/start")

        assert response.status_code == 503
        assert response.json()["code"] == "deep_tune_unavailable"
        assert "active" in response.json()["detail"]

    def test_stream_carries_state_and_spectrum_frames(self, live_client, live_station, seed):
        freq = seed.frequency()

        with live_client.websocket_connect("/stream") as ws:
            live_client.post("/tuning/deep-tune/start")

            started = ws.receive_json()
            assert started["type"] == "deep_tune.state"
            assert started["payload"]["state"] == "started"
            assert started["payload"]["started_at"] is not None

            frame = ws.receive_json()
            assert frame["type"] == "spectrum.frame"
            payload = frame["payload"]
            assert len(payload["db"]) > 0
            assert payload["start_mhz"] < freq.mhz < payload["stop_mhz"]
            (channel,) = payload["channels"]
            assert channel["freq_id"] == freq.id
            assert channel["mhz"] == freq.mhz
            # the synthetic carrier sits on this channel, so it reads hot
            assert channel["power_db"] > payload["noise_floor_db"] + 20
            assert payload["ts"]

            live_client.post("/tuning/deep-tune/stop")
            message = ws.receive_json()
            while message["type"] == "spectrum.frame":
                message = ws.receive_json()
            assert message["type"] == "deep_tune.state"
            assert message["payload"]["state"] == "stopped"
            assert message["payload"]["reason"] == "requested"

        assert not live_station.app.state.deep_tune.active
