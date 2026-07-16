"""Per-provider, per-day API budget accounting against ``api_usage``.

One row per (provider, day) — the table enforces that — so a check is a
single select and consumption is a select-then-update inside the caller's
session (the worker is the only writer).
"""

from datetime import date

from sqlmodel import Session, select

from skywatch.db.enums import ApiProvider
from skywatch.db.models import ApiUsage


def usage_for(session: Session, provider: ApiProvider, day: date) -> ApiUsage:
    """The accounting row for one provider-day, created on first touch."""
    row = session.exec(
        select(ApiUsage).where(ApiUsage.provider == provider, ApiUsage.day == day)
    ).first()
    if row is None:
        row = ApiUsage(provider=provider, day=day, calls=0)
        session.add(row)
        session.flush()
    return row


def calls_today(session: Session, provider: ApiProvider, day: date) -> int:
    row = session.exec(
        select(ApiUsage).where(ApiUsage.provider == provider, ApiUsage.day == day)
    ).first()
    return row.calls if row is not None else 0


def remaining(session: Session, provider: ApiProvider, day: date, cap: int) -> int:
    return max(0, cap - calls_today(session, provider, day))


def record_call(
    session: Session,
    provider: ApiProvider,
    day: date,
    *,
    count: int = 1,
    tokens: int | None = None,
) -> ApiUsage:
    row = usage_for(session, provider, day)
    row.calls += count
    if tokens is not None:
        row.tokens = (row.tokens or 0) + tokens
    session.add(row)
    return row
