"""Recordings library routes: browse clips, stream audio, give feedback."""

from datetime import date
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlmodel import Session
from starlette import status

from skywatch.api.deps import get_fts_available, get_session, get_settings, get_timezone
from skywatch.api.errors import APIErrorCode, ProblemDetail, ProblemException
from skywatch.api.schemas import (
    FeedbackCreate,
    FeedbackResource,
    Link,
    ReclassifyResponse,
    RecordingDetail,
    RecordingListResponse,
    WaveformResponse,
)
from skywatch.api.services import peaks as peaks_service
from skywatch.api.services.recordings import (
    RecordingFilters,
    build_detail,
    build_summaries,
    query_recordings,
)
from skywatch.api.services.search import parse_search
from skywatch.db.enums import ClassificationCategory, RecordingStage
from skywatch.db.models import Feedback, Recording
from skywatch.settings import Settings

router = APIRouter(tags=["recordings"])

MAX_PAGE_SIZE = 200

LimitParam = Annotated[
    int,
    Query(ge=1, le=MAX_PAGE_SIZE, description="Clips per page."),
]
OffsetParam = Annotated[int, Query(ge=0, description="Clips to skip from the newest.")]

_RECLASSIFIABLE_STAGES = {
    RecordingStage.TRANSCRIBED,
    RecordingStage.CLASSIFYING,
    RecordingStage.CLASSIFIED,
    RecordingStage.FAILED_CLASSIFY,
}


def _get_recording(session: Session, recording_id: int) -> Recording:
    recording = session.get(Recording, recording_id)
    if recording is None:
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.RECORDING_NOT_FOUND,
            f"no recording with id {recording_id}",
        )
    return recording


def page_links(request: Request, *, limit: int, offset: int, total: int) -> dict[str, Link]:
    def href(new_offset: int) -> str:
        params = dict(request.query_params)
        params["limit"] = str(limit)
        params["offset"] = str(new_offset)
        return f"{request.url.path}?{urlencode(params)}"

    links = {"self": Link(href=href(offset))}
    if offset + limit < total:
        links["next"] = Link(href=href(offset + limit))
    if offset > 0:
        links["prev"] = Link(href=href(max(0, offset - limit)))
    return links


