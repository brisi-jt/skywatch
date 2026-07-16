"""faster-whisper engine (CTranslate2 backend).

The heavy import and model load happen on first transcription, never at
construction — the worker can be built (and tested) on machines without the
``asr`` extra installed.
"""

import logging
from pathlib import Path

from skywatch.db.enums import AsrEngine
from skywatch.providers.asr.base import ASRError, TranscriptionResult

logger = logging.getLogger(__name__)


class FasterWhisperEngine:
    def __init__(self, model: str = "base.en", compute_type: str = "int8") -> None:
        self.model_name = model
        self.compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:  # pragma: no cover - environment-dependent
                raise ASRError(
                    "faster-whisper is not installed; install the 'asr' extra or "
                    "switch asr.engine to whisper_cpp"
                ) from exc
            logger.info("loading faster-whisper model %s (%s)", self.model_name, self.compute_type)
            self._model = WhisperModel(self.model_name, compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
        if not Path(audio_path).is_file():
            raise ASRError(f"audio file missing: {audio_path}")
        model = self._load()
        try:
            segments, info = model.transcribe(str(audio_path))
            segment_list = list(segments)
        except Exception as exc:
            raise ASRError(f"faster-whisper failed on {audio_path}: {exc}") from exc
        text = " ".join(segment.text.strip() for segment in segment_list).strip()
        logprobs = [s.avg_logprob for s in segment_list if s.avg_logprob is not None]
        avg_logprob = sum(logprobs) / len(logprobs) if logprobs else None
        return TranscriptionResult(
            text=text,
            avg_logprob=avg_logprob,
            language=getattr(info, "language", None),
            engine=AsrEngine.FASTER_WHISPER,
            model=self.model_name,
        )
