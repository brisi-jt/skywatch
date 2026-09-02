"""Transcription stage: one clip through the configured ASR engine.

ASR is the pipeline's bottleneck (slower than real time on the production
machine), so the worker calls this strictly sequentially. A re-run after a
crash replaces any transcript from the interrupted attempt.
"""

from collections.abc import Sequence
from pathlib import Path

from sqlmodel import Session, delete, select

from skywatch.db.models import AircraftMatch, Recording, Transcript, TranscriptSegment
from skywatch.providers.asr.base import ASREngine
from skywatch.providers.asr.verbalize import verbalize_callsigns


def callsign_hotwords(session: Session, recording_id: int, airlines) -> list[str]:
    """Spoken forms of a clip's probable-aircraft callsigns, best rank first.

    Returns ``[]`` when enrichment found no candidates (or was never run),
    so callers can pass the result straight through — the recogniser simply
    gets no bias.
    """
    callsigns = session.exec(
        select(AircraftMatch.callsign)
        .where(AircraftMatch.recording_id == recording_id)
        .order_by(AircraftMatch.rank)  # type: ignore[arg-type]
    ).all()
    return verbalize_callsigns(callsigns, airlines)


def run_transcribe(
    session: Session,
    recording: Recording,
    *,
    engine: ASREngine,
    data_root: Path,
    hotwords: Sequence[str] | None = None,
    initial_prompt: str | None = None,
) -> Transcript:
    """Transcribe one recording; raises ``ASRError`` for the retry path.

    ``hotwords``/``initial_prompt`` bias the recogniser towards expected
    callsigns; engines that cannot use them ignore them. Re-running replaces
    any transcript (and its segments) from an interrupted attempt.
    """
    audio_path = Path(data_root) / recording.file_path
    result = engine.transcribe(audio_path, hotwords=hotwords, initial_prompt=initial_prompt)

    stale_ids = session.exec(
        select(Transcript.id).where(Transcript.recording_id == recording.id)
    ).all()
    if stale_ids:
        session.exec(
            delete(TranscriptSegment).where(
                TranscriptSegment.transcript_id.in_(stale_ids)  # type: ignore[attr-defined]
            )
        )
    session.exec(delete(Transcript).where(Transcript.recording_id == recording.id))

    transcript = Transcript(
        recording_id=recording.id,
        engine=result.engine,
        model=result.model,
        text=result.text,
        avg_logprob=result.avg_logprob,
        language=result.language,
    )
    session.add(transcript)
    session.flush()  # assign transcript.id before attaching segments
    for seg in result.segments:
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                start_s=seg.start_s,
                end_s=seg.end_s,
                text=seg.text,
                avg_word_prob=seg.avg_word_prob,
            )
        )
    return transcript
