"""Enrichment stage: probable-aircraft lookup at capture time.

Runs on the fast path for every clip because OpenSky's historical window is
only one hour — by the time a busy day's transcription backlog drains, the
sky as it was is no longer queryable. Failures here are recorded but never
block transcription or classification.
"""

import logging
from dataclasses import dataclass

from sqlmodel import Session

from skywatch.db.models import Frequency, Recording

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EnrichOutcome:
    matches: int
    skipped_reason: str | None = None


def run_enrich(
    session: Session,
    recording: Recording,
    *,
    enricher,
    frequency: Frequency,
) -> EnrichOutcome:
    """Enrich one recording; propagates provider errors for the retry path."""
    if enricher is None:
        return EnrichOutcome(matches=0, skipped_reason="enrichment disabled")
    matches = enricher.enrich(session, recording, frequency.category)
    if not matches:
        logger.info("no aircraft candidates for recording %s", recording.id)
    return EnrichOutcome(matches=len(matches))
