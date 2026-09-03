"""The daily narrative: a few warm sentences describing a day on the air.

One narrative per station-local day, generated through the same classifier
provider chain the pipeline already uses, metered against the same daily
budget, and cached in the settings table so it costs one or two model calls a
day at most. The worker's maintenance pass writes today's narrative once; the
dashboard's "summarise today so far" button regenerates it on demand.

This module lives in the pipeline layer deliberately: it depends only on the
database, the provider chain, and the budget accounting, never on the API, so
both the worker and the API can drive it.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from skywatch.db.models import Classification, Frequency, Recording, Setting, Transcript
from skywatch.pipeline import budget
from skywatch.providers.llm.base import Classifier, ClassifierError
from skywatch.providers.llm.prompt import NARRATIVE_SYSTEM_PROMPT, build_narrative_prompt

logger = logging.getLogger(__name__)

NARRATIVE_KEY_PREFIX = "narrative:"
"""Settings-table key prefix; one row per ``narrative:<YYYY-MM-DD>``."""

MAX_MOMENTS = 12
"""How many of the day's interesting clips are described to the model."""

SNIPPET_LENGTH = 120


@dataclass(frozen=True)
class Narrative:
    """A cached daily narrative and when it was written."""

    text: str
    generated_at: datetime
    rolling: bool


def narrative_key(day: date) -> str:
    return f"{NARRATIVE_KEY_PREFIX}{day.isoformat()}"


def cached_narrative(session: Session, day: date) -> Narrative | None:
    """The stored narrative for a day, or None when none has been written."""
    row = session.get(Setting, narrative_key(day))
    if row is None:
        return None
    try:
        payload = json.loads(row.value)
        return Narrative(
            text=str(payload["text"]),
            generated_at=datetime.fromisoformat(payload["generated_at"]),
            rolling=bool(payload.get("rolling", False)),
        )
    except (ValueError, KeyError, TypeError):
        logger.warning("discarding unparseable narrative cache for %s", day)
        return None


def _store(session: Session, day: date, narrative: Narrative) -> None:
    payload = json.dumps(
        {
            "text": narrative.text,
            "generated_at": narrative.generated_at.astimezone(UTC).isoformat(),
            "rolling": narrative.rolling,
        }
    )
    row = session.get(Setting, narrative_key(day))
    if row is None:
        session.add(Setting(key=narrative_key(day), value=payload))
    else:
        row.value = payload
        session.add(row)


def _day_bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


@dataclass(frozen=True)
class NarrativeInput:
    """The day's shape as handed to the model."""

    day: date
    total_count: int
    interesting_count: int
    moments: list[str]


def build_narrative_input(session: Session, *, day: date, tz: ZoneInfo) -> NarrativeInput | None:
    """Summarise a day into model input, or None when nothing was recorded."""
    start, end = _day_bounds(day, tz)
    recordings = list(
        session.exec(
            select(Recording)
            .where(Recording.started_at_utc >= start, Recording.started_at_utc < end)
            .order_by(Recording.started_at_utc)  # type: ignore[arg-type]
        ).all()
    )
    if not recordings:
        return None
    ids = [rec.id for rec in recordings]
    latest: dict[int, Classification] = {}
    for row in session.exec(
        select(Classification)
        .where(Classification.recording_id.in_(ids))  # type: ignore[attr-defined]
        .order_by(Classification.id)  # type: ignore[arg-type]
    ).all():
        latest[row.recording_id] = row
    freq_labels = {
        f.id: f.label
        for f in session.exec(
            select(Frequency).where(
                Frequency.id.in_({rec.freq_id for rec in recordings})  # type: ignore[attr-defined]
            )
        ).all()
    }
    interesting = [
        rec for rec in recordings if (v := latest.get(rec.id)) is not None and v.is_interesting
    ]
    moments: list[str] = []
    for rec in interesting[:MAX_MOMENTS]:
        verdict = latest[rec.id]
        local_time = rec.started_at_utc.astimezone(tz).strftime("%H:%M")
        snippet = _transcript_snippet(session, rec.id)
        label = freq_labels.get(rec.freq_id, "an unknown frequency")
        moment = f"{local_time} on {label} [{verdict.category.value}]: {verdict.reason}"
        if snippet:
            moment += f' — "{snippet}"'
        moments.append(moment)
    return NarrativeInput(
        day=day,
        total_count=len(recordings),
        interesting_count=len(interesting),
        moments=moments,
    )


def _transcript_snippet(session: Session, recording_id: int) -> str | None:
    text = session.exec(
        select(Transcript.text)
        .where(Transcript.recording_id == recording_id)
        .order_by(Transcript.id.desc())  # type: ignore[union-attr]
    ).first()
    return text[:SNIPPET_LENGTH].strip() if text else None


def _meter_call(session: Session, provider, day: date) -> None:
    """Meter one real model call in its own committed transaction.

    A separate session on the same engine, mirroring the classifier stage: the
    HTTP call is spent whether or not the caller's transaction later commits, so
    the budget must record it independently.
    """
    with Session(session.get_bind()) as budget_session:
        budget.record_call(budget_session, provider, day)
        budget_session.commit()


def _run_chain(
    session: Session,
    chain: list[Classifier],
    daily_call_cap: int,
    system_prompt: str,
    user_prompt: str,
    *,
    day: date,
) -> str | None:
    """Try each provider in turn; return the first narrative, budget permitting."""
    for classifier in chain:
        narrate = getattr(classifier, "narrate", None)
        if narrate is None:
            continue
        if budget.remaining(session, classifier.provider, day, daily_call_cap) <= 0:
            continue
        _meter_call(session, classifier.provider, day)
        try:
            text = narrate(NARRATIVE_SYSTEM_PROMPT, user_prompt)
        except ClassifierError as exc:
            logger.warning("narrative provider %s failed: %s", classifier.provider, exc)
            continue
        cleaned = text.strip()
        if cleaned:
            return cleaned
    return None


def generate_narrative(
    session: Session,
    *,
    day: date,
    tz: ZoneInfo,
    chain: list[Classifier],
    daily_call_cap: int,
    rolling: bool = False,
    now: datetime | None = None,
) -> Narrative | None:
    """Generate and cache a day's narrative, or None when it cannot be written.

    Returns None when the day had no recordings, the chain is empty, or every
    provider's budget is exhausted (or all fail). Callers commit the session.
    """
    if not chain:
        return None
    inp = build_narrative_input(session, day=day, tz=tz)
    if inp is None:
        return None
    now = now or datetime.now(UTC)
    user_prompt = build_narrative_prompt(
        day_label=day.strftime("%A %-d %B %Y"),
        total_count=inp.total_count,
        interesting_count=inp.interesting_count,
        moments=inp.moments,
    )
    text = _run_chain(
        session, chain, daily_call_cap, NARRATIVE_SYSTEM_PROMPT, user_prompt, day=now.date()
    )
    if text is None:
        return None
    narrative = Narrative(text=text, generated_at=now, rolling=rolling)
    _store(session, day, narrative)
    return narrative
