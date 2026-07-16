"""The station status route."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from skywatch.api.deps import get_capture, get_session, get_settings
from skywatch.api.schemas import StatusResponse
from skywatch.api.services.capture import CaptureController
from skywatch.api.services.status import build_status
from skywatch.settings import Settings

router = APIRouter(tags=["status"])


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Station health at a glance",
    description=(
        "Everything the station knows about its own health: capture state "
        "(source, mode, tuner centre frequency, dongle presence, the "
        "disk-guard pause flag), a three-step trace of the capture chain "
        "(database plan → rendered config file → running process) that "
        "pinpoints where a frequency change stalled, pipeline queue depths "
        "per stage, disk headroom, and today's spend against the external "
        "API budgets. `station_name` is null until the owner names the "
        "station — the cue for a first-run naming dialog."
    ),
)
def get_status(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    capture: Annotated[CaptureController, Depends(get_capture)],
) -> StatusResponse:
    return build_status(session, settings=settings, capture=capture)
