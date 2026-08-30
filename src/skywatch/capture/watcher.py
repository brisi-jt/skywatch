"""Turns clip files in the recordings directory into ``recordings`` rows.

rtl_airband writes each transmission to its own MP3 whose filename carries
the UTC start time and frequency; nothing else identifies the clip. The
watcher picks files up via filesystem events, waits for their size to
settle (rtl_airband streams into the file while the squelch is open), then
ingests them exactly once with stage ``captured``.

Also home to ``probe_mp3``, a dependency-free MP3 frame walker that yields
the sample rate, channel count, and duration the ``recordings`` row needs.
"""

import logging
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from skywatch.capture.filenames import parse_recording_filename
from skywatch.db.engine import session_scope
from skywatch.db.enums import RecordingStage
from skywatch.db.models import Frequency, Recording

logger = logging.getLogger(__name__)

FREQ_MATCH_TOLERANCE_HZ = 1_000
"""A filename frequency must sit within this of a plan row to match it."""

# MPEG audio header tables, Layer III only (all rtl_airband emits).
_BITRATES_KBPS = {
    "mpeg1": (None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    "mpeg2": (None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}
_SAMPLE_RATES = {
    3: (44100, 48000, 32000),  # MPEG1
    2: (22050, 24000, 16000),  # MPEG2
    0: (11025, 12000, 8000),  # MPEG2.5
}


@dataclass(frozen=True)
class Mp3Info:
    sample_rate: int
    channels: int
    duration_s: float


def _syncsafe(raw: bytes) -> int:
    return (raw[0] << 21) | (raw[1] << 14) | (raw[2] << 7) | raw[3]


def probe_mp3(path: Path) -> Mp3Info:
    """Sample rate, channels, and duration by walking MPEG Layer III frames.

    Raises ``ValueError`` when the file contains no decodable audio frames.
    """
    data = path.read_bytes()
    pos = 0
    if data[:3] == b"ID3" and len(data) >= 10:
        pos = 10 + _syncsafe(data[6:10])

    sample_rate: int | None = None
    channels = 1
    total_samples = 0
    while pos + 4 <= len(data):
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        version = (data[pos + 1] >> 3) & 0x3
        layer = (data[pos + 1] >> 1) & 0x3
        bitrate_idx = (data[pos + 2] >> 4) & 0xF
        rate_idx = (data[pos + 2] >> 2) & 0x3
        padding = (data[pos + 2] >> 1) & 0x1
        if version == 1 or layer != 1 or bitrate_idx in (0, 15) or rate_idx == 3:
            pos += 1  # false sync or unsupported frame; keep scanning
            continue
        bitrate_kbps = _BITRATES_KBPS["mpeg1" if version == 3 else "mpeg2"][bitrate_idx]
        frame_rate = _SAMPLE_RATES[version][rate_idx]
        samples_per_frame = 1152 if version == 3 else 576
        frame_len = (samples_per_frame // 8 * bitrate_kbps * 1000) // frame_rate + padding
        if frame_len <= 4:
            pos += 1
            continue
        if sample_rate is None:
            sample_rate = frame_rate
            channels = 1 if ((data[pos + 3] >> 6) & 0x3) == 3 else 2
        total_samples += samples_per_frame
        pos += frame_len

    if sample_rate is None or total_samples == 0:
        raise ValueError(f"no MPEG audio frames found in {path}")
    return Mp3Info(
        sample_rate=sample_rate,
        channels=channels,
        duration_s=total_samples / sample_rate,
    )


def _match_frequency(session: Session, freq_hz: int) -> Frequency | None:
    # Only active frequencies are being recorded, so a clip must belong to one.
    # Matching an inactive row would revive a channel the operator switched off
    # (e.g. a stray file left over from a previous plan).
    rows: Sequence[Frequency] = session.exec(
        select(Frequency).where(Frequency.is_active)  # type: ignore[arg-type]
    ).all()
    best: Frequency | None = None
    best_delta = FREQ_MATCH_TOLERANCE_HZ + 1
    for row in rows:
        delta = abs(round(row.mhz * 1_000_000) - freq_hz)
        if delta < best_delta:
            best, best_delta = row, delta
    return best if best_delta <= FREQ_MATCH_TOLERANCE_HZ else None


def ingest_recording(session: Session, *, path: Path, data_root: Path) -> Recording | None:
    """Create the ``recordings`` row for one clip file, exactly once.

    Returns the new row, or ``None`` when the file is not ingestable
    (foreign filename, unknown frequency, unreadable audio) or was already
    ingested — the same file never produces two rows.
    """
    parsed = parse_recording_filename(path.name)
    if parsed is None:
        logger.warning("ignoring file with foreign name: %s", path)
        return None

    rel_path = Path(os.path.relpath(path, data_root)).as_posix()
    existing = session.exec(select(Recording).where(Recording.file_path == rel_path)).first()
    if existing is not None:
        return None

    frequency = _match_frequency(session, parsed.freq_hz)
    if frequency is None:
        logger.warning(
            "no frequency within %d Hz of %d Hz in the plan; skipping %s",
            FREQ_MATCH_TOLERANCE_HZ,
            parsed.freq_hz,
            path,
        )
        return None

    try:
        info = probe_mp3(path)
    except (OSError, ValueError):
        logger.warning("unreadable audio, skipping %s", path, exc_info=True)
        return None

    recording = Recording(
        freq_id=frequency.id,
        started_at_utc=parsed.started_at_utc,
        ended_at_utc=parsed.started_at_utc + timedelta(seconds=info.duration_s),
        duration_s=info.duration_s,
        file_path=rel_path,
        sample_rate=info.sample_rate,
        stage=RecordingStage.CAPTURED,
    )
    session.add(recording)
    logger.info(
        "captured %s: %.2fs on %s (%.3f MHz)",
        rel_path,
        info.duration_s,
        frequency.label,
        frequency.mhz,
    )
    return recording


class _ClipEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: "RecordingWatcher") -> None:
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        self._watcher.track(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._watcher.track(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._watcher.track(event.dest_path)


class RecordingWatcher:
    """Watches the recordings tree and ingests clips once they stop growing.

    A clip is considered complete when its size has not changed for
    ``settle_seconds`` — rtl_airband holds the file open and appends while
    the squelch is open, and closes it silently when the transmission ends.
    """

    def __init__(
        self,
        engine: Engine,
        recordings_dir: Path,
        *,
        data_root: Path,
        settle_seconds: float = 2.0,
        poll_interval: float = 0.5,
        max_ingest_attempts: int = 5,
    ) -> None:
        self._engine = engine
        self._recordings_dir = Path(recordings_dir)
        self._data_root = Path(data_root)
        self._settle_seconds = settle_seconds
        self._poll_interval = poll_interval
        self._max_ingest_attempts = max(1, max_ingest_attempts)
        # path -> (last-seen size, monotonic time it becomes eligible to ingest)
        self._pending: dict[Path, tuple[int, float]] = {}
        # path -> failed ingest attempts, so a transient error backs off and
        # retries instead of dropping the clip
        self._ingest_attempts: dict[Path, int] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._observer: Observer | None = None
        self._thread: threading.Thread | None = None

    def track(self, raw_path: str | bytes) -> None:
        path = Path(os.fsdecode(raw_path))
        if path.suffix.lower() != ".mp3":
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        with self._lock:
            current = self._pending.get(path)
            if current is None or current[0] != size:
                self._pending[path] = (size, time.monotonic() + self._settle_seconds)

    def scan_existing(self) -> None:
        """Queue clips already on disk (e.g. written while we were down)."""
        for path in self._recordings_dir.rglob("*.mp3"):
            self.track(str(path))

    def _settled(self) -> list[Path]:
        now = time.monotonic()
        ready: list[Path] = []
        with self._lock:
            for path, (size, ready_at) in list(self._pending.items()):
                try:
                    current_size = path.stat().st_size
                except OSError:
                    del self._pending[path]  # vanished before it settled
                    self._ingest_attempts.pop(path, None)
                    continue
                if current_size != size:
                    self._pending[path] = (current_size, now + self._settle_seconds)
                elif now >= ready_at:
                    ready.append(path)
                    del self._pending[path]
        return ready

    def _requeue_failed(self, path: Path) -> None:
        """Re-queue a clip whose ingest raised, with a capped exponential
        backoff. Once the cap is reached the clip is abandoned with a loud
        log rather than retried forever."""
        attempts = self._ingest_attempts.get(path, 0) + 1
        if attempts >= self._max_ingest_attempts:
            logger.error("giving up on %s after %d ingest attempts", path, attempts)
            self._ingest_attempts.pop(path, None)
            return
        self._ingest_attempts[path] = attempts
        try:
            size = path.stat().st_size
        except OSError:
            self._ingest_attempts.pop(path, None)  # vanished; nothing to retry
            return
        backoff = self._settle_seconds * (2 ** (attempts - 1))
        with self._lock:
            self._pending[path] = (size, time.monotonic() + backoff)

    def _process_settled(self) -> None:
        """One ingest pass: attempt every settled clip, re-queuing failures.

        A clip is only removed from tracking once its ingest returns (whether
        it produced a row or was a legitimate skip). An ingest that raises is
        re-queued with backoff, so a transient database error never silently
        drops a captured clip.
        """
        for path in self._settled():
            try:
                with session_scope(self._engine) as session:
                    ingest_recording(session, path=path, data_root=self._data_root)
            except Exception:
                logger.exception("failed to ingest %s; will retry", path)
                self._requeue_failed(path)
            else:
                self._ingest_attempts.pop(path, None)

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_interval):
            self._process_settled()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._recordings_dir.mkdir(parents=True, exist_ok=True)
        self._stop_event.clear()
        self._observer = Observer()
        self._observer.schedule(_ClipEventHandler(self), str(self._recordings_dir), recursive=True)
        self._observer.start()
        self.scan_existing()
        self._thread = threading.Thread(target=self._run, name="recording-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=10)
            self._observer = None