@router.get(
    "/recordings",
    response_model=RecordingListResponse,
    summary="Browse the clip library",
    description=(
        "Recorded transmissions, newest first, as summary cards: frequency, "
        "timing, latest transcript snippet, latest verdict, most plausible "
        "aircraft candidate, and feedback tallies. All filters combine. Date "
        "filters are inclusive and use the station's local day boundaries. "
        "`interesting` and `category` match each clip's latest verdict, so a "
        "reclassified clip follows its newest classification. `has_match` "
        "selects clips with (or without) aircraft candidates. `q` searches "
        'transcripts, best match first: bare or "quoted" words are the '
        "search text, and the tokens `freq:`, `callsign:`, `interesting`, "
        "`before:<date>` and `after:<date>` narrow the results. Explicit "
        "filter parameters win over anything the same filter's token sets."
    ),
)
def list_recordings(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    tz: Annotated[ZoneInfo, Depends(get_timezone)],
    fts_available: Annotated[bool, Depends(get_fts_available)],
    from_date: Annotated[date | None, Query(description="Earliest local day to include.")] = None,
    to_date: Annotated[date | None, Query(description="Latest local day to include.")] = None,
    freq_id: Annotated[int | None, Query(description="Only clips from this frequency.")] = None,
    interesting: Annotated[
        bool | None,
        Query(description="true for clips whose latest verdict is interesting; false for routine."),
    ] = None,
    category: Annotated[
        ClassificationCategory | None,
        Query(description="Only clips whose latest verdict has this category."),
    ] = None,
    has_match: Annotated[
        bool | None, Query(description="Whether clips must have aircraft candidates.")
    ] = None,
    q: Annotated[
        str | None,
        Query(
            description=(
                "Search transcripts, with the "
                "freq:/callsign:/interesting/before:/after: grammar."
            )
        ),
    ] = None,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> RecordingListResponse:
    parsed = parse_search(q)
    filters = RecordingFilters(
        from_date=from_date if from_date is not None else parsed.after,
        to_date=to_date if to_date is not None else parsed.before,
        freq_id=freq_id,
        interesting=interesting if interesting is not None else (parsed.interesting or None),
        category=category,
        has_match=has_match,
        fts_match=parsed.fts_match,
        text_terms=parsed.text_terms,
        freq_query=parsed.freq,
        callsign=parsed.callsign,
    )
    rows, total = query_recordings(
        session, filters, tz=tz, limit=limit, offset=offset, fts_available=fts_available
    )
    return RecordingListResponse(
        items=build_summaries(session, rows),
        total=total,
        limit=limit,
        offset=offset,
        links=page_links(request, limit=limit, offset=offset, total=total),
    )


@router.get(
    "/recordings/{recording_id}",
    response_model=RecordingDetail,
    summary="One clip with full provenance",
    description=(
        "Everything the station knows about one clip: the latest transcript "
        "with engine provenance and confidence, the complete classification "
        "history (newest first — verdicts are appended, never overwritten), "
        "every ranked aircraft candidate, individual feedback entries, and "
        "any pipeline error the clip hit."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown recording."}},
)
def get_recording(
    recording_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> RecordingDetail:
    recording = _get_recording(session, recording_id)
    return build_detail(session, recording)


@router.get(
    "/recordings/{recording_id}/audio",
    summary="Stream a clip's audio",
    description=(
        "The clip as MP3 (8 kHz mono as captured). Supports HTTP Range "
        "requests, so seeking in an audio player works. Returns 410 once "
        "retention has pruned the audio of an old routine clip — the "
        "clip's metadata remains available."
    ),
    response_class=FileResponse,
    responses={
        200: {"content": {"audio/mpeg": {}}},
        206: {"description": "Partial content for a Range request."},
        404: {"model": ProblemDetail, "description": "Unknown recording or missing file."},
        410: {"model": ProblemDetail, "description": "Audio pruned by retention."},
    },
)
def get_audio(
    recording_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> FileResponse:
    recording = _get_recording(session, recording_id)
    if recording.audio_deleted_at is not None:
        raise ProblemException(
            status.HTTP_410_GONE,
            APIErrorCode.AUDIO_DELETED,
            "audio for this clip was pruned by the retention policy; its "
            "metadata and transcript remain available",
        )
    path = settings.data_root / recording.file_path
    if not path.is_file():
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.AUDIO_FILE_MISSING,
            "the audio file for this clip is not on disk",
        )
    return FileResponse(path, media_type="audio/mpeg", filename=path.name)


@router.get(
    "/recordings/{recording_id}/peaks",
    response_model=WaveformResponse,
    summary="A clip's waveform for the scrubber",
    description=(
        "Normalised amplitude peaks for drawing a static waveform behind the "
        "player's seek bar. Computed from the clip's MP3 the first time it is "
        "asked for and cached thereafter, so this is cheap on repeat visits. "
        "Returns 410 once retention has pruned the audio. The peaks array is "
        "empty when the station's audio decoder is unavailable — the scrubber "
        "then shows a plain track."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown recording or missing file."},
        410: {"model": ProblemDetail, "description": "Audio pruned by retention."},
    },
)
def get_peaks(
    recording_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WaveformResponse:
    recording = _get_recording(session, recording_id)
    if recording.audio_deleted_at is not None:
        raise ProblemException(
            status.HTTP_410_GONE,
            APIErrorCode.AUDIO_DELETED,
            "audio for this clip was pruned by the retention policy; its "
            "waveform is no longer available",
        )
    path = settings.data_root / recording.file_path
    if not path.is_file():
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.AUDIO_FILE_MISSING,
            "the audio file for this clip is not on disk",
        )
    peaks = peaks_service.load_or_compute(settings.data_root, recording_id, path)
    return WaveformResponse(
        recording_id=recording_id,
        peaks=peaks,
        links={
            "self": Link(href=f"/recordings/{recording_id}/peaks"),
            "audio": Link(href=f"/recordings/{recording_id}/audio"),
        },
    )


@router.post(
    "/recordings/{recording_id}/reclassify",
    response_model=ReclassifyResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a clip for reclassification",
    description=(
        "Sends the clip back through the classifier. The pipeline worker "
        "picks it up on its next pass and appends a fresh verdict to the "
        "clip's history (nothing is overwritten). Returns 202 immediately; "
        "watch the stream or re-fetch the clip for the new verdict. Clips "
        "that have not been transcribed yet cannot be reclassified."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown recording."},
        409: {"model": ProblemDetail, "description": "Clip has not been transcribed yet."},
    },
)
def reclassify_recording(
    recording_id: int,
    session: Annotated[Session, Depends(get_session)],
) -> ReclassifyResponse:
    recording = _get_recording(session, recording_id)
    if recording.stage not in _RECLASSIFIABLE_STAGES:
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.RECORDING_NOT_CLASSIFIABLE,
            f"clip is at stage '{recording.stage.value}'; it can be "
            "reclassified once transcription has completed",
        )
    if recording.stage in (RecordingStage.CLASSIFIED, RecordingStage.FAILED_CLASSIFY):
        recording.stage = RecordingStage.TRANSCRIBED
        session.add(recording)
        session.commit()
    return ReclassifyResponse(
        recording_id=recording_id,
        stage=RecordingStage.TRANSCRIBED,
        detail="queued for reclassification; a new verdict will be appended shortly",
        links={"recording": Link(href=f"/recordings/{recording_id}")},
    )


@router.post(
    "/recordings/{recording_id}/feedback",
    response_model=FeedbackResource,
    status_code=status.HTTP_201_CREATED,
    summary="Record a thumbs-up or thumbs-down",
    description=(
        "Stores a listener verdict on whether the clip was worth hearing. "
        "Verdicts accumulate — they are individual votes, not a toggle — and "
        "feed the all-time greatest-hits list in the digest."
    ),
    responses={404: {"model": ProblemDetail, "description": "Unknown recording."}},
)
def create_feedback(
    recording_id: int,
    payload: FeedbackCreate,
    session: Annotated[Session, Depends(get_session)],
) -> FeedbackResource:
    recording = _get_recording(session, recording_id)
    row = Feedback(recording_id=recording.id, verdict=payload.verdict, note=payload.note)
    session.add(row)
    session.commit()
    session.refresh(row)
    return FeedbackResource(
        id=row.id,
        recording_id=row.recording_id,
        verdict=row.verdict,
        note=row.note,
        created_at=row.created_at,
        links={"recording": Link(href=f"/recordings/{recording_id}")},
    )
