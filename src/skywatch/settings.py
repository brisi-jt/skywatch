"""Station configuration.

All configuration flows through the single ``Settings`` class here:

- ``config/config.yaml`` supplies station config (path overridable via the
  ``SKYWATCH_CONFIG`` environment variable; a missing file means defaults).
- Environment variables and a repository-root ``.env`` supply secrets and
  overrides. Nested fields use ``__`` as the delimiter, e.g. ``SERVER__PORT``.

Precedence: explicit constructor arguments, then environment variables, then
``.env``, then the YAML file, then field defaults.
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path("config/config.yaml")


class ReceiverSettings(BaseModel):
    """Where the station physically is; drives flight-data lookups."""

    postcode: str = "SW1A 1AA"
    lat: float | None = None
    lon: float | None = None


class CaptureSettings(BaseModel):
    """SDR capture source and tuning."""

    source: Literal["live", "replay"] = "replay"
    mode: Literal["multichannel", "scan"] = "multichannel"
    # How live capture controls rtl_airband: as its own child process, or by
    # kicking the com.skywatch.rtl-airband launchd service (the deployed
    # topology, where launchd owns the process).
    supervisor: Literal["subprocess", "launchctl"] = "subprocess"
    device_index: int = 0
    # gain, squelch_snr_threshold, and ppm seed the station database on
    # first start; after that the dashboard's tuning page owns them and
    # these values are ignored.
    gain: float = 32.0
    squelch_snr_threshold: float = 12
    ppm: int = 0
    sample_rate_msps: float = 2.56
    output_dir: Path = Path("data/recordings")


class ASRSettings(BaseModel):
    """Speech-to-text engine selection."""

    engine: Literal["faster_whisper", "whisper_cpp"] = "faster_whisper"
    model: str = "base.en"
    compute_type: str = "int8"
    whisper_cpp_binary: Path = Path("whisper-cli")
    whisper_cpp_model: Path | None = None
    # Bias the recogniser towards the spoken forms of nearby aircraft
    # callsigns (from enrichment) when transcribing a clip.
    callsign_boost: bool = True


class LLMSettings(BaseModel):
    """Cloud classifier provider and budget."""

    provider: Literal["gemini", "groq", "ollama", "none"] = "gemini"
    model: str = "gemini-2.5-flash-lite"
    daily_call_cap: int = 900
    fallback: list[Literal["gemini", "groq", "ollama", "none"]] = ["groq", "none"]
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"


class EnrichmentSettings(BaseModel):
    """Flight-data lookups for probable aircraft."""

    provider: Literal["opensky", "none"] = "opensky"
    radius_km: float = 40
    bucket_seconds: int = 30
    daily_credit_cap: int = 3000


class SkySettings(BaseModel):
    """Live 'what's overhead' view: source chain, radius, and guards."""

    radius_nm: float = 25
    opensky_daily_cap: int = 500
    heard_window_hours: int = 12
    airplanes_live_base_url: str = "https://api.airplanes.live"
    adsb_lol_base_url: str = "https://api.adsb.lol"
    adsb_fi_base_url: str = "https://opendata.adsb.fi"


class RetentionSettings(BaseModel):
    """How long routine audio is kept before pruning, and the disk floor."""

    routine_audio_days: int = 14
    min_free_disk_gb: float = 2.0


class ServerSettings(BaseModel):
    """API bind address and the station's local timezone."""

    host: str = "0.0.0.0"
    port: int = 8000
    timezone: str = "Europe/London"
    # The address the dashboard is reachable at from wherever the weekly
    # email or an ntfy push is read (e.g. a Tailscale hostname). Left null,
    # clip links fall back to relative paths, which only resolve when opened
    # from the same device the dashboard runs on.
    public_base_url: str | None = None


class EmailDigestSettings(BaseModel):
    """The weekly summary email: who gets it, and when."""

    enabled: bool = False
    to: list[str] = []
    day: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"] = "sun"
    hour: int = 8


class NtfyDigestSettings(BaseModel):
    """Optional real-time push for interesting clips, via ntfy.sh or self-hosted."""

    enabled: bool = False
    topic: str | None = None
    server: str = "https://ntfy.sh"


class DigestSettings(BaseModel):
    """Outbound notifications: the weekly email and the optional live push."""

    email: EmailDigestSettings = EmailDigestSettings()
    ntfy: NtfyDigestSettings = NtfyDigestSettings()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    data_root: Path = Path("data")

    receiver: ReceiverSettings = ReceiverSettings()
    capture: CaptureSettings = CaptureSettings()
    asr: ASRSettings = ASRSettings()
    llm: LLMSettings = LLMSettings()
    enrichment: EnrichmentSettings = EnrichmentSettings()
    sky: SkySettings = SkySettings()
    retention: RetentionSettings = RetentionSettings()
    server: ServerSettings = ServerSettings()
    digest: DigestSettings = DigestSettings()

    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    opensky_client_id: str | None = None
    opensky_client_secret: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_file = Path(os.environ.get("SKYWATCH_CONFIG", DEFAULT_CONFIG_PATH))
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=yaml_file),
            file_secret_settings,
        )
