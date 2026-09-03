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


class TranscriptSegmentResource(BaseModel):
    """One timed slice of a transcript, for follow-along playback."""

    id: int
    start_s: float = Field(description="Segment start, in seconds from the clip's beginning.")
    end_s: float = Field(description="Segment end, in seconds from the clip's beginning.")
    text: str
    avg_word_prob: float | None = Field(
        description=(
            "Mean per-word probability across the segment; nearer 1.0 is more "
            "confident, and low values deserve a 'rough' caveat. Null when the "
            "engine does not report word-level probabilities."
        )
    )


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
    segments: list[TranscriptSegmentResource] = Field(
        default_factory=list,
        description=(
            "Timed segments in order, for a transcript that follows the audio. "
            "Empty when the engine reported no timings."
        ),
    )
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
    alert_category: str | None = Field(
        default=None,
        description=(
            "A curated 'interesting airframe' category (e.g. Military, Historic) "
            "from the plane-alert database, or null when the aircraft is not listed."
        ),
    )
    registration: str | None = Field(
        default=None, description="Tail number from the aircraft database, when known."
    )
    aircraft_type: str | None = Field(
        default=None,
        description="ICAO type code (e.g. A320) from the aircraft database, when known.",
    )
    operator_name: str | None = Field(
        default=None, description="Operator from the aircraft database, when known."
    )


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


