"""Speech-to-text engines, selected via the ``asr.engine`` setting."""

from skywatch.providers.asr.base import ASREngine, ASRError, TranscriptionResult
from skywatch.providers.asr.faster_whisper import FasterWhisperEngine
from skywatch.providers.asr.whisper_cpp import WhisperCppEngine
from skywatch.settings import ASRSettings

__all__ = [
    "ASREngine",
    "ASRError",
    "FasterWhisperEngine",
    "TranscriptionResult",
    "WhisperCppEngine",
    "create_asr_engine",
]


def create_asr_engine(settings: ASRSettings) -> ASREngine:
    if settings.engine == "whisper_cpp":
        if settings.whisper_cpp_model is None:
            raise ValueError(
                "asr.whisper_cpp_model must point at a ggml model file when "
                "asr.engine is whisper_cpp"
            )
        return WhisperCppEngine(
            binary=settings.whisper_cpp_binary,
            model_path=settings.whisper_cpp_model,
            model_name=settings.model,
        )
    return FasterWhisperEngine(model=settings.model, compute_type=settings.compute_type)
