"""Query helpers and mutations for listener-curated incident bundles."""

from sqlalchemy import func
from sqlmodel import Session, select
from starlette import status

from skywatch.api.errors import APIErrorCode, ProblemException
from skywatch.api.schemas import (
    IncidentClipResource,
    IncidentDetail,
    IncidentSummary,
    Link,
)
from skywatch.api.services.recordings import build_summaries
from skywatch.db.models import Incident, IncidentClip, Recording


def _get_incident(session: Session, incident_id: int) -> Incident:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.INCIDENT_NOT_FOUND,
            f"no incident with id {incident_id}",
        )
    return incident


def _clips(session: Session, incident_id: int) -> list[IncidentClip]:
    return list(
        session.exec(
            select(IncidentClip)
            .where(IncidentClip.incident_id == incident_id)
            .order_by(IncidentClip.position)  # type: ignore[arg-type]
        ).all()
    )


def incident_links(incident_id: int) -> dict[str, Link]:
    return {
        "self": Link(href=f"/incidents/{incident_id}"),
        "clips": Link(href=f"/incidents/{incident_id}/clips"),
    }


def _to_detail(session: Session, incident: Incident) -> IncidentDetail:
    clips = _clips(session, incident.id)
    recordings = {
        rec.id: rec
        for rec in session.exec(
            select(Recording).where(
                Recording.id.in_([clip.recording_id for clip in clips])  # type: ignore[attr-defined]
            )
        ).all()
    }
    summaries = {
        rec_id: summary
        for rec_id, summary in zip(
            recordings.keys(), build_summaries(session, list(recordings.values())), strict=True
        )
    }
    return IncidentDetail(
        id=incident.id,
        title=incident.title,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
        clips=[
            IncidentClipResource(position=clip.position, recording=summaries[clip.recording_id])
            for clip in clips
            if clip.recording_id in summaries
        ],
        links=incident_links(incident.id),
    )


def list_incidents(session: Session) -> list[IncidentSummary]:
    incidents = session.exec(
        select(Incident).order_by(Incident.created_at.desc(), Incident.id.desc())  # type: ignore[union-attr]
    ).all()
    ids = [incident.id for incident in incidents]
    counts: dict[int, int] = dict.fromkeys(ids, 0)
    if ids:
        rows = session.exec(
            select(IncidentClip.incident_id, func.count())
            .where(IncidentClip.incident_id.in_(ids))  # type: ignore[attr-defined]
            .group_by(IncidentClip.incident_id)
        ).all()
        counts.update(dict(rows))
    return [
        IncidentSummary(
            id=incident.id,
            title=incident.title,
            clip_count=counts.get(incident.id, 0),
            created_at=incident.created_at,
            updated_at=incident.updated_at,
            links=incident_links(incident.id),
        )
        for incident in incidents
    ]


def create_incident(session: Session, *, title: str) -> IncidentDetail:
    incident = Incident(title=title)
    session.add(incident)
    session.commit()
    session.refresh(incident)
    return _to_detail(session, incident)


def get_incident(session: Session, incident_id: int) -> IncidentDetail:
    incident = _get_incident(session, incident_id)
    return _to_detail(session, incident)


def delete_incident(session: Session, incident_id: int) -> None:
    incident = _get_incident(session, incident_id)
    for clip in _clips(session, incident_id):
        session.delete(clip)
    session.flush()  # clip rows must be gone before the incident's FK target disappears
    session.delete(incident)
    session.commit()


def add_clip(session: Session, incident_id: int, *, recording_id: int) -> IncidentDetail:
    incident = _get_incident(session, incident_id)
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.RECORDING_NOT_FOUND,
            f"no recording with id {recording_id}",
        )
    existing = _clips(session, incident_id)
    if any(clip.recording_id == recording_id for clip in existing):
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.RECORDING_ALREADY_IN_INCIDENT,
            f"clip {recording_id} is already part of this incident",
        )
    session.add(
        IncidentClip(incident_id=incident_id, recording_id=recording_id, position=len(existing))
    )
    session.commit()
    return _to_detail(session, incident)


def remove_clip(session: Session, incident_id: int, recording_id: int) -> IncidentDetail:
    incident = _get_incident(session, incident_id)
    existing = _clips(session, incident_id)
    target = next((clip for clip in existing if clip.recording_id == recording_id), None)
    if target is None:
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.INCIDENT_CLIP_NOT_FOUND,
            f"clip {recording_id} is not part of incident {incident_id}",
        )
    session.delete(target)
    session.flush()
    # Renumber the remaining clips so positions stay contiguous from zero.
    remaining = [clip for clip in existing if clip.id != target.id]
    for index, clip in enumerate(remaining):
        if clip.position != index:
            clip.position = index
            session.add(clip)
    session.commit()
    return _to_detail(session, incident)
