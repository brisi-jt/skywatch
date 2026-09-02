"""The contract every speech-to-text engine honours."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from skywatch.db.enums import AsrEngine


class ASRError(RuntimeError):
    """Transcription failed; the clip can be retried later."""


@dataclass(frozen=True)
class TranscriptionSegment:
    """One timed slice of a transcript.

    ``avg_word_prob`` is the mean per-word probability across the segment
    (nearer 1.0 is more confident); it is null when the engine does not
    report word-level probabilities.
    """

    start_s: float
    end_s: float
    text: str
    avg_word_prob: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    """One clip's transcript with full engine provenance."""

    text: str
    avg_logprob: float | None
    language: str | None
    engine: AsrEngine
    model: str
    segments: tuple[TranscriptionSegment, ...] = field(default_factory=tuple)


@runtime_checkable
class ASREngine(Protocol):
    def transcribe(
        self,
        audio_path: Path,
        *,
        hotwords: Sequence[str] | None = None,
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe one audio file; raises ``ASRError`` on failure.

        ``hotwords`` and ``initial_prompt`` bias the recogniser towards
        expected terms (e.g. spoken callsigns). Engines that cannot use them
        accept and ignore them.
        """
        ...
