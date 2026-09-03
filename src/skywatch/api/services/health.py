"""Builds the station's health history: a run of worker heartbeats."""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from skywatch.api.schemas import HealthHistoryResponse, HeartbeatResource, Link
from skywatch.db.models import Heartbeat

DEFAULT_WINDOW_DAYS = 7
"""How far back a request looks when it doesn't specify ``since``."""

MAX_ITEMS = 2000
"""Hard ceiling on rows returned, independent of the requested window."""


def build_health_history(
    session: Session,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 500,
    now: datetime | None = None,
) -> HealthHistoryResponse:
    """Heartbeats within ``[since, until]``, oldest first, for a sparkline.

    Defaults to the last week when ``since`` is omitted, and to now when
    ``until`` is omitted. ``limit`` is a client-facing page size; the true
    ceiling is ``MAX_ITEMS`` regardless of what is requested.
    """
    now = now or datetime.now(UTC)
    until = until or now
    since = since or (until - timedelta(days=DEFAULT_WINDOW_DAYS))
    capped_limit = max(1, min(limit, MAX_ITEMS))

    rows = list(
        session.exec(
            select(Heartbeat)
            .where(Heartbeat.created_at >= since, Heartbeat.created_at <= until)
            .order_by(Heartbeat.created_at)  # type: ignore[arg-type]
            .limit(capped_limit)
        ).all()
    )
    return HealthHistoryResponse(
        since=since,
        until=until,
        items=[
            HeartbeatResource(
                recorded_at=row.created_at,
                capture_running=row.capture_running,
                queue_depths=row.queue_depths,
                disk_free_gb=row.disk_free_gb,
                llm_remaining=row.llm_remaining,
                opensky_remaining=row.opensky_remaining,
            )
            for row in rows
        ],
        links={"self": Link(href="/health/history")},
    )
