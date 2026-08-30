"""Capture control for the API process.

The API restarts capture after frequency-plan changes. In live mode that
means supervising rtl_airband through a ``LiveSDRSource`` (stop, rewrite the
config file from the database plan, start). In replay mode the worker
process owns the fixture player, so there is nothing for the API to restart
and the controller is a no-op.
"""

import logging
import os
import threading
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session

from skywatch.capture.source import CaptureSource, SourceStatus
from skywatch.capture.stats import default_stats_path
from skywatch.db.models import Setting
from skywatch.pipeline.retention import CAPTURE_PAUSED_KEY
from skywatch.settings import Settings

logger = logging.getLogger(__name__)


def capture_paused_for_disk(session: Session) -> bool:
    """Whether the worker's disk-space guard currently has capture paused."""
    row = session.get(Setting, CAPTURE_PAUSED_KEY)
    return row is not None and row.value == "1"


def reject_if_capture_paused(session: Session) -> None:
    """Refuse plan or tuning changes while capture is paused for low disk.

    Those actions restart capture, and only the worker may lift a low-disk
    pause, so they are blocked with a 409 until free space recovers.
    """
    from skywatch.api.errors import APIErrorCode, ProblemException

    if capture_paused_for_disk(session):
        raise ProblemException(
            409,
            APIErrorCode.CAPTURE_PAUSED_LOW_DISK,
            "capture is paused because free disk is below the floor; the station "
            "resumes on its own once space is freed, and frequency and tuning "
            "changes are blocked until then",
        )


class CaptureController:
    def __init__(
        self,
        *,
        engine: Engine,
        settings: Settings,
        source: CaptureSource | None = None,
        conf_path: Path | None = None,
    ) -> None:
        self._settings = settings
        self._engine = engine
        self.restart_lock = threading.RLock()
        """Serialises plan/tuning changes and their capture restart so two
        concurrent requests cannot interleave read-modify-write-restart."""
        data_root = settings.data_root
        self.conf_path = Path(conf_path) if conf_path else data_root / "rtl_airband.conf"
        self.stats_filepath = default_stats_path(data_root)
        if source is None and settings.capture.source == "live":
            from skywatch.capture.live import LiveSDRSource

            recordings_dir = settings.capture.output_dir
            if not recordings_dir.is_absolute():
                recordings_dir = recordings_dir.resolve()
            source = LiveSDRSource(
                engine,
                settings.capture,
                conf_path=self.conf_path,
                recordings_dir=recordings_dir,
                stats_filepath=self.stats_filepath,
                supervisor=settings.capture.supervisor,
                launchd_domain=f"gui/{os.getuid()}",
            )
        self.source = source

    def restart(self, *, has_active: bool) -> tuple[bool, str | None]:
        """Bounce capture onto the current plan.

        Returns (restarted, warning). With no active frequencies the source
        is stopped and left stopped; a failed restart is reported as a
        warning rather than an error, because the plan change itself has
        already been committed and the status trace will show the mismatch.

        While the worker's disk-space guard has capture paused the source is
        stopped but never started again: the worker is the only process that
        clears the pause and brings the station back on air. This keeps every
        restart path — plan changes, tuning apply, deep tune exit — from
        overriding a low-disk pause.
        """
        if self.source is None:
            return False, None
        with self.restart_lock:
            try:
                self.source.stop()
                if not has_active:
                    return False, "capture stopped: no active frequencies to record"
                if self._paused_for_disk():
                    return False, (
                        "capture remains paused: free disk is below the floor; "
                        "the station resumes on its own once space is freed"
                    )
                self.source.start()
            except Exception as exc:
                logger.warning("capture restart failed: %s", exc)
                return False, f"capture restart failed: {exc}"
        return True, None

    def _paused_for_disk(self) -> bool:
        with Session(self._engine) as session:
            return capture_paused_for_disk(session)

    def stop(self) -> None:
        """Stop capture and leave it stopped.

        Deep tune borrows the receiver this way; the session's exit path
        calls :meth:`restart` to put the station back on air.
        """
        if self.source is not None:
            self.source.stop()

    def status(self) -> SourceStatus | None:
        if self.source is None:
            return None
        try:
            return self.source.status()
        except Exception as exc:
            logger.warning("capture status probe failed: %s", exc)
            return SourceStatus(running=False, detail="capture status unavailable")

    def dongle_present(self) -> bool | None:
        """Whether an RTL-SDR device is attached; None when there is nothing
        to probe (replay mode)."""
        probe = getattr(self.source, "dongle_present", None)
        if probe is None:
            return None
        try:
            return bool(probe())
        except Exception as exc:
            logger.warning("dongle probe failed: %s", exc)
            return False
