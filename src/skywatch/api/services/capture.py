"""Capture control for the API process.

The API restarts capture after frequency-plan changes. In live mode that
means supervising rtl_airband through a ``LiveSDRSource`` (stop, rewrite the
config file from the database plan, start). In replay mode the worker
process owns the fixture player, so there is nothing for the API to restart
and the controller is a no-op.
"""

import logging
from pathlib import Path

from sqlalchemy import Engine

from skywatch.capture.source import CaptureSource, SourceStatus
from skywatch.settings import Settings

logger = logging.getLogger(__name__)


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
        data_root = settings.data_root
        self.conf_path = Path(conf_path) if conf_path else data_root / "rtl_airband.conf"
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
            )
        self.source = source

    def restart(self, *, has_active: bool) -> tuple[bool, str | None]:
        """Bounce capture onto the current plan.

        Returns (restarted, warning). With no active frequencies the source
        is stopped and left stopped; a failed restart is reported as a
        warning rather than an error, because the plan change itself has
        already been committed and the status trace will show the mismatch.
        """
        if self.source is None:
            return False, None
        try:
            self.source.stop()
            if not has_active:
                return False, "capture stopped: no active frequencies to record"
            self.source.start()
        except Exception as exc:
            logger.warning("capture restart failed: %s", exc)
            return False, f"capture restart failed: {exc}"
        return True, None

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
