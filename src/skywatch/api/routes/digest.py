"""The daily digest route behind the dashboard's Today view."""

from datetime import date as date_type
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from skywatch.api.deps import (
    get_classifier_chain,
    get_session,
    get_settings,
    get_timezone,
)
from skywatch.api.schemas import DigestResponse, NotableDaysResponse
from skywatch.api.services.digest import build_digest, build_notable_days, regenerate_today_summary
from skywatch.settings import Settings

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


@router.post(
    "/digest/summary",
    response_model=DigestResponse,
    summary="Summarise today so far",
    description=(
        "Regenerates today's written narrative from everything recorded so far "
        "and returns today's digest with the fresh summary attached (marked as "
        "an 'as of now' refresh). Rate-limited to once every ten minutes and "
        "counted against the station's daily model budget. Returns 429 "
        "`summary_rate_limited` if refreshed too recently, 409 "
        "`summary_unavailable` when nothing has been recorded today yet, and "
        "503 `summary_unavailable` when no summary can be produced (no "
        "classifier configured, or the budget is used up)."
    ),
)
def summarise_today(
    session: Annotated[Session, Depends(get_session)],
    tz: Annotated[ZoneInfo, Depends(get_timezone)],
    settings: Annotated[Settings, Depends(get_settings)],
    chain: Annotated[list, Depends(get_classifier_chain)],
) -> DigestResponse:
    return regenerate_today_summary(
        session, tz=tz, chain=chain, daily_call_cap=settings.llm.daily_call_cap
    )


@router.get(
    "/digest/notable",
    response_model=NotableDaysResponse,
    summary="The station's most eventful days",
    description=(
        "Station-local days ranked by weighted interestingness — emergency, "
        "guard-frequency and go-around clips count for more than an ordinary "
        "interesting flag, so a single real emergency call can outrank a day "
        "with several routine flags. Empty until a clip has been flagged "
        "interesting."
    ),
)
def get_notable_days(
    session: Annotated[Session, Depends(get_session)],
    tz: Annotated[ZoneInfo, Depends(get_timezone)],
) -> NotableDaysResponse:
    return build_notable_days(session, tz=tz)
