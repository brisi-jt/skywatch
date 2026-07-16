"""whisper.cpp engine: wraps the whisper-cli binary as a subprocess.

The fallback for machines where the ctranslate2 wheel is unavailable; the
binary and ggml model paths come from settings. Output is requested as JSON
so the transcript parse does not depend on the CLI's plain-text layout.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from skywatch.db.enums import AsrEngine
from skywatch.providers.asr.base import ASRError, TranscriptionResult


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

    def transcribe(self, audio_path: Path) -> TranscriptionResult:
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
        return TranscriptionResult(
            text=text,
            avg_logprob=None,  # whisper.cpp does not report segment log-probabilities
            language=language,
            engine=AsrEngine.WHISPER_CPP,
            model=self.model_name,
        )
