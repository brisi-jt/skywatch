"""The interesting-clips shortcut route."""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from skywatch.api.deps import get_session, get_timezone
from skywatch.api.routes.recordings import LimitParam, OffsetParam, page_links
from skywatch.api.schemas import RecordingListResponse
from skywatch.api.services.recordings import (
    RecordingFilters,
    build_summaries,
    query_recordings,
)

router = APIRouter(tags=["recordings"])


@router.get(
    "/clips/interesting",
    response_model=RecordingListResponse,
    summary="The clips worth hearing",
    description=(
        "Clips whose latest verdict is interesting, newest first — the "
        "default library view. Equivalent to /recordings?interesting=true, "
        "kept as its own route because it is the page most clients open "
        "first."
    ),
)
def list_interesting_clips(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    tz: Annotated[ZoneInfo, Depends(get_timezone)],
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> RecordingListResponse:
    rows, total = query_recordings(
        session, RecordingFilters(interesting=True), tz=tz, limit=limit, offset=offset
    )
    return RecordingListResponse(
        items=build_summaries(session, rows),
        total=total,
        limit=limit,
        offset=offset,
        links=page_links(request, limit=limit, offset=offset, total=total),
    )
