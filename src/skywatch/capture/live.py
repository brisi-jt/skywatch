"""Live capture source: a supervised rtl_airband against the real dongle.

Responsibilities:

- render the conf from the active frequency plan and write it into place;
- check a dongle is actually attached (by parsing ``rtl_test`` output);
- start/stop/inspect rtl_airband, either as a plain child process or via
  ``launchctl kickstart`` when launchd owns the service.

All system interactions go through injectable callables so tests (and any
box without hardware) never touch real launchctl, rtl_test, or rtl_airband.
"""

import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from sqlalchemy import Engine
from sqlmodel import select

from skywatch.capture.conf_render import render_conf
from skywatch.capture.source import SourceStatus
from skywatch.db.engine import session_scope
from skywatch.db.models import Frequency
from skywatch.settings import CaptureSettings

logger = logging.getLogger(__name__)

DEFAULT_LAUNCHD_LABEL = "com.skywatch.rtl-airband"

_RTL_TEST_FOUND_RE = re.compile(r"Found\s+(\d+)\s+device", re.IGNORECASE)


class DongleNotFoundError(RuntimeError):
    """No RTL-SDR device is attached (or rtl_test cannot see one)."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], CommandResult]


class _Process(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


Spawn = Callable[[list[str]], _Process]


def run_command(argv: list[str]) -> CommandResult:
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _spawn_process(argv: list[str]) -> _Process:
    return subprocess.Popen(argv)


class LiveSDRSource:
    """Renders the conf and supervises rtl_airband."""

    def __init__(
        self,
        engine: Engine,
        capture: CaptureSettings,
        *,
        conf_path: Path,
        recordings_dir: Path,
        supervisor: Literal["subprocess", "launchctl"] = "subprocess",
        launchd_label: str = DEFAULT_LAUNCHD_LABEL,
        launchd_domain: str = "system",
        rtl_airband_bin: str = "rtl_airband",
        rtl_test_bin: str = "rtl_test",
        runner: Runner = run_command,
        spawn: Spawn = _spawn_process,
    ) -> None:
        self._engine = engine
        self._capture = capture
        self._conf_path = Path(conf_path)
        self._recordings_dir = Path(recordings_dir)
        self._supervisor = supervisor
        self._launchd_target = f"{launchd_domain}/{launchd_label}"
        self._rtl_airband_bin = rtl_airband_bin
        self._rtl_test_bin = rtl_test_bin
        self._runner = runner
        self._spawn = spawn
        self._process: _Process | None = None

    def _active_frequencies(self) -> list[Frequency]:
        with session_scope(self._engine) as session:
            rows = session.exec(select(Frequency).where(Frequency.is_active)).all()
            session.expunge_all()
        return list(rows)

    def write_conf(self) -> str:
        """Render the conf from the active plan and write it into place."""
        text = render_conf(
            self._active_frequencies(), self._capture, recordings_dir=self._recordings_dir
        )
        self._conf_path.parent.mkdir(parents=True, exist_ok=True)
        self._conf_path.write_text(text)
        logger.info("wrote %s", self._conf_path)
        return text

    def dongle_present(self) -> bool:
        """Parse ``rtl_test -t`` output for an attached device."""
        result = self._runner([self._rtl_test_bin, "-t"])
        match = _RTL_TEST_FOUND_RE.search(result.stdout + result.stderr)
        return match is not None and int(match.group(1)) > 0

    def start(self) -> None:
        if not self.dongle_present():
            raise DongleNotFoundError(
                "no RTL-SDR dongle detected; plug it in and check `rtl_test -t`"
            )
        self.write_conf()
        self._recordings_dir.mkdir(parents=True, exist_ok=True)
        if self._supervisor == "launchctl":
            # -k restarts the service if it is already running, so a config
            # change and a cold start are the same operation.
            self._runner(["launchctl", "kickstart", "-k", self._launchd_target])
        else:
            self._process = self._spawn([self._rtl_airband_bin, "-F", "-c", str(self._conf_path)])

    def stop(self) -> None:
        if self._supervisor == "launchctl":
            self._runner(["launchctl", "kill", "SIGTERM", self._launchd_target])
            return
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("rtl_airband did not exit after SIGTERM")
        self._process = None

    def status(self) -> SourceStatus:
        if self._supervisor == "launchctl":
            result = self._runner(["launchctl", "print", self._launchd_target])
            running = bool(re.search(r"state\s*=\s*running", result.stdout))
            return SourceStatus(running=running, detail=self._launchd_target)
        running = self._process is not None and self._process.poll() is None
        return SourceStatus(running=running, detail=self._rtl_airband_bin)
