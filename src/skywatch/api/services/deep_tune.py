"""Deep Tune: an exclusive off-air spectrum session.

One RTL-SDR dongle has one USB claimant, so a live spectrum view cannot run
alongside rtl_airband. A deep tune session therefore stops capture, opens
the device directly through pyrtlsdr, streams averaged-periodogram spectrum
frames over the event stream a few times a second, and restarts capture on
every exit path — a requested stop, an idle timeout, a vanished dashboard,
or a read error all put the station back on air.

The server owns the lifecycle: the session ends itself after ten minutes
without interaction (with a one-minute warning event first) and within about
thirty seconds of losing every stream client. The IQ source, the clock, and
the thread factory are all injectable so the whole lifecycle is testable
without hardware or wall-clock waits.
"""

import contextlib
import importlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

try:
    import numpy as np
except ImportError:  # stations without the optional tuning extras
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

DEEP_TUNE_IDLE_TIMEOUT_S = 600.0
"""Sessions end after this long without a ping."""

DEEP_TUNE_WARNING_S = 60.0
"""A warning event fires this many seconds before the idle timeout."""

DEEP_TUNE_PRESENCE_TIMEOUT_S = 30.0
"""Sessions end this long after losing every stream client and ping."""

DEEP_TUNE_FRAME_INTERVAL_S = 0.4
"""Pause between spectrum frames (2.5 frames per second)."""

DEEP_TUNE_SAMPLES_PER_FRAME = 65536
"""IQ samples read per frame: 25.6 ms of signal at 2.56 Msps."""

DEEP_TUNE_NFFT = 1024
"""Spectrum resolution: 2.56 MHz / 1024 = 2.5 kHz per bin."""

CHANNEL_BANDWIDTH_HZ = 12_500.0
"""Width of the band integrated for each channel's power readout — one
VHF airband channel at 25 kHz spacing, halved to stay clear of neighbours."""

MISSING_SUPPORT_DETAIL = (
    "spectrum support is not installed on this station: deep tune needs the "
    "optional pyrtlsdr receiver library (install the project's 'tuning' extra)"
)


class DeepTuneActive(Exception):
    """A session is already running; the receiver is single-occupancy."""


class DeepTuneNotActive(Exception):
    """No session is running to stop or keep alive."""


@dataclass(frozen=True)
class DeepTuneChannel:
    """One active frequency to read band power for."""

    freq_id: int
    label: str
    mhz: float


@dataclass(frozen=True)
class DeepTuneConfig:
    """Everything a session needs to open the device and label the window."""

    center_mhz: float
    sample_rate_msps: float
    device_index: int
    gain_db: float
    ppm: int
    channels: list[DeepTuneChannel] = field(default_factory=list)


@dataclass(frozen=True)
class DeepTuneStatus:
    """Session state as reported on /tuning and the deep-tune endpoints."""

    active: bool
    started_at: datetime | None = None
    seconds_remaining_before_timeout: float | None = None
    center_mhz: float | None = None
    span_mhz: float | None = None


class IQSource(Protocol):
    """A stream of complex baseband samples from an opened receiver."""

    def read(self, n: int) -> Any: ...

    def close(self) -> None: ...


class IQSourceFactory(Protocol):
    """Opens receivers, and knows ahead of time whether it can."""

    def availability(self) -> str | None:
        """None when a session could start, else a plain-language reason."""
        ...

    def open(self, config: DeepTuneConfig) -> IQSource: ...


# -- spectrum maths ------------------------------------------------------------------


def welch_psd_db(iq: Any, nfft: int) -> Any:
    """Averaged-periodogram power spectral density in dB, centre-shifted.

    Hann-windowed segments with 50% overlap, vectorised end to end — the
    per-sample-Python trap is what makes 2.56 Msps unaffordable, so every
    step here stays inside numpy. 0 dB corresponds to a full-scale carrier.
    """
    samples = np.asarray(iq, dtype=np.complex64)
    if len(samples) < nfft:
        raise ValueError(f"need at least {nfft} samples for a {nfft}-point spectrum")
    window = np.hanning(nfft).astype(np.float32)
    step = nfft // 2
    segments = np.lib.stride_tricks.sliding_window_view(samples, nfft)[::step]
    spectra = np.fft.fft(segments * window, axis=1)
    psd = np.mean(np.abs(spectra) ** 2, axis=0) / (window.sum() ** 2)
    return 10.0 * np.log10(np.fft.fftshift(psd) + 1e-20)


