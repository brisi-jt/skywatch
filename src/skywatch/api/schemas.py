"""Response and request models for the station API.

Every resource response carries a HAL-style ``_links`` object holding
``self`` plus related resources and the actions currently available on the
resource, so a client can follow the API without building URLs by hand.
Timestamps are UTC ISO 8601 throughout; presentation-timezone rendering is
the client's job.
"""

from datetime import date as date_type
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from skywatch.db.enums import (
    AsrEngine,
    ClassificationCategory,
    ClassificationSource,
    ClassificationStatus,
    FeedbackVerdict,
    FlightDataSource,
    FrequencyCategory,
    FrequencyMode,
    RecordingStage,
)


class Link(BaseModel):
    """One HAL link: a relative URL on this API."""

    href: str


class HALModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    links: dict[str, Link] = Field(
        default_factory=dict,
        alias="_links",
        description=(
            "HAL links: self plus related resources and the actions currently "
            "available on this resource."
        ),
    )


# -- frequencies --------------------------------------------------------------------


class FrequencyResource(HALModel):
    """One entry in the station's frequency plan."""

    id: int
    label: str
    mhz: float
    mode: FrequencyMode
    facility: str
    category: FrequencyCategory
    description: str
    is_active: bool = Field(description="Whether the station currently records this frequency.")
    tuner_group: int
    verified: bool = Field(
        description=(
            "False until the frequency has been checked against a current "
            "official or enthusiast source; unverified rows deserve a "
            "prominent caveat in any UI."
        )
    )


class FrequencyListResponse(HALModel):
    items: list[FrequencyResource]


class FrequencyActionResponse(HALModel):
    """Result of activating or deactivating a frequency."""

    frequency: FrequencyResource
    warnings: list[str] = Field(
        description=(
            "Non-fatal notes about the new plan, e.g. the scan-mode "
            "concurrency trade-off or a capture restart that could not "
            "complete."
        )
    )
    capture_restarted: bool = Field(
        description="Whether the capture process was restarted onto the new plan."
    )


# -- recordings ---------------------------------------------------------------------


class FrequencyRef(BaseModel):
    """Just enough about a frequency to label a clip."""

    id: int
    label: str
    mhz: float


class TranscriptResource(BaseModel):
    """Speech-to-text output with engine provenance."""

    id: int
    engine: AsrEngine
    model: str
    text: str
    avg_logprob: float | None = Field(
        description=(
            "Mean log-probability the recogniser assigned to its own output; "
            "closer to 0 is more confident. Values below about -1 deserve a "
            "'rough transcript' caveat. Null when the engine does not report it."
        )
    )
    language: str | None
    created_at: datetime


class ClassificationResource(BaseModel):
    """One routine/interesting verdict. History is append-only; the newest
    verdict is the one that counts."""

    id: int
    is_interesting: bool
    category: ClassificationCategory
    confidence: float = Field(description="Verdict confidence in [0, 1].")
    reason: str = Field(description="Plain-language explanation of the verdict.")
    source: ClassificationSource
    model: str | None = Field(description="LLM model name when the source is llm.")
    prefilter_flags: list[str] = Field(
        description="Which prefilter rules fired (e.g. keyword:mayday, guard_frequency)."
    )
    status: ClassificationStatus = Field(
        description=(
            "final, or deferred when the daily LLM budget was exhausted and a "
            "fuller verdict will be backfilled after the quota resets."
        )
    )
    created_at: datetime


class AircraftMatchResource(BaseModel):
    """A probable aircraft near the station when the clip was captured.

    Candidates are heuristic: they come from position data around the
    receiver at capture time, not from decoding the transmission. Present
    them as 'probably/possibly', never as fact.
    """

    id: int
    source: FlightDataSource
    icao24: str
    callsign: str | None
    airline_name: str | None
    flight_number_guess: str | None = Field(
        description=(
            "Marketed flight number inferred from the callsign; a guess by "
            "construction, so always phrase it as one."
        )
    )
    lat: float
    lon: float
    alt_ft: float | None
    gs_kt: float | None
    distance_km: float
    match_confidence: float = Field(description="Ranking confidence in [0, 1].")
    rank: int = Field(description="1 is the most plausible candidate.")
    queried_at: datetime


class FeedbackCounts(BaseModel):
    """Thumbs-up / thumbs-down tallies for a clip."""

    up: int
    down: int


class FeedbackResource(HALModel):
    """One listener verdict on a clip."""

    id: int
    recording_id: int
    verdict: FeedbackVerdict
    note: str | None
    created_at: datetime


