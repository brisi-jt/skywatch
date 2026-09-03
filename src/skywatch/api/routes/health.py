"""Health history route: the Station view's uptime sparkline."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from skywatch.api.deps import get_session
from skywatch.api.schemas import HealthHistoryResponse
from skywatch.api.services.health import build_health_history

router = APIRouter(tags=["health"])

MAX_PAGE_SIZE = 2000


@router.get(
    "/health/history",
    response_model=HealthHistoryResponse,
    summary="Station health over time",
    description=(
        "A run of health snapshots taken during the worker's maintenance "
        "pass: whether capture was running, pipeline queue depths, free "
        "disk, and the classifier/flight-data budgets remaining. Defaults "
        "to the last seven days, oldest first, when `since` is omitted."
    ),
)
def get_health_history(
    session: Annotated[Session, Depends(get_session)],
    since: Annotated[
        datetime | None, Query(description="Earliest snapshot to include (UTC).")
    ] = None,
    until: Annotated[
        datetime | None, Query(description="Latest snapshot to include (UTC).")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE, description="Snapshots to return.")] = 500,
) -> HealthHistoryResponse:
    return build_health_history(session, since=since, until=until, limit=limit)