class WaveformResponse(HALModel):
    """A clip's waveform, downsampled for a scrubber."""

    recording_id: int
    peaks: list[float] = Field(
        description=(
            "Normalised amplitudes in [0, 1], one per horizontal bucket, for "
            "drawing a static waveform behind the seek bar. Empty when the "
            "station cannot decode the clip's audio."
        )
    )


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
    deep_tune_active: bool = Field(
        default=False,
        description=(
            "True while a deep tune session has the receiver: capture is "
            "deliberately off-air, not failed."
        ),
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
    timezone: str = Field(
        description=(
            "IANA timezone name the station presents local times in (e.g. "
            "`Europe/London`). The dashboard formats every clock and calendar "
            "day in this zone rather than assuming one."
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


class DigestNarrative(BaseModel):
    """A few plain-English sentences describing a day on the air."""

    text: str = Field(description="The narrative itself: three or four warm sentences.")
    generated_at: datetime = Field(
        description="When this narrative was written (UTC); render an 'as of' time in local zone."
    )
    rolling: bool = Field(
        description=(
            "True when produced by an on-demand 'summarise today so far' refresh "
            "rather than the automatic once-a-day pass — the cue for an 'as of' stamp."
        )
    )


class DigestResponse(HALModel):
    """One local day on the airwaves, summarised."""

    date: date_type
    total_count: int = Field(description="Transmissions recorded during the day.")
    interesting_count: int
    narrative: DigestNarrative | None = Field(
        default=None,
        description=(
            "A written summary of the day, or null when none has been generated "
            "(a quiet day, no classifier configured, or the budget was tight)."
        ),
    )
    interesting: list[RecordingSummary] = Field(
        description="The day's interesting clips, newest first."
    )
    greatest_hits: list[RecordingSummary] = Field(
        description="All-time favourites: the clips with the most thumbs-up."
    )


# -- stats & notable days ------------------------------------------------------------


class DailyMovementCount(BaseModel):
    """Total and interesting transmission counts for one station-local day."""

    date: date_type
    total_count: int
    interesting_count: int


class HourlyHeatCell(BaseModel):
    """A transmission count for one station-local hour on one frequency.

    Only non-zero combinations are included; anything absent is zero.
    """

    hour: int = Field(description="Station-local hour of day, 0-23.")
    freq_id: int
    count: int


class AirlineCount(BaseModel):
    """How often an airline was the top-ranked aircraft match for a clip."""

    airline_name: str
    count: int


class StatsResponse(HALModel):
    """Aggregate numbers over the station's most recent listening window."""

    window_days: int = Field(description="Size of the rolling window these stats cover.")
    days_covered: int = Field(
        description="Distinct station-local days with at least one recording in the window."
    )
    total_count: int = Field(description="Transmissions recorded within the window.")
    interesting_rate: float | None = Field(
        description=(
            "Share of the window's transmissions flagged interesting; null when "
            "the window has no recordings yet."
        )
    )
    go_around_count: int
    daily_counts: list[DailyMovementCount] = Field(
        description="One entry per day in the window, oldest first."
    )
    heat_frequencies: list[FrequencyRef] = Field(
        description="Frequencies that appear in the heat grid, alphabetical by label."
    )
    hourly_heat: list[HourlyHeatCell] = Field(
        description="Non-zero hour-by-frequency cells for the busiest-hour heat grid."
    )
    top_airlines: list[AirlineCount] = Field(
        description="Airlines heard most often, busiest first."
    )


class NotableDay(BaseModel):
    """One station-local day, ranked by how eventful it was."""

    date: date_type
    score: float = Field(
        description=(
            "Weighted interestingness for the day: emergency, guard-frequency "
            "and go-around clips count for more than an ordinary interesting flag."
        )
    )
    interesting_count: int = Field(description="Interesting clips recorded that day.")


class NotableDaysResponse(HALModel):
    """The station's most eventful days on record."""

    items: list[NotableDay] = Field(description="Highest-scoring days first.")


# -- tuning -------------------------------------------------------------------------


class SquelchOverride(BaseModel):
    """A per-frequency squelch threshold that beats the station default."""

    freq_id: int
    label: str
    mhz: float
    squelch_snr_db: float


class AppliedTuning(BaseModel):
    """One complete set of tuning values."""

    gain_db: float = Field(description="RTL-SDR tuner gain; always one of the real gain steps.")
    squelch_default_snr_db: float = Field(
        description=(
            "Station-wide squelch threshold: recording starts when a signal "
            "rises this many dB above the channel's noise floor."
        )
    )
    ppm: int = Field(
        description="Frequency correction for the dongle's crystal offset, in parts per million."
    )
    squelch_overrides: list[SquelchOverride]


class FactoryTuning(BaseModel):
    """The values the station shipped with; the reset of last resort."""

    gain_db: float
    squelch_default_snr_db: float
    ppm: int


class DeepTuneState(BaseModel):
    """Whether an exclusive off-air spectrum session is running."""

    active: bool
    started_at: datetime | None = Field(
        default=None, description="When the session began; null when inactive."
    )
    seconds_remaining_before_timeout: float | None = Field(
        default=None,
        description=(
            "Seconds until the session ends itself for lack of interaction; "
            "null when inactive. Pings reset the countdown."
        ),
    )


class DeepTuneSessionResponse(HALModel):
    """The deep tune session as the start, stop, and ping endpoints report it."""

    deep_tune: DeepTuneState
    center_mhz: float | None = Field(
        default=None,
        description="Centre of the spectrum window being streamed; null when inactive.",
    )
    span_mhz: float | None = Field(
        default=None,
        description="Full width of the spectrum window in MHz; null when inactive.",
    )


class TuningResponse(HALModel):
    """The tuning bench's full state."""

    applied: AppliedTuning = Field(description="The values capture is currently running with.")
    baseline: AppliedTuning | None = Field(
        description=(
            "The saved station defaults that per-lever reset returns to, or "
            "null when none have been saved yet (factory values apply)."
        )
    )
    factory: FactoryTuning
    gain_steps_db: list[float] = Field(
        description=(
            "The tuner's real gain ladder. Gain controls should offer exactly "
            "these values; anything else is snapped to the nearest step."
        )
    )
    last_applied_at: datetime | None = Field(
        description="When tuning values were last applied, or null if never."
    )
    deep_tune: DeepTuneState


class SquelchOverrideRequest(BaseModel):
    freq_id: int
    squelch_snr_db: float


class TuningApplyRequest(BaseModel):
    """A complete set of tuning values — not a delta.

    Send the current value for any lever that is not changing; a
    per-frequency override omitted here is removed.
    """

    gain_db: float
    squelch_default_snr_db: float
    ppm: int
    squelch_overrides: list[SquelchOverrideRequest] = []


class TuningApplyResponse(TuningResponse):
    """The tuning state after an apply, plus how the restart went."""

    capture_restarted: bool
    warnings: list[str] = Field(
        description="Non-fatal notes, e.g. a capture restart that could not complete."
    )


class StatsFileState(BaseModel):
    """Freshness of the capture process's statistics file."""

    present: bool = Field(description="False until capture has written the file at least once.")
    stale: bool = Field(
        description=(
            "True when the file has not been rewritten recently; the numbers "
            "describe a process that is no longer reporting, so meters should "
            "show a paused state."
        )
    )
    updated_at: datetime | None


class SinceLastApply(BaseModel):
    """Activity since the most recent tuning apply, for before/after comparison."""

    applied_at: datetime
    total_clips: int


class ChannelMeter(BaseModel):
    """One frequency's live readings and recent activity."""

    freq_id: int
    label: str
    mhz: float
    signal_dbfs: float | None = Field(
        description="Signal level relative to full scale; null while no stats are available."
    )
    noise_dbfs: float | None
    snr_db: float | None = Field(
        description="Signal above the noise floor — the number squelch compares against."
    )
    squelch_level_dbfs: float | None = Field(
        description="The level at which squelch currently opens on this channel."
    )
    squelch_open_count: int | None = Field(
        description="Times squelch has opened since capture started."
    )
    flappy_count: int | None = Field(
        description=(
            "Times squelch opened and closed in quick succession — a high "
            "count suggests the threshold sits too close to the noise floor."
        )
    )
    clips_last_hour: int
    last_heard_utc: datetime | None
    clips_since_apply: int | None = Field(
        description="Clips recorded since tuning was last applied; null if never applied."
    )


class MetersResponse(HALModel):
    """Live meter readings for every active frequency."""

    stats: StatsFileState
    channels: list[ChannelMeter]
    since_last_apply: SinceLastApply | None


# -- settings & docs ----------------------------------------------------------------


class SettingsResponse(HALModel):
    """The station's owner-editable settings."""

    station_name: str | None
    tuning_walkthrough_done: bool = Field(
        description=(
            "Whether the tuning bench's one-time introductory tour has been completed or dismissed."
        ),
    )
    first_clip_celebrated: bool = Field(
        description=(
            "Whether the once-ever celebration for the station's first captured "
            "clip has already been shown. Set true after it plays so it never "
            "repeats."
        ),
    )
    earcon_enabled: bool = Field(
        description=(
            "Whether a soft chime sounds when an interesting clip is reached in "
            "hands-free playback or arrives live. Off by default; the listener "
            "opts in."
        ),
    )
    watch_phrases: list[str] = Field(
        description=(
            "Phrases that always flag a clip as interesting when heard. "
            "Editable by the owner; seeded with the station's built-in distress "
            "phrases."
        ),
    )


class DocumentResponse(HALModel):
    """A station document as raw Markdown for the client to render."""

    name: str
    markdown: str


# -- feedback eval ------------------------------------------------------------------


class EvalDisagreement(HALModel):
    """One clip where the classifier and the listeners disagreed."""

    recording_id: int
    classified_interesting: bool = Field(description="The classifier's latest verdict.")
    category: ClassificationCategory
    human_interesting: bool = Field(
        description="What the listeners' votes say: more thumbs-up than thumbs-down."
    )
    feedback_up: int
    feedback_down: int
    transcript_snippet: str | None


class EvalFeedbackResponse(HALModel):
    """The classifier measured against listener feedback as ground truth.

    Only clips that have at least one vote and a settled verdict are counted;
    a listener's votes are treated as truth (more up than down = worth
    hearing). Precision and recall are null until there is anything to divide.
    """

    sample_size: int = Field(description="Clips with both feedback and a classification.")
    precision: float | None = Field(
        description="Of the clips the classifier flagged, the share listeners agreed with."
    )
    recall: float | None = Field(
        description="Of the clips listeners liked, the share the classifier flagged."
    )
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    disagreements: list[EvalDisagreement] = Field(
        description="Every clip where the classifier and listeners diverged, newest first."
    )
