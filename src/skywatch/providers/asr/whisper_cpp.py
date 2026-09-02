"""whisper.cpp engine: wraps the whisper-cli binary as a subprocess.

The fallback for machines where the ctranslate2 wheel is unavailable; the
binary and ggml model paths come from settings. Output is requested as JSON
so the transcript parse does not depend on the CLI's plain-text layout.
"""

import json
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path

from skywatch.db.enums import AsrEngine
from skywatch.providers.asr.base import ASRError, TranscriptionResult, TranscriptionSegment


def _segment_from_json(seg: dict) -> TranscriptionSegment | None:
    """Build a timed segment from a whisper.cpp JSON entry, when it has offsets.

    whisper.cpp reports millisecond offsets but no word-level probabilities,
    so ``avg_word_prob`` is always null here.
    """
    offsets = seg.get("offsets") or {}
    start_ms, end_ms = offsets.get("from"), offsets.get("to")
    if start_ms is None or end_ms is None:
        return None
    return TranscriptionSegment(
        start_s=start_ms / 1000.0,
        end_s=end_ms / 1000.0,
        text=seg.get("text", "").strip(),
        avg_word_prob=None,
    )


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, check=False, **kwargs)


class WhisperCppEngine:
    def __init__(
        self,
        binary: Path,
        model_path: Path,
        *,
        model_name: str | None = None,
        runner=_run,
    ) -> None:
        self._binary = Path(binary)
        self._model_path = Path(model_path)
        self.model_name = model_name or self._model_path.stem
        self._runner = runner

    def transcribe(
        self,
        audio_path: Path,
        *,
        hotwords: Sequence[str] | None = None,
        initial_prompt: str | None = None,
    ) -> TranscriptionResult:
        # whisper.cpp has no hotword biasing here; accept and ignore so the
        # calling stage need not special-case the engine.
        audio_path = Path(audio_path)
        if not audio_path.is_file():
            raise ASRError(f"audio file missing: {audio_path}")
        with tempfile.TemporaryDirectory(prefix="skywatch-whispercpp-") as tmp:
            prefix = str(Path(tmp) / "transcript")
            cmd = [
                str(self._binary),
                "-m",
                str(self._model_path),
                "-f",
                str(audio_path),
                "--output-json",
                "-of",
                prefix,
                "--no-prints",
            ]
            result = self._runner(cmd)
            if result.returncode != 0:
                stderr = (result.stderr or b"").decode(errors="replace").strip()
                raise ASRError(f"whisper.cpp exited {result.returncode}: {stderr[:500]}")
            output = Path(f"{prefix}.json")
            try:
                payload = json.loads(output.read_text())
            except (OSError, ValueError) as exc:
                raise ASRError(f"whisper.cpp produced no parseable output: {exc}") from exc
        segments = payload.get("transcription", [])
        text = " ".join(seg.get("text", "").strip() for seg in segments).strip()
        language = (payload.get("result") or {}).get("language")
        timed = tuple(filter(None, (_segment_from_json(seg) for seg in segments)))
        return TranscriptionResult(
            text=text,
            avg_logprob=None,  # whisper.cpp does not report segment log-probabilities
            language=language,
            engine=AsrEngine.WHISPER_CPP,
            model=self.model_name,
            segments=timed,
        )
