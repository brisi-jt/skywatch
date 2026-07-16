"""Transcription stage: one clip through the configured ASR engine.

ASR is the pipeline's bottleneck (slower than real time on the production
machine), so the worker calls this strictly sequentially. A re-run after a
crash replaces any transcript from the interrupted attempt.
"""

from pathlib import Path

from sqlmodel import Session, delete

from skywatch.db.models import Recording, Transcript
from skywatch.providers.asr.base import ASREngine


def run_transcribe(
    session: Session,
    recording: Recording,
    *,
    engine: ASREngine,
    data_root: Path,
) -> Transcript:
    """Transcribe one recording; raises ``ASRError`` for the retry path."""
    audio_path = Path(data_root) / recording.file_path
    result = engine.transcribe(audio_path)
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
    return transcript
