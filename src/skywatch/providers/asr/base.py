"""The contract every speech-to-text engine honours."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from skywatch.db.enums import AsrEngine


class ASRError(RuntimeError):
    """Transcription failed; the clip can be retried later."""


@dataclass(frozen=True)
class TranscriptionResult:
    """One clip's transcript with full engine provenance."""

    text: str
    avg_logprob: float | None
    language: str | None
    engine: AsrEngine
    model: str


@runtime_checkable
class ASREngine(Protocol):
    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """Transcribe one audio file; raises ``ASRError`` on failure."""
        ...
