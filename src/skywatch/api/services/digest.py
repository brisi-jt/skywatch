"""Builds the daily digest: one station-local day, summarised.

Day boundaries follow the station's configured timezone, so "Tuesday"
means Tuesday as the listener experiences it, not UTC Tuesday.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import Session, select
from starlette import status

from skywatch.api.errors import APIErrorCode, ProblemException
from skywatch.api.schemas import DigestNarrative, DigestResponse, Link
from skywatch.api.services.recordings import build_summaries, day_start_utc
from skywatch.db.enums import FeedbackVerdict
from skywatch.db.models import Classification, Feedback, Recording
from skywatch.pipeline import narrative as narrative_cache
from skywatch.providers.llm.base import Classifier

GREATEST_HITS_LIMIT = 8

MIN_SUMMARY_INTERVAL_S = 600
"""Ten minutes between on-demand narrative regenerations, server-enforced."""


def _narrative_resource(session: Session, day: date) -> DigestNarrative | None:
    cached = narrative_cache.cached_narrative(session, day)
    if cached is None:
        return None
    return DigestNarrative(
        text=cached.text, generated_at=cached.generated_at, rolling=cached.rolling
    )


def _latest_classifications(session: Session, ids: list[int]) -> dict[int, Classification]:
    if not ids:
        return {}
    latest: dict[int, Classification] = {}
    rows = session.exec(
        select(Classification)
        .where(Classification.recording_id.in_(ids))  # type: ignore[attr-defined]
        .order_by(Classification.id)  # type: ignore[arg-type]
    ).all()
    for row in rows:
        latest[row.recording_id] = row
    return latest


def _greatest_hits(session: Session) -> list[Recording]:
    """All-time favourites, ranked by thumbs-up count."""
    rows = session.exec(
        select(Feedback.recording_id, func.count().label("ups"))
        .where(Feedback.verdict == FeedbackVerdict.UP)
        .group_by(Feedback.recording_id)
        .order_by(func.count().desc(), Feedback.recording_id.desc())  # type: ignore[union-attr]
        .limit(GREATEST_HITS_LIMIT)
    ).all()
    ids = [rec_id for rec_id, _ in rows]
    if not ids:
        return []
    recordings = {
        rec.id: rec
        for rec in session.exec(
            select(Recording).where(Recording.id.in_(ids))  # type: ignore[attr-defined]
        ).all()
    }
    return [recordings[rec_id] for rec_id in ids if rec_id in recordings]


def build_digest(
    session: Session, *, day: date, tz: ZoneInfo, today: date | None = None
) -> DigestResponse:
    start = day_start_utc(day, tz)
    end = day_start_utc(day + timedelta(days=1), tz)
    days_rows = list(
        session.exec(
            select(Recording)
            .where(Recording.started_at_utc >= start, Recording.started_at_utc < end)
            .order_by(
                Recording.started_at_utc.desc(),  # type: ignore[attr-defined]
                Recording.id.desc(),  # type: ignore[union-attr]
            )
        ).all()
    )
    latest = _latest_classifications(session, [rec.id for rec in days_rows])
    interesting = [
        rec
        for rec in days_rows
        if (verdict := latest.get(rec.id)) is not None and verdict.is_interesting
    ]

    today = today or datetime.now(tz).date()
    links = {
        "self": Link(href=f"/digest?date={day.isoformat()}"),
        "previous_day": Link(href=f"/digest?date={(day - timedelta(days=1)).isoformat()}"),
    }
    if day < today:
        links["next_day"] = Link(href=f"/digest?date={(day + timedelta(days=1)).isoformat()}")

    return DigestResponse(
        date=day,
        total_count=len(days_rows),
        interesting_count=len(interesting),
        narrative=_narrative_resource(session, day),
        interesting=build_summaries(session, interesting),
        greatest_hits=build_summaries(session, _greatest_hits(session)),
        links=links,
    )


def regenerate_today_summary(
    session: Session,
    *,
    tz: ZoneInfo,
    chain: list[Classifier],
    daily_call_cap: int,
    now: datetime | None = None,
) -> DigestResponse:
    """Rewrite today's narrative on demand, then return today's digest.

    Rate-limited to one regeneration every ten minutes and budget-counted like
    any other model call. Raises a problem when it is too soon, when there is
    nothing to summarise yet, or when no summary can be produced (no classifier
    configured, or the budget is used up).
    """
    now = now or datetime.now(UTC)
    today = now.astimezone(tz).date()

    existing = narrative_cache.cached_narrative(session, today)
    if existing is not None:
        age = (now - existing.generated_at).total_seconds()
        if age < MIN_SUMMARY_INTERVAL_S:
            raise ProblemException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                APIErrorCode.SUMMARY_RATE_LIMITED,
                "today's summary was refreshed moments ago; try again shortly",
                extensions={"retry_after_s": int(MIN_SUMMARY_INTERVAL_S - age)},
            )

    if narrative_cache.build_narrative_input(session, day=today, tz=tz) is None:
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.SUMMARY_UNAVAILABLE,
            "nothing has been recorded today yet, so there is nothing to summarise",
        )

    result = narrative_cache.generate_narrative(
        session,
        day=today,
        tz=tz,
        chain=chain,
        daily_call_cap=daily_call_cap,
        rolling=True,
        now=now,
    )
    if result is None:
        raise ProblemException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            APIErrorCode.SUMMARY_UNAVAILABLE,
            "the station could not write a summary right now; the model budget "
            "may be used up until it resets",
        )
    session.commit()
    return build_digest(session, day=today, tz=tz, today=today)
