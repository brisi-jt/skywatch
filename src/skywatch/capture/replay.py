"""Development capture source: replays fixture clips into the watched dir.

Files land exactly the way rtl_airband would deliver them — dated
subdirectories, filename-encoded UTC start time and frequency — but slightly
backdated, so downstream stages (including time-sensitive flight lookups)
see plausible clips without any hardware attached.
"""

import itertools
import shutil
import threading
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from skywatch.capture.filenames import dated_subdir, format_recording_filename
from skywatch.capture.source import SourceStatus
from skywatch.db.models import utcnow


class ReplaySource:
    """Streams fixture MP3s into the recordings directory.

    ``run_once`` drops every fixture synchronously; ``start`` does the same
    from a background thread at ``pacing_s`` intervals, cycling forever when
    ``loop`` is set.
    """

    def __init__(
        self,
        fixtures: Sequence[Path],
        output_dir: Path,
        *,
        freqs_hz: Sequence[int],
        pacing_s: float = 0.5,
        template: str = "replay",
        dated_subdirs: bool = True,
        backdate_s: float = 5.0,
        loop: bool = False,
        clock=utcnow,
    ) -> None:
        if not fixtures:
            raise ValueError("ReplaySource needs at least one fixture clip")
        if not freqs_hz:
            raise ValueError("ReplaySource needs at least one frequency")
        self._fixtures = [Path(f) for f in fixtures]
        self._output_dir = Path(output_dir)
        self._freqs_hz = list(freqs_hz)
        self._pacing_s = pacing_s
        self._template = template
        self._dated_subdirs = dated_subdirs
        self._backdate_s = backdate_s
        self._loop = loop
        self._clock = clock
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._drop_count = 0

    def _drop(self, fixture: Path, freq_hz: int) -> Path:
        started: datetime = (self._clock() - timedelta(seconds=self._backdate_s)).replace(
            microsecond=0
        )
        while True:
            name = format_recording_filename(self._template, started, freq_hz)
            directory = self._output_dir
            if self._dated_subdirs:
                directory = directory / dated_subdir(started)
            dest = directory / name
            if not dest.exists():
                break
            started += timedelta(seconds=1)  # rtl_airband names are second-granular
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fixture, dest)
        self._drop_count += 1
        return dest

    def run_once(self) -> list[Path]:
        """Drop every fixture once, pacing between drops; returns the paths."""
        dropped: list[Path] = []
        freqs = itertools.cycle(self._freqs_hz)
        for index, fixture in enumerate(self._fixtures):
            if self._stop_event.is_set():
                break
            if index and self._pacing_s and self._stop_event.wait(self._pacing_s):
                break
            dropped.append(self._drop(fixture, next(freqs)))
        return dropped

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            if not self._loop:
                break
            if self._stop_event.wait(self._pacing_s or 0.1):
                break

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="replay-source", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None

    def status(self) -> SourceStatus:
        running = self._thread is not None and self._thread.is_alive()
        return SourceStatus(running=running, detail=f"{self._drop_count} clips dropped")
