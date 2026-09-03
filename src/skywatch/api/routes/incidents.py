"""Incident routes: group clips that belong together into an ordered bundle."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session
from starlette import status

from skywatch.api.deps import get_session
from skywatch.api.errors import ProblemDetail
from skywatch.api.schemas import (
    IncidentAddClip,
    IncidentCreate,
    IncidentDetail,
    IncidentListResponse,
    Link,
)
from skywatch.api.services import incidents as incidents_service

router = APIRouter(tags=["incidents"])


@router.get(
    "/incidents",
    response_model=IncidentListResponse,
    summary="List incident bundles",
    description=(
        "Listener-curated groups of clips that belong together — a go-around "
        "sequence, an emergency followed by its resolution — newest first."
    ),
)
def list_incidents(session: Annotated[Session, Depends(get_session)]) -> IncidentListResponse:
    return IncidentListResponse(
        items=incidents_service.list_incidents(session), links={"self": Link(href="/incidents")}
    )


@router.post(
    "/incidents",
    response_model=IncidentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new incident bundle",
    description="Creates an empty, titled incident; add clips to it afterwards.",
)
def create_incident(
    payload: IncidentCreate,
    session: Annotated[Session, Depends(get_session)],
) -> IncidentDetail:
    return incidents_service.create_incident(session, title=payload.title)


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentDetail,
    summary="One incident with its clips in order",
    responses={404: {"model": ProblemDetail, "description": "Unknown incident."}},
)
def get_incident(
    incident_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> IncidentDetail:
    return incidents_service.get_incident(session, incident_id)


@router.delete(
    "/incidents/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an incident bundle",
    description="Removes the bundle and its clip memberships; the clips themselves are untouched.",
    responses={404: {"model": ProblemDetail, "description": "Unknown incident."}},
)
def delete_incident(
    incident_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> None:
    incidents_service.delete_incident(session, incident_id)


@router.post(
    "/incidents/{incident_id}/clips",
    response_model=IncidentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add a clip to an incident",
    description=(
        "Appends a clip to the end of the incident's playback order. A clip "
        "already in the incident cannot be added twice."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown incident or recording."},
        409: {"model": ProblemDetail, "description": "The clip is already in this incident."},
    },
)
def add_clip(
    incident_id: int,
    payload: IncidentAddClip,
    session: Annotated[Session, Depends(get_session)],
) -> IncidentDetail:
    return incidents_service.add_clip(session, incident_id, recording_id=payload.recording_id)


@router.delete(
    "/incidents/{incident_id}/clips/{recording_id}",
    response_model=IncidentDetail,
    summary="Remove a clip from an incident",
    description=(
        "Drops one clip from the bundle and closes the gap in the playback "
        "order; the clip itself is untouched."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown incident or membership."}},
)
def remove_clip(
    incident_id: int,
    recording_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> IncidentDetail:
    return incidents_service.remove_clip(session, incident_id, recording_id)
