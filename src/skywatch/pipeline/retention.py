"""Retention pruning and the disk-space guard.

Routine audio is deleted after the retention window; interesting audio is
kept forever, and every database row survives pruning (the clip's history
remains browsable, just without playback). When free disk drops below the
floor, capture is paused and the pause is surfaced through the settings
table so the API can report it.
"""

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import Session, select

from skywatch.db.models import Classification, Recording, utcnow

logger = logging.getLogger(__name__)

CAPTURE_PAUSED_KEY = "capture.paused_for_disk"
"""Settings-table key the worker writes ("1"/"0") when the disk guard trips."""

_BYTES_PER_GB = 1024**3


@dataclass(frozen=True)
class DiskStatus:
    free_gb: float
    total_gb: float
    min_free_gb: float
    low: bool


def check_disk(path: Path, min_free_gb: float) -> DiskStatus:
    usage = shutil.disk_usage(path)
    free_gb = usage.free / _BYTES_PER_GB
    return DiskStatus(
        free_gb=round(free_gb, 2),
        total_gb=round(usage.total / _BYTES_PER_GB, 2),
        min_free_gb=min_free_gb,
        low=free_gb < min_free_gb,
    )


def _latest_classification(session: Session, recording_id: int) -> Classification | None:
    return session.exec(
        select(Classification)
        .where(Classification.recording_id == recording_id)
        .order_by(Classification.id.desc())  # type: ignore[union-attr]
    ).first()


def prune_routine_audio(
    session: Session,
    *,
    data_root: Path,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete audio for ROUTINE clips older than the window; keep every row.

    A clip is prunable only when its latest classification says routine —
    unclassified and interesting clips are never touched, and a later
    reclassification to interesting protects the audio even if an earlier
    verdict said routine.
    """
    now = now or utcnow()
    cutoff = now - timedelta(days=retention_days)
    candidates = session.exec(
        select(Recording).where(
            Recording.audio_deleted_at.is_(None),  # type: ignore[union-attr]
            Recording.started_at_utc < cutoff,
        )
    ).all()
    pruned = 0
    for recording in candidates:
        latest = _latest_classification(session, recording.id)
        if latest is None or latest.is_interesting:
            continue
        audio_path = Path(data_root) / recording.file_path
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not delete %s; leaving for next pass", audio_path, exc_info=True)
            continue
        recording.audio_deleted_at = now
        session.add(recording)
        pruned += 1
    if pruned:
        logger.info(
            "pruned audio for %d routine clip(s) older than %d days", pruned, retention_days
        )
    return pruned
