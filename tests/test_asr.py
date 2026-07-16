"""ASR provider tests.

faster-whisper is never exercised here (heavy model download); the engine is
constructed lazily so selection can be tested without the package installed.
whisper.cpp is a subprocess wrapper tested through an injected runner.
"""

import json
from pathlib import Path

import pytest

from skywatch.db.enums import AsrEngine
from skywatch.providers.asr import create_asr_engine
from skywatch.providers.asr.base import ASRError
from skywatch.providers.asr.faster_whisper import FasterWhisperEngine
from skywatch.providers.asr.whisper_cpp import WhisperCppEngine
from skywatch.settings import ASRSettings


class TestFactory:
    def test_selects_faster_whisper(self):
        engine = create_asr_engine(ASRSettings(engine="faster_whisper", model="base.en"))
        assert isinstance(engine, FasterWhisperEngine)

    def test_selects_whisper_cpp(self):
        settings = ASRSettings(
            engine="whisper_cpp",
            model="base.en",
            whisper_cpp_binary=Path("/usr/local/bin/whisper-cli"),
            whisper_cpp_model=Path("/models/ggml-base.en.bin"),
        )
        engine = create_asr_engine(settings)
        assert isinstance(engine, WhisperCppEngine)

    def test_whisper_cpp_requires_model_path(self):
        with pytest.raises(ValueError):
            create_asr_engine(ASRSettings(engine="whisper_cpp", whisper_cpp_model=None))

    def test_faster_whisper_construction_is_lazy(self):
        # Constructing the engine must not import faster_whisper or load a model.
        engine = FasterWhisperEngine(model="base.en", compute_type="int8")
        assert engine.model_name == "base.en"


class _FakeCompleted:
    def __init__(self, returncode=0, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = b""


class TestWhisperCpp:
    def _engine(self, tmp_path, *, returncode=0, transcription=None):
        commands = []

        def runner(cmd, **kwargs):
            commands.append(cmd)
            if returncode == 0:
                # whisper-cli writes <output-prefix>.json when asked for JSON.
                prefix = cmd[cmd.index("-of") + 1]
                payload = {
                    "result": {"language": "en"},
                    "transcription": transcription
                    if transcription is not None
                    else [{"text": " Mayday mayday."}, {"text": " Engine failure."}],
                }
                Path(f"{prefix}.json").write_text(json.dumps(payload))
            return _FakeCompleted(returncode=returncode, stderr=b"boom")

        engine = WhisperCppEngine(
            binary=Path("/opt/whisper/whisper-cli"),
            model_path=Path("/models/ggml-base.en.bin"),
            model_name="base.en",
            runner=runner,
        )
        return engine, commands

    def test_transcribes_via_subprocess(self, tmp_path):
        engine, commands = self._engine(tmp_path)
        audio = tmp_path / "clip.mp3"
        audio.write_bytes(b"fake")
        result = engine.transcribe(audio)
        assert result.text == "Mayday mayday. Engine failure."
        assert result.engine is AsrEngine.WHISPER_CPP
        assert result.model == "base.en"
        assert result.language == "en"
        assert result.avg_logprob is None
        (cmd,) = commands
        assert cmd[0] == "/opt/whisper/whisper-cli"
        assert cmd[cmd.index("-m") + 1] == "/models/ggml-base.en.bin"
        assert cmd[cmd.index("-f") + 1] == str(audio)

    def test_nonzero_exit_raises(self, tmp_path):
        engine, _ = self._engine(tmp_path, returncode=1)
        audio = tmp_path / "clip.mp3"
        audio.write_bytes(b"fake")
        with pytest.raises(ASRError):
            engine.transcribe(audio)

    def test_missing_audio_raises(self, tmp_path):
        engine, _ = self._engine(tmp_path)
        with pytest.raises(ASRError):
            engine.transcribe(tmp_path / "absent.mp3")