def build_frame(iq: Any, config: DeepTuneConfig, *, nfft: int = DEEP_TUNE_NFFT) -> dict:
    """One spectrum.frame payload: axis metadata, dB curve, channel powers."""
    sample_rate_hz = config.sample_rate_msps * 1e6
    db = welch_psd_db(iq, nfft)
    linear = 10.0 ** (db / 10.0)
    bin_hz = sample_rate_hz / nfft
    start_hz = config.center_mhz * 1e6 - sample_rate_hz / 2
    noise_floor_db = float(np.median(db))

    channels = []
    half_band_bins = (CHANNEL_BANDWIDTH_HZ / 2) / bin_hz
    for channel in config.channels:
        centre_bin = (channel.mhz * 1e6 - start_hz) / bin_hz
        lo = int(round(centre_bin - half_band_bins))
        hi = int(round(centre_bin + half_band_bins))
        power_db: float | None = None
        snr_db: float | None = None
        if hi >= 0 and lo < nfft:
            band = linear[max(lo, 0) : min(hi, nfft - 1) + 1]
            power_db = round(float(10.0 * np.log10(band.sum() + 1e-20)), 1)
            snr_db = round(power_db - noise_floor_db, 1)
        channels.append(
            {
                "freq_id": channel.freq_id,
                "label": channel.label,
                "mhz": channel.mhz,
                "power_db": power_db,
                "snr_db": snr_db,
            }
        )

    return {
        "start_mhz": round(start_hz / 1e6, 6),
        "stop_mhz": round((start_hz + sample_rate_hz) / 1e6, 6),
        "bin_hz": round(bin_hz, 3),
        "db": [round(value, 1) for value in db.tolist()],
        "noise_floor_db": round(noise_floor_db, 1),
        "channels": channels,
        "ts": datetime.now(UTC).isoformat(),
    }


# -- receiver access -----------------------------------------------------------------


class PyRtlSdrSourceFactory:
    """Opens the real dongle through pyrtlsdr.

    The import is deferred and injectable: stations without the tuning
    extras (or without librtlsdr on the host) report a plain-language
    availability reason instead of failing at startup.
    """

    def __init__(self, import_module: Callable[[str], Any] = importlib.import_module) -> None:
        self._import_module = import_module

    def availability(self) -> str | None:
        if np is None:
            return MISSING_SUPPORT_DETAIL
        try:
            # importing rtlsdr also loads librtlsdr, so a missing shared
            # library surfaces here rather than mid-session
            self._import_module("rtlsdr")
        except Exception:
            return MISSING_SUPPORT_DETAIL
        return None

    def open(self, config: DeepTuneConfig) -> IQSource:
        module = self._import_module("rtlsdr")
        device = module.RtlSdr(device_index=config.device_index)
        try:
            device.sample_rate = config.sample_rate_msps * 1e6
            device.center_freq = config.center_mhz * 1e6
            if config.ppm:
                device.freq_correction = config.ppm
            device.gain = config.gain_db
        except Exception:
            with contextlib.suppress(Exception):
                device.close()
            raise
        return _PyRtlSdrSource(device)


class _PyRtlSdrSource:
    def __init__(self, device: Any) -> None:
        self._device = device

    def read(self, n: int) -> Any:
        return self._device.read_samples(n).astype(np.complex64)

    def close(self) -> None:
        self._device.close()


# -- the session ---------------------------------------------------------------------


