"""Database schema.

Conventions:

- Every table carries ``created_at`` / ``updated_at`` in UTC.
- All timestamps are stored as UTC and come back timezone-aware
  (see ``UTCDateTime``).
- Status-like columns use the ``StrEnum`` types from ``enums.py`` and are
  persisted by value.
- ``recordings.file_path`` (and every other audio path) is relative to the
  station's data root, so the data directory can move without a migration.
"""

from datetime import UTC, date, datetime
from enum import Enum

from sqlalchemy import JSON, Column, DateTime, TypeDecorator, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

from skywatch.db.enums import (
    ApiProvider,
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


def utcnow() -> datetime:
    """Timezone-aware current UTC time; the only clock the schema uses."""
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Stores timezone-aware datetimes as naive UTC and restores tzinfo on read.

    SQLite keeps datetimes as strings without an offset; this keeps every
    value UTC on disk and timezone-aware in Python, so round trips are exact.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; timestamps must be timezone-aware UTC")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def _str_enum(enum_cls: type[Enum]) -> SAEnum:
    """Column type persisting a ``StrEnum`` by value, with bind validation."""
    return SAEnum(
        enum_cls,
        values_callable=lambda cls: [member.value for member in cls],
        native_enum=False,
        validate_strings=True,
    )


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utcnow, sa_type=UTCDateTime, nullable=False)
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=UTCDateTime,
        nullable=False,
        sa_column_kwargs={"onupdate": utcnow},
    )


class Frequency(TimestampMixin, table=True):
    """A monitored (or monitorable) airband frequency; the frequency plan."""

    __tablename__ = "frequencies"
    __table_args__ = (UniqueConstraint("label", "mhz", name="uq_frequencies_label_mhz"),)

    id: int | None = Field(default=None, primary_key=True)
    label: str = Field(index=True)
    mhz: float
    mode: FrequencyMode = Field(default=FrequencyMode.AM, sa_type=_str_enum(FrequencyMode))
    facility: str
    category: FrequencyCategory = Field(sa_type=_str_enum(FrequencyCategory))
    description: str = ""
    is_active: bool = Field(default=False)
    tuner_group: int
    verified: bool = Field(default=False)


class Recording(TimestampMixin, table=True):
    """One squelch-delimited audio clip and its pipeline state."""

    __tablename__ = "recordings"

    id: int | None = Field(default=None, primary_key=True)
    freq_id: int = Field(foreign_key="frequencies.id", index=True)
    started_at_utc: datetime = Field(sa_type=UTCDateTime, index=True)
    ended_at_utc: datetime = Field(sa_type=UTCDateTime)
    duration_s: float
    file_path: str
    sample_rate: int
    stage: RecordingStage = Field(
        default=RecordingStage.CAPTURED, sa_type=_str_enum(RecordingStage), index=True
    )
    stage_error: str | None = None
    audio_deleted_at: datetime | None = Field(default=None, sa_type=UTCDateTime, nullable=True)


class Transcript(TimestampMixin, table=True):
    """Speech-to-text output for a recording, with engine provenance."""

    __tablename__ = "transcripts"

    id: int | None = Field(default=None, primary_key=True)
    recording_id: int = Field(foreign_key="recordings.id", index=True)
    engine: AsrEngine = Field(sa_type=_str_enum(AsrEngine))
    model: str
    text: str
    avg_logprob: float | None = None
    language: str | None = None


class Classification(TimestampMixin, table=True):
    """A routine/interesting verdict for a recording.

    Reclassification appends a new row; the latest row wins and history stays.
    """

    __tablename__ = "classifications"

    id: int | None = Field(default=None, primary_key=True)
    recording_id: int = Field(foreign_key="recordings.id", index=True)
    is_interesting: bool
    category: ClassificationCategory = Field(sa_type=_str_enum(ClassificationCategory))
    confidence: float
    reason: str
    source: ClassificationSource = Field(sa_type=_str_enum(ClassificationSource))
    model: str | None = None
    prefilter_flags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    status: ClassificationStatus = Field(sa_type=_str_enum(ClassificationStatus))


class AircraftMatch(TimestampMixin, table=True):
    """A probable aircraft for a recording, ranked by plausibility."""

    __tablename__ = "aircraft_matches"

    id: int | None = Field(default=None, primary_key=True)
    recording_id: int = Field(foreign_key="recordings.id", index=True)
    source: FlightDataSource = Field(sa_type=_str_enum(FlightDataSource))
    icao24: str
    callsign: str | None = None
    airline_name: str | None = None
    flight_number_guess: str | None = None
    lat: float
    lon: float
    alt_ft: float | None = None
    gs_kt: float | None = None
    distance_km: float
    match_confidence: float
    rank: int
    queried_at: datetime = Field(sa_type=UTCDateTime)


class Feedback(TimestampMixin, table=True):
    """Listener verdict on whether a clip was worth surfacing."""

    __tablename__ = "feedback"

    id: int | None = Field(default=None, primary_key=True)
    recording_id: int = Field(foreign_key="recordings.id", index=True)
    verdict: FeedbackVerdict = Field(sa_type=_str_enum(FeedbackVerdict))
    note: str | None = None


class ApiUsage(TimestampMixin, table=True):
    """Per-provider, per-day call and token accounting for budget guards."""

    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("provider", "day", name="uq_api_usage_provider_day"),)

    id: int | None = Field(default=None, primary_key=True)
    provider: ApiProvider = Field(sa_type=_str_enum(ApiProvider))
    day: date
    calls: int = 0
    tokens: int | None = None


class Setting(TimestampMixin, table=True):
    """Dashboard-writable station settings as a key/value store."""

    __tablename__ = "settings"

    key: str = Field(primary_key=True)
    value: str
