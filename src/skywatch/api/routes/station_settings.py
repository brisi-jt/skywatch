"""Owner-editable station settings routes."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from skywatch.api.deps import get_session
from skywatch.api.errors import ProblemDetail
from skywatch.api.schemas import SettingsResponse
from skywatch.api.services import station_settings

router = APIRouter(tags=["settings"])


@router.get(
    "/settings",
    response_model=SettingsResponse,
    summary="Read the station settings",
    description=(
        "The owner-editable settings. `station_name` is null until the "
        "station has been named — the cue to offer a naming dialog on first "
        "run."
    ),
)
def get_settings(session: Annotated[Session, Depends(get_session)]) -> SettingsResponse:
    return station_settings.settings_view(session)


@router.patch(
    "/settings",
    response_model=SettingsResponse,
    summary="Update station settings",
    description=(
        "Partial update: send only the keys to change. `station_name` is "
        "currently the only editable key; anything else is rejected with a "
        "400 problem detail listing the allowed keys. A successful rename is "
        "announced on the event stream as `status.changed`, so other open "
        "dashboards update live."
    ),
    responses={
        400: {"model": ProblemDetail, "description": "Unknown setting key."},
        422: {"model": ProblemDetail, "description": "Invalid setting value."},
    },
)
def patch_settings(
    session: Annotated[Session, Depends(get_session)],
    payload: Annotated[
        dict[str, str],
        Body(
            description="Setting keys to update with their new values.",
            examples=[{"station_name": "My Airband Station"}],
        ),
    ],
) -> SettingsResponse:
    return station_settings.apply_patch(session, payload)
