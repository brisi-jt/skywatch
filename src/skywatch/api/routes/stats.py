"""The stats route behind the dashboard's story page."""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlmodel import Session

from skywatch.api.deps import get_session, get_timezone
from skywatch.api.schemas import StatsResponse
from skywatch.api.services.stats import build_stats

router = APIRouter(tags=["stats"])


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="The station's story in numbers",
    description=(
        "Aggregate numbers over the station's most recent listening window: "
        "the daily movement trend, a busiest-hour-by-frequency heat grid, the "
        "airlines heard most often, the share of transmissions flagged "
        "interesting, and how many go-arounds were recorded. Returns the same "
        "zeroed shape when the window has no recordings yet."
    ),
)
def get_stats(
    session: Annotated[Session, Depends(get_session)],
    tz: Annotated[ZoneInfo, Depends(get_timezone)],
) -> StatsResponse:
    return build_stats(session, tz=tz)
