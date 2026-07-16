"""The daily digest route behind the dashboard's Today view."""

from datetime import date as date_type
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from skywatch.api.deps import get_session, get_timezone
from skywatch.api.schemas import DigestResponse
from skywatch.api.services.digest import build_digest

router = APIRouter(tags=["digest"])


@router.get(
    "/digest",
    response_model=DigestResponse,
    summary="One day on the airwaves",
    description=(
        "A summary of one station-local day: how many transmissions were "
        "recorded, how many were flagged interesting, the interesting clips "
        "themselves, and the all-time greatest hits (the clips with the most "
        "thumbs-up, regardless of day). Defaults to today; `previous_day` / "
        "`next_day` links page through history, and `next_day` is omitted "
        "for today. A day with zero recordings returns the same shape with "
        "zero counts and empty lists."
    ),
)
def get_digest(
    session: Annotated[Session, Depends(get_session)],
    tz: Annotated[ZoneInfo, Depends(get_timezone)],
    date: Annotated[
        date_type | None,
        Query(description="Local day to summarise (YYYY-MM-DD); today when omitted."),
    ] = None,
) -> DigestResponse:
    day = date or datetime.now(tz).date()
    return build_digest(session, day=day, tz=tz)