class DeepTuneManager:
    """Owns the single deep tune session and its server-side lifecycle.

    The read loop runs in a daemon thread: it publishes one spectrum frame
    per interval, checks the idle and presence deadlines against the
    injected monotonic clock, and — in a ``finally`` that covers every exit
    path including exceptions — restarts capture and announces the stop.
    """

    def __init__(
        self,
        *,
        source_factory: IQSourceFactory,
        publish: Callable[[dict], None],
        stop_capture: Callable[[], None],
        restart_capture: Callable[[], None],
        clients_connected: Callable[[], bool],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] | None = None,
        thread_factory: Callable[..., Any] = threading.Thread,
        idle_timeout_s: float = DEEP_TUNE_IDLE_TIMEOUT_S,
        warning_s: float = DEEP_TUNE_WARNING_S,
        presence_timeout_s: float = DEEP_TUNE_PRESENCE_TIMEOUT_S,
        frame_interval_s: float = DEEP_TUNE_FRAME_INTERVAL_S,
        samples_per_frame: int = DEEP_TUNE_SAMPLES_PER_FRAME,
        nfft: int = DEEP_TUNE_NFFT,
    ) -> None:
        self._factory = source_factory
        self._publish_raw = publish
        self._stop_capture = stop_capture
        self._restart_capture = restart_capture
        self._clients_connected = clients_connected
        self._clock = clock
        self._thread_factory = thread_factory
        self._idle_timeout_s = idle_timeout_s
        self._warning_s = warning_s
        self._presence_timeout_s = presence_timeout_s
        self._frame_interval_s = frame_interval_s
        self._samples_per_frame = samples_per_frame
        self._nfft = nfft

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        # the default sleep waits on the stop event, so a requested stop
        # interrupts the pause between frames instead of riding it out
        self._sleep: Callable[[float], None] = sleep or (lambda s: self._stop_event.wait(s))
        self._thread: Any = None
        self._config: DeepTuneConfig | None = None
        self._active = False
        self._started_at: datetime | None = None
        self._started_monotonic = 0.0
        self._last_interaction = 0.0
        self._last_ping: float | None = None
        self._warning_sent = False

    # -- state ---------------------------------------------------------------------

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def availability(self) -> str | None:
        """None when a session could start, else a plain-language reason."""
        return self._factory.availability()

    def state(self) -> DeepTuneStatus:
        with self._lock:
            if not self._active or self._config is None:
                return DeepTuneStatus(active=False)
            remaining = self._idle_timeout_s - (self._clock() - self._last_interaction)
            return DeepTuneStatus(
                active=True,
                started_at=self._started_at,
                seconds_remaining_before_timeout=max(0.0, round(remaining, 1)),
                center_mhz=self._config.center_mhz,
                span_mhz=self._config.sample_rate_msps,
            )

    # -- lifecycle -----------------------------------------------------------------

    def start(self, config: DeepTuneConfig) -> None:
        """Stop capture and begin streaming spectrum frames.

        Raises :class:`DeepTuneActive` when a session is already running.
        If anything fails between stopping capture and the session thread
        taking over, capture is restarted before the error propagates.
        """
        with self._lock:
            if self._active:
                raise DeepTuneActive
            self._active = True
            now = self._clock()
            self._config = config
            self._started_at = datetime.now(UTC)
            self._started_monotonic = now
            self._last_interaction = now
            self._last_ping = None
            self._warning_sent = False
            self._stop_event.clear()
        try:
            self._stop_capture()
            thread = self._thread_factory(target=self._run, args=(config,), daemon=True)
            self._thread = thread
            thread.start()
        except BaseException:
            with self._lock:
                self._active = False
            self._safe_restart_capture()
            raise

    def stop(self) -> None:
        """End the session; the exit path restarts capture before returning."""
        with self._lock:
            if not self._active:
                raise DeepTuneNotActive
            thread = self._thread
        self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10.0)

    def ping(self) -> None:
        """Interaction keep-alive: resets the idle clock and presence window."""
        with self._lock:
            if not self._active:
                raise DeepTuneNotActive
            now = self._clock()
            self._last_interaction = now
            self._last_ping = now
            self._warning_sent = False

    def shutdown(self) -> None:
        """End any running session; safe to call when none is running."""
        with contextlib.suppress(DeepTuneNotActive):
            self.stop()

    # -- the read loop ---------------------------------------------------------------

    def _run(self, config: DeepTuneConfig) -> None:
        reason = "stopped"
        try:
            source = self._factory.open(config)
            try:
                self._publish_state("started")
                while True:
                    if self._stop_event.is_set():
                        reason = "requested"
                        break
                    deadline_reason = self._check_deadlines(self._clock())
                    if deadline_reason is not None:
                        reason = deadline_reason
                        break
                    iq = source.read(self._samples_per_frame)
                    frame = build_frame(iq, config, nfft=self._nfft)
                    self._publish({"type": "spectrum.frame", "payload": frame})
                    self._sleep(self._frame_interval_s)
            finally:
                with contextlib.suppress(Exception):
                    source.close()
        except Exception:
            logger.exception("deep tune session failed; restarting capture")
            reason = "error"
        finally:
            self._safe_restart_capture()
            with self._lock:
                self._active = False
                started_at = self._started_at
                self._config = None
                self._started_at = None
            self._publish_state("stopped", reason=reason, started_at=started_at)

    def _check_deadlines(self, now: float) -> str | None:
        with self._lock:
            remaining = self._idle_timeout_s - (now - self._last_interaction)
            if remaining <= 0:
                return "idle_timeout"
            if remaining <= self._warning_s and not self._warning_sent:
                self._warning_sent = True
                self._publish_state("warning", seconds_remaining=round(remaining, 1))
            last_seen = self._started_monotonic
            if self._last_ping is not None:
                last_seen = max(last_seen, self._last_ping)
        if not self._clients_connected() and now - last_seen >= self._presence_timeout_s:
            return "connection_lost"
        return None

    # -- plumbing ----------------------------------------------------------------------

    def _safe_restart_capture(self) -> None:
        try:
            self._restart_capture()
        except Exception:
            logger.exception("capture restart after deep tune failed")

    def _publish(self, message: dict) -> None:
        try:
            self._publish_raw(message)
        except Exception:
            logger.exception("deep tune event publish failed")

    def _publish_state(
        self,
        state: str,
        *,
        reason: str | None = None,
        seconds_remaining: float | None = None,
        started_at: datetime | None = None,
    ) -> None:
        if started_at is None:
            with self._lock:
                started_at = self._started_at
        self._publish(
            {
                "type": "deep_tune.state",
                "payload": {
                    "state": state,
                    "reason": reason,
                    "started_at": started_at.isoformat() if started_at else None,
                    "seconds_remaining": seconds_remaining,
                },
            }
        )
