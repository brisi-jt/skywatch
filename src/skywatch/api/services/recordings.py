"""Query helpers and response builders for the recordings library.

A clip's "current" transcript and classification are the newest rows of
each kind (classification history is append-only; the latest verdict wins).
Summary building is batched so a page of clips costs a handful of queries
rather than one per clip.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_
from sqlalchemy import text as sa_text
from sqlmodel import Session, select

from skywatch.api.schemas import (
    AircraftMatchResource,
    ClassificationResource,
    FeedbackCounts,
    FeedbackResource,
    FrequencyRef,
    Link,
    RecordingDetail,
    RecordingSummary,
    TranscriptResource,
    TranscriptSegmentResource,
)
from skywatch.db.enums import ClassificationCategory, FeedbackVerdict
from skywatch.db.models import (
    AircraftMatch,
    Classification,
    Feedback,
    Frequency,
    Recording,
    Transcript,
    TranscriptSegment,
)

SNIPPET_LENGTH = 140


@dataclass(frozen=True)
class RecordingFilters:
    from_date: date | None = None
    to_date: date | None = None
    freq_id: int | None = None
    interesting: bool | None = None
    category: ClassificationCategory | None = None
    has_match: bool | None = None
    starred: bool | None = None
    # Search: free text (from the ``q`` grammar) plus its structured tokens.
    fts_match: str | None = None
    text_terms: tuple[str, ...] = ()
    freq_query: str | None = None
    callsign: str | None = None


def day_start_utc(day: date, tz: ZoneInfo) -> datetime:
    """The UTC instant at which a station-local day begins."""
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def _latest_classification_join(stmt):
    latest = (
        select(
            Classification.recording_id,
            func.max(Classification.id).label("classification_id"),
        )
        .group_by(Classification.recording_id)
        .subquery()
    )
    return (
        stmt.join(latest, latest.c.recording_id == Recording.id).join(
            Classification, Classification.id == latest.c.classification_id
        ),
        Classification,
    )


def query_recordings(
    session: Session,
    filters: RecordingFilters,
    *,
    tz: ZoneInfo,
    limit: int,
    offset: int,
    fts_available: bool = False,
) -> tuple[list[Recording], int]:
    """Filtered, newest-first page of recordings plus the unpaged total.

    With a free-text search the page is ordered by relevance (best match
    first) when the FTS5 index is available, and by recency otherwise. Set
    ``fts_available`` from the running database's capability probe.
    """
    stmt = select(Recording)
    if filters.from_date is not None:
        stmt = stmt.where(Recording.started_at_utc >= day_start_utc(filters.from_date, tz))
    if filters.to_date is not None:
        end = day_start_utc(filters.to_date + timedelta(days=1), tz)
        stmt = stmt.where(Recording.started_at_utc < end)
    if filters.freq_id is not None:
        stmt = stmt.where(Recording.freq_id == filters.freq_id)
    if filters.freq_query is not None:
        stmt = stmt.join(Frequency, Frequency.id == Recording.freq_id)
        conditions = [Frequency.label.ilike(f"%{filters.freq_query}%")]
        try:
            wanted_mhz = float(filters.freq_query)
        except ValueError:
            pass
        else:
            conditions.append(func.abs(Frequency.mhz - wanted_mhz) < 0.001)
        stmt = stmt.where(or_(*conditions))
    if filters.interesting is not None or filters.category is not None:
        stmt, latest_cls = _latest_classification_join(stmt)
        if filters.interesting is not None:
            stmt = stmt.where(latest_cls.is_interesting == filters.interesting)
        if filters.category is not None:
            stmt = stmt.where(latest_cls.category == filters.category)
    if filters.has_match is not None:
        match_exists = (
            select(AircraftMatch.id).where(AircraftMatch.recording_id == Recording.id).exists()
        )
        stmt = stmt.where(match_exists if filters.has_match else ~match_exists)
    if filters.starred is not None:
        stmt = stmt.where(
            Recording.starred_at.is_not(None)  # type: ignore[union-attr]
            if filters.starred
            else Recording.starred_at.is_(None)  # type: ignore[union-attr]
        )
    if filters.callsign is not None:
        callsign_exists = (
            select(AircraftMatch.id)
            .where(
                AircraftMatch.recording_id == Recording.id,
                AircraftMatch.callsign.ilike(f"%{filters.callsign}%"),  # type: ignore[union-attr]
            )
            .exists()
        )
        stmt = stmt.where(callsign_exists)

    ranked_ids: list[int] | None = None
    if filters.text_terms:
        if fts_available and filters.fts_match is not None:
            # bm25 can only be read when the FTS table is the one being
            # iterated, so match it alone (no join, which would let the planner
            # drive from transcripts and drop bm25's context) and map the
            # transcript rowids back to recordings here.
            matches = session.execute(
                sa_text(
                    "SELECT rowid AS tid, bm25(transcripts_fts) AS rank "
                    "FROM transcripts_fts WHERE transcripts_fts MATCH :fts_match "
                    "ORDER BY rank"
                ).bindparams(fts_match=filters.fts_match)
            ).all()
            transcript_ids = [row[0] for row in matches]  # best-ranked first
            if not transcript_ids:
                return [], 0
            recording_by_transcript = dict(
                session.execute(
                    select(Transcript.id, Transcript.recording_id).where(
                        Transcript.id.in_(transcript_ids)  # type: ignore[attr-defined]
                    )
                ).all()
            )
            ranked_ids = []
            seen: set[int] = set()
            for transcript_id in transcript_ids:
                recording_id = recording_by_transcript.get(transcript_id)
                if recording_id is not None and recording_id not in seen:
                    seen.add(recording_id)
                    ranked_ids.append(recording_id)
            if not ranked_ids:
                return [], 0
            stmt = stmt.where(Recording.id.in_(ranked_ids))  # type: ignore[attr-defined]
        else:
            # No FTS5: match every term as a substring of the transcript text.
            for term in filters.text_terms:
                term_exists = (
                    select(Transcript.id)
                    .where(
                        Transcript.recording_id == Recording.id,
                        Transcript.text.ilike(f"%{term}%"),  # type: ignore[union-attr]
                    )
                    .exists()
                )
                stmt = stmt.where(term_exists)

    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    order = []
    if ranked_ids is not None:
        # Preserve the bm25 order (best match first) across pagination.
        order.append(
            case(
                {rid: index for index, rid in enumerate(ranked_ids)},
                value=Recording.id,
                else_=len(ranked_ids),
            )
        )
    order += [
        Recording.started_at_utc.desc(),  # type: ignore[attr-defined]
        Recording.id.desc(),  # type: ignore[union-attr]
    ]
    rows = session.exec(stmt.order_by(*order).limit(limit).offset(offset)).all()
    return list(rows), int(total)


# -- batched summary building ---------------------------------------------------------


def _latest_per_recording(rows) -> dict[int, object]:
    """Newest row per recording_id, assuming ascending id order."""
    latest: dict[int, object] = {}
    for row in rows:
        latest[row.recording_id] = row
    return latest


def _feedback_counts(session: Session, ids: list[int]) -> dict[int, FeedbackCounts]:
    counts: dict[int, dict[str, int]] = {rec_id: {"up": 0, "down": 0} for rec_id in ids}
    rows = session.exec(
        select(Feedback.recording_id, Feedback.verdict, func.count())
        .where(Feedback.recording_id.in_(ids))  # type: ignore[attr-defined]
        .group_by(Feedback.recording_id, Feedback.verdict)
    ).all()
    for rec_id, verdict, count in rows:
        counts[rec_id][FeedbackVerdict(verdict).value] = count
    return {rec_id: FeedbackCounts(**tallies) for rec_id, tallies in counts.items()}


def recording_links(recording: Recording) -> dict[str, Link]:
    links = {
        "self": Link(href=f"/recordings/{recording.id}"),
        "frequency": Link(href=f"/recordings?freq_id={recording.freq_id}"),
        "reclassify": Link(href=f"/recordings/{recording.id}/reclassify"),
        "feedback": Link(href=f"/recordings/{recording.id}/feedback"),
    }
    if recording.audio_deleted_at is None:
        links["audio"] = Link(href=f"/recordings/{recording.id}/audio")
        links["peaks"] = Link(href=f"/recordings/{recording.id}/peaks")
    return links


def build_summaries(session: Session, recordings: list[Recording]) -> list[RecordingSummary]:
    if not recordings:
        return []
    ids = [rec.id for rec in recordings]
    freq_ids = {rec.freq_id for rec in recordings}
    frequencies = {
        f.id: f
        for f in session.exec(
            select(Frequency).where(Frequency.id.in_(freq_ids))  # type: ignore[attr-defined]
        ).all()
    }
    transcripts = _latest_per_recording(
        session.exec(
            select(Transcript)
            .where(Transcript.recording_id.in_(ids))  # type: ignore[attr-defined]
            .order_by(Transcript.id)  # type: ignore[arg-type]
        ).all()
    )
    classifications = _latest_per_recording(
        session.exec(
            select(Classification)
            .where(Classification.recording_id.in_(ids))  # type: ignore[attr-defined]
            .order_by(Classification.id)  # type: ignore[arg-type]
        ).all()
    )
    top_matches: dict[int, AircraftMatch] = {}
    for match in session.exec(
        select(AircraftMatch)
        .where(AircraftMatch.recording_id.in_(ids))  # type: ignore[attr-defined]
        .order_by(AircraftMatch.rank.desc())  # type: ignore[attr-defined]
    ).all():
        top_matches[match.recording_id] = match  # descending rank: best (rank 1) lands last
    feedback = _feedback_counts(session, ids)

    summaries = []
    for rec in recordings:
        freq = frequencies[rec.freq_id]
        transcript = transcripts.get(rec.id)
        classification = classifications.get(rec.id)
        match = top_matches.get(rec.id)
        summaries.append(
            RecordingSummary(
                id=rec.id,
                frequency=FrequencyRef(id=freq.id, label=freq.label, mhz=freq.mhz),
                started_at_utc=rec.started_at_utc,
                ended_at_utc=rec.ended_at_utc,
                duration_s=rec.duration_s,
                stage=rec.stage,
                audio_available=rec.audio_deleted_at is None,
                transcript_snippet=(
                    transcript.text[:SNIPPET_LENGTH] if transcript is not None else None
                ),
                classification=(
                    _classification_resource(classification) if classification else None
                ),
                top_match=_match_resource(match) if match else None,
                feedback=feedback[rec.id],
                starred_at=rec.starred_at,
                links=recording_links(rec),
            )
        )
    return summaries


def build_detail(session: Session, recording: Recording) -> RecordingDetail:
    summary = build_summaries(session, [recording])[0]
    transcript = session.exec(
        select(Transcript)
        .where(Transcript.recording_id == recording.id)
        .order_by(Transcript.id.desc())  # type: ignore[union-attr]
    ).first()
    classifications = session.exec(
        select(Classification)
        .where(Classification.recording_id == recording.id)
        .order_by(Classification.id.desc())  # type: ignore[union-attr]
    ).all()
    matches = session.exec(
        select(AircraftMatch)
        .where(AircraftMatch.recording_id == recording.id)
        .order_by(AircraftMatch.rank)  # type: ignore[arg-type]
    ).all()
    entries = session.exec(
        select(Feedback).where(Feedback.recording_id == recording.id).order_by(Feedback.id.desc())  # type: ignore[union-attr]
    ).all()
    segments = (
        session.exec(
            select(TranscriptSegment)
            .where(TranscriptSegment.transcript_id == transcript.id)
            .order_by(TranscriptSegment.start_s, TranscriptSegment.id)  # type: ignore[arg-type]
        ).all()
        if transcript is not None
        else []
    )
    return RecordingDetail(
        **summary.model_dump(exclude={"links"}),
        sample_rate=recording.sample_rate,
        file_path=recording.file_path,
        stage_error=recording.stage_error,
        audio_deleted_at=recording.audio_deleted_at,
        transcript=_transcript_resource(transcript, segments) if transcript else None,
        classifications=[_classification_resource(c) for c in classifications],
        matches=[_match_resource(m) for m in matches],
        feedback_entries=[
            FeedbackResource(
                id=entry.id,
                recording_id=entry.recording_id,
                verdict=entry.verdict,
                note=entry.note,
                created_at=entry.created_at,
                links={"recording": Link(href=f"/recordings/{recording.id}")},
            )
            for entry in entries
        ],
        links=summary.links,
    )


def _transcript_resource(
    row: Transcript, segments: list[TranscriptSegment] | None = None
) -> TranscriptResource:
    return TranscriptResource(
        id=row.id,
        engine=row.engine,
        model=row.model,
        text=row.text,
        avg_logprob=row.avg_logprob,
        language=row.language,
        segments=[
            TranscriptSegmentResource(
                id=seg.id,
                start_s=seg.start_s,
                end_s=seg.end_s,
                text=seg.text,
                avg_word_prob=seg.avg_word_prob,
            )
            for seg in (segments or [])
        ],
        created_at=row.created_at,
    )


def _classification_resource(row: Classification) -> ClassificationResource:
    return ClassificationResource(
        id=row.id,
        is_interesting=row.is_interesting,
        category=row.category,
        confidence=row.confidence,
        reason=row.reason,
        source=row.source,
        model=row.model,
        prefilter_flags=row.prefilter_flags,
        status=row.status,
        created_at=row.created_at,
    )


def _match_resource(row: AircraftMatch) -> AircraftMatchResource:
    return AircraftMatchResource(
        id=row.id,
        source=row.source,
        icao24=row.icao24,
        callsign=row.callsign,
        airline_name=row.airline_name,
        flight_number_guess=row.flight_number_guess,
        lat=row.lat,
        lon=row.lon,
        alt_ft=row.alt_ft,
        gs_kt=row.gs_kt,
        distance_km=row.distance_km,
        match_confidence=row.match_confidence,
        rank=row.rank,
        queried_at=row.queried_at,
        alert_category=row.alert_category,
        registration=row.registration,
        aircraft_type=row.aircraft_type,
        operator_name=row.operator_name,
    )
