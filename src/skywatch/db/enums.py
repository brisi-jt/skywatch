"""Enumerations for every status-like database column.

All values are lowercase strings so they read naturally in raw SQL and API
payloads; the members are the only way code should reference them.
"""

from enum import StrEnum


class FrequencyMode(StrEnum):
    """Demodulation mode for a monitored frequency."""

    AM = "am"


class FrequencyCategory(StrEnum):
    """What kind of aviation service a frequency carries."""

    GUARD = "guard"
    TOWER = "tower"
    GROUND = "ground"
    APPROACH = "approach"
    RADAR = "radar"
    ATIS = "atis"
    AREA_CONTROL = "area_control"
    AIRFIELD = "airfield"


class RecordingStage(StrEnum):
    """Lifecycle position of a captured clip in the processing pipeline.

    Enrichment failures are recorded but never block transcription or
    classification; the failed_* stages mark where a clip needs attention.
    """

    CAPTURED = "captured"
    ENRICHING = "enriching"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    FAILED_ENRICH = "failed_enrich"
    FAILED_TRANSCRIBE = "failed_transcribe"
    FAILED_CLASSIFY = "failed_classify"


class AsrEngine(StrEnum):
    """Speech-to-text engine that produced a transcript."""

    FASTER_WHISPER = "faster_whisper"
    WHISPER_CPP = "whisper_cpp"


class ClassificationCategory(StrEnum):
    """Why a clip is (or is not) interesting."""

    ROUTINE = "routine"
    EMERGENCY = "emergency"
    URGENCY = "urgency"
    GO_AROUND = "go_around"
    MEDICAL = "medical"
    FUEL = "fuel"
    GUARD_ACTIVITY = "guard_activity"
    UNUSUAL = "unusual"
    OTHER = "other"


class ClassificationSource(StrEnum):
    """Which layer produced a classification verdict."""

    PREFILTER = "prefilter"
    LLM = "llm"


class ClassificationStatus(StrEnum):
    """Whether a verdict is settled or awaiting an LLM pass after quota reset."""

    FINAL = "final"
    DEFERRED = "deferred"


class FeedbackVerdict(StrEnum):
    """Listener thumbs-up / thumbs-down on a clip."""

    UP = "up"
    DOWN = "down"


class FlightDataSource(StrEnum):
    """Where an aircraft match came from."""

    OPENSKY = "opensky"


class ApiProvider(StrEnum):
    """External API whose usage is metered against a daily budget."""

    GEMINI = "gemini"
    GROQ = "groq"
    OLLAMA = "ollama"
    OPENSKY = "opensky"
