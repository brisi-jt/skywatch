"""Builds the daily digest: one station-local day, summarised.

Day boundaries follow the station's configured timezone, so "Tuesday"
means Tuesday as the listener experiences it, not UTC Tuesday.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import Session, select

from skywatch.api.schemas import DigestNarrative, DigestResponse, Link
from skywatch.api.services.recordings import build_summaries, day_start_utc
from skywatch.db.enums import FeedbackVerdict
from skywatch.db.models import Classification, Feedback, Recording
from skywatch.pipeline import narrative as narrative_cache

GREATEST_HITS_LIMIT = 8


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
