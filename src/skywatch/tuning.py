"""Database-owned tuning values: gain, squelch, and frequency correction.

The ``settings`` KV table owns these levers. ``config/config.yaml`` supplies
their first values (seeded once on startup) and keeps the topology — mode,
device, sample rate — but later yaml edits do not change tuning; the
dashboard's tuning page is the editor. This module is the single
reader/writer for both the API and the worker, so every conf render sees the
same numbers.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from skywatch.capture.conf_render import render_conf
from skywatch.db.models import Frequency, Setting
from skywatch.settings import CaptureSettings

logger = logging.getLogger(__name__)

GAIN_KEY = "tuning.gain"
SQUELCH_DEFAULT_KEY = "tuning.squelch_default"
PPM_KEY = "tuning.ppm"
SQUELCH_OVERRIDE_PREFIX = "tuning.squelch."
BASELINE_PREFIX = "tuning.baseline."
LAST_APPLIED_AT_KEY = "tuning.last_applied_at"

FACTORY_GAIN_DB = 32.0
FACTORY_SQUELCH_SNR_DB = 12.0
FACTORY_PPM = 0

# The R820T tuner's real gain ladder (librtlsdr tuner_r82xx, in dB). The
# hardware can only sit on these values — rtl_airband rounds anything else
# to the nearest step — so controls should offer exactly this set.
R820T_GAIN_STEPS_DB = (
    0.0,
    0.9,
    1.4,
    2.7,
    3.7,
    7.7,
    8.7,
    12.5,
    14.4,
    15.7,
    16.6,
    19.7,
    20.7,
    22.9,
    25.4,
    28.0,
    29.7,
    32.8,
    33.8,
    36.4,
    37.2,
    38.6,
    40.2,
    42.1,
    43.4,
    43.9,
    44.5,
    48.0,
    49.6,
)


def snap_gain_db(value: float) -> float:
    """The nearest real tuner gain step to ``value``."""
    return min(R820T_GAIN_STEPS_DB, key=lambda step: abs(step - value))


def _fmt(value: float) -> str:
    """Store numbers without a trailing ``.0`` so round trips stay tidy."""
    return f"{value:g}"


@dataclass(frozen=True)
class TuningValues:
    """One complete set of tuning levers."""

    gain_db: float
    squelch_default_snr_db: float
    ppm: int
    squelch_overrides: dict[int, float] = field(default_factory=dict)
    """Per-frequency squelch SNR thresholds, keyed by ``frequencies.id``."""


class TuningService:
    """Reads and writes the tuning rows in the ``settings`` table.

    Constructed over the station's :class:`CaptureSettings`, which provide
    the fallback values for rows that do not exist yet (a station that has
    never been seeded behaves exactly as its config file says).
    """

    def __init__(self, capture: CaptureSettings) -> None:
        self._capture = capture

    # -- seeding -----------------------------------------------------------------

    def ensure_seeded(self, session: Session) -> bool:
        """Copy the config-file tunables into the database, once.

        Only missing rows are written, so running this on every startup is
        safe and later config-file edits never overwrite what the dashboard
        has applied. Returns True when anything was written.
        """
        seeds = {
            GAIN_KEY: _fmt(self._capture.gain),
            SQUELCH_DEFAULT_KEY: _fmt(self._capture.squelch_snr_threshold),
            PPM_KEY: str(self._capture.ppm),
        }
        wrote = False
        for key, value in seeds.items():
            if session.get(Setting, key) is None:
                session.add(Setting(key=key, value=value))
                wrote = True
        if wrote:
            session.commit()
        return wrote

    # -- reads -------------------------------------------------------------------

    def current(self, session: Session) -> TuningValues:
        """The applied values: database rows, config-file values for any gap."""
        return TuningValues(
            gain_db=self._float(session, GAIN_KEY, self._capture.gain),
            squelch_default_snr_db=self._float(
                session, SQUELCH_DEFAULT_KEY, self._capture.squelch_snr_threshold
            ),
            ppm=self._int(session, PPM_KEY, self._capture.ppm),
            squelch_overrides=self._overrides(session, SQUELCH_OVERRIDE_PREFIX),
        )

    def baseline(self, session: Session) -> TuningValues | None:
        """The saved baseline, or None when none has been saved yet."""
        gain = self._value(session, BASELINE_PREFIX + "gain")
        if gain is None:
            return None
        return TuningValues(
            gain_db=self._float(session, BASELINE_PREFIX + "gain", FACTORY_GAIN_DB),
            squelch_default_snr_db=self._float(
                session, BASELINE_PREFIX + "squelch_default", FACTORY_SQUELCH_SNR_DB
            ),
            ppm=self._int(session, BASELINE_PREFIX + "ppm", FACTORY_PPM),
            squelch_overrides=self._overrides(session, BASELINE_PREFIX + "squelch."),
        )

    def last_applied_at(self, session: Session) -> datetime | None:
        raw = self._value(session, LAST_APPLIED_AT_KEY)
        if raw is None:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning(
                "unreadable %s value %r; treating as never applied", LAST_APPLIED_AT_KEY, raw
            )
            return None

    def effective_capture(self, session: Session) -> CaptureSettings:
        """Capture settings with the database-owned levers merged in."""
        values = self.current(session)
        return self._capture.model_copy(
            update={
                "gain": values.gain_db,
                "squelch_snr_threshold": values.squelch_default_snr_db,
                "ppm": values.ppm,
            }
        )

    def render(
        self,
        session: Session,
        frequencies: list[Frequency],
        *,
        recordings_dir: Path,
        stats_filepath: Path | None,
    ) -> str:
        """Render the rtl_airband conf for ``frequencies`` with applied tuning."""
        return render_conf(
            frequencies,
            self.effective_capture(session),
            recordings_dir=recordings_dir,
            squelch_overrides=self.current(session).squelch_overrides,
            stats_filepath=stats_filepath,
        )

    # -- writes ------------------------------------------------------------------

    def store(self, session: Session, values: TuningValues, *, applied_at: datetime) -> None:
        """Persist a complete set of applied values.

        Override rows absent from ``values`` are deleted, so the database
        always mirrors exactly what was applied.
        """
        self._upsert(session, GAIN_KEY, _fmt(values.gain_db))
        self._upsert(session, SQUELCH_DEFAULT_KEY, _fmt(values.squelch_default_snr_db))
        self._upsert(session, PPM_KEY, str(values.ppm))
        self._replace_overrides(session, SQUELCH_OVERRIDE_PREFIX, values.squelch_overrides)
        self._upsert(session, LAST_APPLIED_AT_KEY, applied_at.isoformat())
        session.commit()

    def save_baseline(self, session: Session, values: TuningValues) -> None:
        """Snapshot ``values`` as the baseline, replacing any previous one."""
        self._upsert(session, BASELINE_PREFIX + "gain", _fmt(values.gain_db))
        self._upsert(
            session, BASELINE_PREFIX + "squelch_default", _fmt(values.squelch_default_snr_db)
        )
        self._upsert(session, BASELINE_PREFIX + "ppm", str(values.ppm))
        self._replace_overrides(session, BASELINE_PREFIX + "squelch.", values.squelch_overrides)
        session.commit()

    # -- row helpers ---------------------------------------------------------------

    @staticmethod
    def _value(session: Session, key: str) -> str | None:
        row = session.get(Setting, key)
        return row.value if row is not None else None

    def _float(self, session: Session, key: str, fallback: float) -> float:
        raw = self._value(session, key)
        if raw is None:
            return float(fallback)
        try:
            return float(raw)
        except ValueError:
            logger.warning("unreadable %s value %r; using %s", key, raw, fallback)
            return float(fallback)

    def _int(self, session: Session, key: str, fallback: int) -> int:
        return int(round(self._float(session, key, fallback)))

    @staticmethod
    def _overrides(session: Session, prefix: str) -> dict[int, float]:
        rows = session.exec(
            select(Setting).where(Setting.key.startswith(prefix))  # type: ignore[attr-defined]
        ).all()
        overrides: dict[int, float] = {}
        for row in rows:
            suffix = row.key.removeprefix(prefix)
            try:
                overrides[int(suffix)] = float(row.value)
            except ValueError:
                logger.warning("skipping unreadable tuning row %s=%r", row.key, row.value)
        return overrides

    @staticmethod
    def _upsert(session: Session, key: str, value: str) -> None:
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
            session.add(row)

    def _replace_overrides(
        self, session: Session, prefix: str, overrides: dict[int, float]
    ) -> None:
        existing = session.exec(
            select(Setting).where(Setting.key.startswith(prefix))  # type: ignore[attr-defined]
        ).all()
        wanted = {f"{prefix}{freq_id}": _fmt(value) for freq_id, value in overrides.items()}
        for row in existing:
            if row.key not in wanted:
                session.delete(row)
        for key, value in wanted.items():
            self._upsert(session, key, value)
