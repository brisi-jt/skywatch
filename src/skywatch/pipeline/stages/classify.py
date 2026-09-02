"""Classification stage: prefilters first, then a budgeted LLM chain.

Rules of the stage:

- Prefilters always run; the LLM can only upgrade their verdict to
  interesting, never downgrade a flagged clip back to routine.
- Clips under the duration floor or with empty transcripts never reach an
  LLM — they are classified by prefilters alone.
- Every LLM call is metered per provider per day. When quota blocks the
  whole chain, the prefilter verdict is stored as ``deferred`` and a later
  backfill pass upgrades it once budget returns.
- LLM confidence is downweighted when the recogniser reported a weak
  transcript, since the verdict is only as good as the words it judged.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlmodel import Session, select

from skywatch.db.enums import (
    ClassificationCategory,
    ClassificationSource,
    ClassificationStatus,
)
from skywatch.db.models import AircraftMatch, Classification, Frequency, Recording, Transcript
from skywatch.pipeline import budget
from skywatch.pipeline.prefilters import PrefilterVerdict, run_prefilters
from skywatch.providers.llm.base import (
    Classifier,
    ClassifierError,
    ClassifyRequest,
    LLMVerdict,
)

logger = logging.getLogger(__name__)

MIN_LLM_CLIP_SECONDS = 1.5
"""Clips shorter than this carry too little speech to be worth an LLM call."""

_GOOD_LOGPROB = -0.3
_POOR_LOGPROB = -1.5
_MIN_SCALE = 0.5


class ClassifyFailed(RuntimeError):
    """Every provider errored; the stage should be retried later."""


def best_aircraft_alert(session: Session, recording_id: int) -> tuple[str, int] | None:
    """The best-ranked probable aircraft flagged interesting, or None.

    Returns ``(category, rank)`` for the highest-ranked candidate carrying a
    plane-alert category, so the prefilter can flag the clip accordingly.
    """
    row = session.exec(
        select(AircraftMatch.alert_category, AircraftMatch.rank)
        .where(
            AircraftMatch.recording_id == recording_id,
            AircraftMatch.alert_category.is_not(None),  # type: ignore[union-attr]
        )
        .order_by(AircraftMatch.rank)  # type: ignore[arg-type]
    ).first()
    if row is None:
        return None
    category, rank = row
    return category, rank


def _commit_budget_call(session: Session, provider, day: date) -> None:
    """Meter one real API call in its own committed transaction.

    Uses a separate session on the same engine so the increment survives even
    when the caller's classification transaction is later rolled back (e.g. the
    whole provider chain fails and the stage is retried).
    """
    with Session(session.get_bind()) as budget_session:
        budget.record_call(budget_session, provider, day)
        budget_session.commit()


@dataclass(frozen=True)
class EvalVerdict:
    """A combined verdict outside the database, for the eval runner."""

    is_interesting: bool
    category: ClassificationCategory
    confidence: float
    reason: str
    source: ClassificationSource


def downweight_confidence(confidence: float, avg_logprob: float | None) -> float:
    """Scale an LLM confidence by transcription quality.

    Full confidence at healthy segment log-probabilities, linearly down to
    half confidence for badly garbled audio; unknown quality is untouched.
    """
    if avg_logprob is None:
        return confidence
    if avg_logprob >= _GOOD_LOGPROB:
        return confidence
    span = _GOOD_LOGPROB - _POOR_LOGPROB
    scale = 1.0 - (1.0 - _MIN_SCALE) * min(1.0, (_GOOD_LOGPROB - avg_logprob) / span)
    return confidence * scale


def _combine(
    prefilter: PrefilterVerdict, verdict: LLMVerdict, avg_logprob: float | None
) -> tuple[bool, ClassificationCategory, float, str]:
    """Merge the two layers; the prefilter verdict is only ever upgraded."""
    llm_confidence = downweight_confidence(verdict.confidence, avg_logprob)
    if prefilter.is_interesting and not verdict.is_interesting:
        reason = f"{prefilter.reason} (model judged it routine: {verdict.reason})"
        return True, prefilter.category, prefilter.confidence, reason
    return verdict.is_interesting, verdict.category, llm_confidence, verdict.reason


def _store(
    session: Session,
    recording: Recording,
    prefilter: PrefilterVerdict,
    *,
    is_interesting: bool,
    category: ClassificationCategory,
    confidence: float,
    reason: str,
    source: ClassificationSource,
    model: str | None,
    status: ClassificationStatus,
) -> Classification:
    row = Classification(
        recording_id=recording.id,
        is_interesting=is_interesting,
        category=category,
        confidence=round(confidence, 4),
        reason=reason,
        source=source,
        model=model,
        prefilter_flags=list(prefilter.flags),
        status=status,
    )
    session.add(row)
    return row


def run_classify(
    session: Session,
    recording: Recording,
    transcript: Transcript | None,
    *,
    frequency: Frequency,
    chain: list[Classifier],
    daily_call_cap: int,
    recent_durations: tuple[float, ...] | list[float] = (),
    watch_phrases: tuple[str, ...] | list[str] = (),
    day: date | None = None,
    backfill: bool = False,
) -> Classification | None:
    """Classify one recording, appending a ``classifications`` row.

    With ``backfill=True`` a row is appended only if an LLM verdict is
    actually obtained — used to upgrade earlier ``deferred`` verdicts
    without duplicating them.
    """
    day = day or datetime.now(UTC).date()
    text = (transcript.text if transcript is not None else "").strip()
    avg_logprob = transcript.avg_logprob if transcript is not None else None
    prefilter = run_prefilters(
        transcript_text=text or None,
        duration_s=recording.duration_s,
        freq_category=frequency.category,
        recent_durations=recent_durations,
        watch_phrases=watch_phrases,
        aircraft_alert=best_aircraft_alert(session, recording.id),
    )

    skip_reason = None
    if recording.duration_s < MIN_LLM_CLIP_SECONDS:
        skip_reason = f"clip under {MIN_LLM_CLIP_SECONDS:g}s"
    elif not text:
        skip_reason = "empty transcript"
    if skip_reason is not None:
        if backfill:
            return None
        return _store(
            session,
            recording,
            prefilter,
            is_interesting=prefilter.is_interesting,
            category=prefilter.category,
            confidence=prefilter.confidence,
            reason=f"{prefilter.reason} (llm skipped: {skip_reason})",
            source=ClassificationSource.PREFILTER,
            model=None,
            status=ClassificationStatus.FINAL,
        )

    request = ClassifyRequest(
        transcript=text,
        duration_s=recording.duration_s,
        frequency_label=frequency.label,
        frequency_category=frequency.category,
        prefilter_flags=list(prefilter.flags),
        asr_avg_logprob=avg_logprob,
    )

    verdict: LLMVerdict | None = None
    quota_hit = False
    errors: list[str] = []
    for classifier in chain:
        if budget.remaining(session, classifier.provider, day, daily_call_cap) <= 0:
            quota_hit = True
            continue
        # Commit the call against the budget in its own transaction BEFORE the
        # network request. A real HTTP call was spent, so it must be metered
        # even if the whole chain then fails and this stage's classification
        # transaction is rolled back — otherwise the spend is invisible and the
        # daily cap can be blown by repeated retries.
        _commit_budget_call(session, classifier.provider, day)
        try:
            verdict = classifier.classify(request)
            break
        except ClassifierError as exc:
            logger.warning("classifier %s failed: %s", classifier.provider, exc)
            errors.append(f"{classifier.provider.value}: {exc}")

    if verdict is not None:
        is_interesting, category, confidence, reason = _combine(prefilter, verdict, avg_logprob)
        return _store(
            session,
            recording,
            prefilter,
            is_interesting=is_interesting,
            category=category,
            confidence=confidence,
            reason=reason,
            source=ClassificationSource.LLM,
            model=verdict.model,
            status=ClassificationStatus.FINAL,
        )

    if backfill:
        return None

    if quota_hit:
        return _store(
            session,
            recording,
            prefilter,
            is_interesting=prefilter.is_interesting,
            category=prefilter.category,
            confidence=prefilter.confidence,
            reason=f"{prefilter.reason} (llm deferred: daily call cap reached)",
            source=ClassificationSource.PREFILTER,
            model=None,
            status=ClassificationStatus.DEFERRED,
        )

    if errors:
        raise ClassifyFailed("; ".join(errors))

    return _store(
        session,
        recording,
        prefilter,
        is_interesting=prefilter.is_interesting,
        category=prefilter.category,
        confidence=prefilter.confidence,
        reason=prefilter.reason,
        source=ClassificationSource.PREFILTER,
        model=None,
        status=ClassificationStatus.FINAL,
    )


def evaluate_clip(
    *,
    transcript_text: str,
    duration_s: float,
    frequency_label: str,
    freq_category,
    prefilter: PrefilterVerdict,
    chain: list[Classifier],
    asr_avg_logprob: float | None,
) -> EvalVerdict:
    """Database-free classification for the eval runner (no budget metering)."""
    text = transcript_text.strip()
    if duration_s < MIN_LLM_CLIP_SECONDS or not text or not chain:
        return EvalVerdict(
            is_interesting=prefilter.is_interesting,
            category=prefilter.category,
            confidence=prefilter.confidence,
            reason=prefilter.reason,
            source=ClassificationSource.PREFILTER,
        )
    request = ClassifyRequest(
        transcript=text,
        duration_s=duration_s,
        frequency_label=frequency_label,
        frequency_category=freq_category,
        prefilter_flags=list(prefilter.flags),
        asr_avg_logprob=asr_avg_logprob,
    )
    for classifier in chain:
        try:
            verdict = classifier.classify(request)
        except ClassifierError:
            continue
        is_interesting, category, confidence, reason = _combine(prefilter, verdict, asr_avg_logprob)
        return EvalVerdict(
            is_interesting=is_interesting,
            category=category,
            confidence=confidence,
            reason=reason,
            source=ClassificationSource.LLM,
        )
    return EvalVerdict(
        is_interesting=prefilter.is_interesting,
        category=prefilter.category,
        confidence=prefilter.confidence,
        reason=prefilter.reason,
        source=ClassificationSource.PREFILTER,
    )