class RecordingSummary(HALModel):
    """A clip as it appears in lists and cards."""

    id: int
    frequency: FrequencyRef
    started_at_utc: datetime
    ended_at_utc: datetime
    duration_s: float
    stage: RecordingStage
    audio_available: bool = Field(
        description="False once retention has pruned the audio; the row itself is kept."
    )
    transcript_snippet: str | None = Field(
        description="Opening of the latest transcript, or null while transcription is pending."
    )
    classification: ClassificationResource | None = Field(
        description="Latest verdict, or null while classification is pending."
    )
    top_match: AircraftMatchResource | None = Field(
        description="Most plausible aircraft candidate, or null when none was found."
    )
    feedback: FeedbackCounts


class RecordingDetail(RecordingSummary):
    """A clip with its complete provenance."""

    sample_rate: int
    file_path: str = Field(description="Audio location relative to the station's data root.")
    stage_error: str | None = Field(
        description="Most recent pipeline failure for this clip, if any stage struggled."
    )
    audio_deleted_at: datetime | None
    transcript: TranscriptResource | None
    classifications: list[ClassificationResource] = Field(
        description="Full verdict history, newest first."
    )
    matches: list[AircraftMatchResource] = Field(description="All candidates, best first.")
    feedback_entries: list[FeedbackResource]


class RecordingListResponse(HALModel):
    items: list[RecordingSummary]
    total: int = Field(description="Matching clips across all pages.")
    limit: int
    offset: int


class ReclassifyResponse(HALModel):
    """Acknowledgement that a clip was queued for reclassification."""

    recording_id: int
    stage: RecordingStage
    detail: str


class FeedbackCreate(BaseModel):
    """Request body for recording a listener verdict."""

    verdict: FeedbackVerdict
    note: str | None = None


# -- status -------------------------------------------------------------------------


class ConfState(StrEnum):
    """How the rtl_airband config file on disk relates to the database plan."""

    MATCH = "match"
    STALE = "stale"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class CaptureStatus(BaseModel):
    """The capture chain as it is right now."""

    source: str = Field(description="live (real SDR dongle) or replay (fixture playback).")
    mode: str = Field(description="multichannel or scan.")
    running: bool
    detail: str
    paused_for_disk: bool = Field(description="True while the disk-space guard has capture paused.")
    dongle_present: bool | None = Field(
        description="Whether an RTL-SDR device is attached; null when not probed (replay)."
    )
    centerfreq_mhz: float | None = Field(
        description="Tuner centre frequency for the active plan; null in scan mode."
    )


class TraceChannel(BaseModel):
    label: str
    mhz: float


class TraceIntent(BaseModel):
    """What the database says should be captured."""

    mode: str
    channels: list[TraceChannel]


class TraceConf(BaseModel):
    """Whether the rendered config file reflects the database plan."""

    state: ConfState
    path: str | None


class TraceProcess(BaseModel):
    """Whether the capture process is actually running."""

    running: bool
    detail: str


class CaptureTrace(BaseModel):
    """The three-step capture chain: database intent, rendered config file,
    running process. Any mismatch between steps points at where a frequency
    change stalled."""

    db_intent: TraceIntent
    rendered_conf: TraceConf
    process: TraceProcess


class DiskInfo(BaseModel):
    free_gb: float
    total_gb: float
    min_free_gb: float = Field(description="Floor below which capture is paused.")
    low: bool


class BudgetInfo(BaseModel):
    """Today's consumption against one external API's daily budget."""

    provider: str
    calls_today: int
    daily_cap: int
    remaining: int


class StatusBudgets(BaseModel):
    llm: BudgetInfo | None = Field(
        description="Classifier budget; null when classification runs prefilter-only."
    )
    opensky: BudgetInfo | None = Field(
        description="Flight-data credit budget; null when enrichment is disabled."
    )


class StatusResponse(HALModel):
    """Everything the station knows about its own health."""

    station_name: str | None = Field(
        description=(
            "The name the owner gave the station, or null when it has never "
            "been named — the signal to offer a first-run naming dialog."
        )
    )
    capture: CaptureStatus
    trace: CaptureTrace
    queues: dict[str, int] = Field(
        description=(
            "Clips per pipeline stage. The failed_* stages are the needs-attention surface."
        )
    )
    disk: DiskInfo
    budgets: StatusBudgets


# -- digest -------------------------------------------------------------------------


class DigestResponse(HALModel):
    """One local day on the airwaves, summarised."""

    date: date_type
    total_count: int = Field(description="Transmissions recorded during the day.")
    interesting_count: int
    interesting: list[RecordingSummary] = Field(
        description="The day's interesting clips, newest first."
    )
    greatest_hits: list[RecordingSummary] = Field(
        description="All-time favourites: the clips with the most thumbs-up."
    )


# -- settings & docs ----------------------------------------------------------------


class SettingsResponse(HALModel):
    """The station's owner-editable settings."""

    station_name: str | None


class DocumentResponse(HALModel):
    """A station document as raw Markdown for the client to render."""

    name: str
    markdown: str
