from pathlib import Path

from skywatch.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = REPO_ROOT / "config" / "config.yaml.example"


def test_example_config_loads_with_documented_values(monkeypatch):
    monkeypatch.setenv("SKYWATCH_CONFIG", str(EXAMPLE_CONFIG))
    settings = Settings()

    assert settings.data_root == Path("data")

    assert settings.receiver.postcode == "SW1A 1AA"
    assert settings.receiver.lat is None
    assert settings.receiver.lon is None

    assert settings.capture.source == "replay"
    assert settings.capture.mode == "multichannel"
    assert settings.capture.device_index == 0
    assert settings.capture.gain == 32.0
    assert settings.capture.squelch_snr_threshold == 12
    assert settings.capture.sample_rate_msps == 2.56
    assert settings.capture.output_dir == Path("data/recordings")

    assert settings.asr.engine == "faster_whisper"
    assert settings.asr.model == "base.en"
    assert settings.asr.compute_type == "int8"

    assert settings.llm.provider == "gemini"
    assert settings.llm.model == "gemini-2.5-flash-lite"
    assert settings.llm.daily_call_cap == 900
    assert settings.llm.fallback == ["groq", "none"]

    assert settings.enrichment.provider == "opensky"
    assert settings.enrichment.radius_km == 40
    assert settings.enrichment.bucket_seconds == 30
    assert settings.enrichment.daily_credit_cap == 3000

    assert settings.retention.routine_audio_days == 14

    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 8000


def test_missing_config_file_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "does-not-exist.yaml"))
    settings = Settings()

    assert settings.capture.source == "replay"
    assert settings.llm.provider == "gemini"
    assert settings.server.port == 8000


def test_environment_overrides_yaml(monkeypatch):
    monkeypatch.setenv("SKYWATCH_CONFIG", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("CAPTURE__GAIN", "49.6")
    monkeypatch.setenv("SERVER__PORT", "9000")

    settings = Settings()

    assert settings.capture.gain == 49.6
    assert settings.server.port == 9000


def test_secrets_load_from_environment(monkeypatch):
    monkeypatch.setenv("SKYWATCH_CONFIG", str(EXAMPLE_CONFIG))
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("OPENSKY_CLIENT_ID", "test-client")

    settings = Settings()

    assert settings.gemini_api_key == "test-gemini-key"
    assert settings.opensky_client_id == "test-client"
    assert settings.groq_api_key is None
    assert settings.opensky_client_secret is None
