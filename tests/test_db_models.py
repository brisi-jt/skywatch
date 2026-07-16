"""Round-trip persistence tests: every field on every model survives
create -> commit -> fresh-session read, with correct Python types."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

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
from skywatch.db.models import (
    AircraftMatch,
    ApiUsage,
    Classification,
    Feedback,
    Frequency,
    Recording,
    Setting,
    Transcript,
)

T0 = datetime(2026, 7, 1, 9, 30, 5, 123456, tzinfo=UTC)
T1 = datetime(2026, 7, 1, 9, 30, 17, 654321, tzinfo=UTC)


def _persist(engine, obj):
    with Session(engine) as s:
        s.add(obj)
        s.commit()
        s.refresh(obj)
        return obj.id if hasattr(obj, "id") else obj.key


def _reload(engine, model, pk):
    with Session(engine) as s:
        row = s.get(model, pk)
        assert row is not None
        return row


def _frequency(**overrides) -> Frequency:
    values = {
        "label": "Stansted Tower",
        "mhz": 123.805,
        "mode": FrequencyMode.AM,
        "facility": "London Stansted",
        "category": FrequencyCategory.TOWER,
        "description": "Aerodrome control for runway operations.",
        "is_active": True,
        "tuner_group": 2,
        "verified": False,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return Frequency(**values)


def _recording(freq_id: int, **overrides) -> Recording:
    values = {
        "freq_id": freq_id,
        "started_at_utc": T0,
        "ended_at_utc": T1,
        "duration_s": 12.53,
        "file_path": "recordings/20260701/SW_20260701_093005_123805000.mp3",
        "sample_rate": 8000,
        "stage": RecordingStage.CAPTURED,
        "stage_error": None,
        "audio_deleted_at": None,
        "created_at": T0,
        "updated_at": T0,
    }
    values.update(overrides)
    return Recording(**values)


def _seed_recording(engine) -> int:
    freq_id = _persist(engine, _frequency())
    return _persist(engine, _recording(freq_id))


def _assert_utc(value: datetime, expected: datetime) -> None:
    assert isinstance(value, datetime)
    assert value.tzinfo is not None
    assert value == expected


def test_frequency_round_trip(engine):
    pk = _persist(engine, _frequency())
    row = _reload(engine, Frequency, pk)

    assert row.id == pk
    assert row.label == "Stansted Tower"
    assert isinstance(row.mhz, float)
    assert row.mhz == 123.805
    assert isinstance(row.mode, FrequencyMode)
    assert row.mode == FrequencyMode.AM
    assert row.facility == "London Stansted"
    assert isinstance(row.category, FrequencyCategory)
    assert row.category == FrequencyCategory.TOWER
    assert row.description == "Aerodrome control for runway operations."
    assert row.is_active is True
    assert isinstance(row.tuner_group, int)
    assert row.tuner_group == 2
    assert row.verified is False
    _assert_utc(row.created_at, T0)
    _assert_utc(row.updated_at, T0)


def test_frequency_label_mhz_unique(engine):
    _persist(engine, _frequency())
    with pytest.raises(IntegrityError), Session(engine) as s:
        s.add(_frequency())
        s.commit()


def test_recording_round_trip(engine):
    freq_id = _persist(engine, _frequency())
    deleted_at = datetime(2026, 7, 15, 3, 0, 0, tzinfo=UTC)
    pk = _persist(
        engine,
        _recording(
            freq_id,
            stage=RecordingStage.FAILED_TRANSCRIBE,
            stage_error="decoder exited with status 1",
            audio_deleted_at=deleted_at,
        ),
    )
    row = _reload(engine, Recording, pk)

    assert row.id == pk
    assert row.freq_id == freq_id
    _assert_utc(row.started_at_utc, T0)
    _assert_utc(row.ended_at_utc, T1)
    assert isinstance(row.duration_s, float)
    assert row.duration_s == 12.53
    assert row.file_path == "recordings/20260701/SW_20260701_093005_123805000.mp3"
    assert isinstance(row.sample_rate, int)
    assert row.sample_rate == 8000
    assert isinstance(row.stage, RecordingStage)
    assert row.stage == RecordingStage.FAILED_TRANSCRIBE
    assert row.stage_error == "decoder exited with status 1"
    _assert_utc(row.audio_deleted_at, deleted_at)
    _assert_utc(row.created_at, T0)
    _assert_utc(row.updated_at, T0)


def test_recording_requires_existing_frequency(engine):
    with pytest.raises(IntegrityError), Session(engine) as s:
        s.add(_recording(freq_id=9999))
        s.commit()


def test_transcript_round_trip(engine):
    recording_id = _seed_recording(engine)
    pk = _persist(
        engine,
        Transcript(
            recording_id=recording_id,
            engine=AsrEngine.FASTER_WHISPER,
            model="base.en",
            text="stansted tower golf bravo alpha ready for departure",
            avg_logprob=-0.2431,
            language="en",
            created_at=T1,
            updated_at=T1,
        ),
    )
    row = _reload(engine, Transcript, pk)

    assert row.id == pk
    assert row.recording_id == recording_id
    assert isinstance(row.engine, AsrEngine)
    assert row.engine == AsrEngine.FASTER_WHISPER
    assert row.model == "base.en"
    assert row.text == "stansted tower golf bravo alpha ready for departure"
    assert isinstance(row.avg_logprob, float)
    assert row.avg_logprob == -0.2431
    assert row.language == "en"
    _assert_utc(row.created_at, T1)
    _assert_utc(row.updated_at, T1)


def test_classification_round_trip(engine):
    recording_id = _seed_recording(engine)
    pk = _persist(
        engine,
        Classification(
            recording_id=recording_id,
            is_interesting=True,
            category=ClassificationCategory.EMERGENCY,
            confidence=0.93,
            reason="Mayday call with souls-on-board count.",
            source=ClassificationSource.LLM,
            model="gemini-2.5-flash-lite",
            prefilter_flags=["keyword:mayday", "guard_frequency"],
            status=ClassificationStatus.FINAL,
            created_at=T1,
            updated_at=T1,
        ),
    )
    row = _reload(engine, Classification, pk)

    assert row.id == pk
    assert row.recording_id == recording_id
    assert row.is_interesting is True
    assert isinstance(row.category, ClassificationCategory)
    assert row.category == ClassificationCategory.EMERGENCY
    assert isinstance(row.confidence, float)
    assert row.confidence == 0.93
    assert row.reason == "Mayday call with souls-on-board count."
    assert isinstance(row.source, ClassificationSource)
    assert row.source == ClassificationSource.LLM
    assert row.model == "gemini-2.5-flash-lite"
    assert isinstance(row.prefilter_flags, list)
    assert row.prefilter_flags == ["keyword:mayday", "guard_frequency"]
    assert isinstance(row.status, ClassificationStatus)
    assert row.status == ClassificationStatus.FINAL
    _assert_utc(row.created_at, T1)
    _assert_utc(row.updated_at, T1)


def test_aircraft_match_round_trip(engine):
    recording_id = _seed_recording(engine)
    queried = datetime(2026, 7, 1, 9, 30, 20, tzinfo=UTC)
    pk = _persist(
        engine,
        AircraftMatch(
            recording_id=recording_id,
            source=FlightDataSource.OPENSKY,
            icao24="4009f9",
            callsign="RYR51LM",
            airline_name="Ryanair",
            flight_number_guess="FR1884",
            lat=51.8863,
            lon=0.2389,
            alt_ft=2350.0,
            gs_kt=161.5,
            distance_km=18.4,
            match_confidence=0.71,
            rank=1,
            queried_at=queried,
            created_at=T1,
            updated_at=T1,
        ),
    )
    row = _reload(engine, AircraftMatch, pk)

    assert row.id == pk
    assert row.recording_id == recording_id
    assert isinstance(row.source, FlightDataSource)
    assert row.source == FlightDataSource.OPENSKY
    assert row.icao24 == "4009f9"
    assert row.callsign == "RYR51LM"
    assert row.airline_name == "Ryanair"
    assert row.flight_number_guess == "FR1884"
    assert isinstance(row.lat, float)
    assert row.lat == 51.8863
    assert isinstance(row.lon, float)
    assert row.lon == 0.2389
    assert isinstance(row.alt_ft, float)
    assert row.alt_ft == 2350.0
    assert isinstance(row.gs_kt, float)
    assert row.gs_kt == 161.5
    assert isinstance(row.distance_km, float)
    assert row.distance_km == 18.4
    assert isinstance(row.match_confidence, float)
    assert row.match_confidence == 0.71
    assert isinstance(row.rank, int)
    assert row.rank == 1
    _assert_utc(row.queried_at, queried)
    _assert_utc(row.created_at, T1)
    _assert_utc(row.updated_at, T1)


def test_aircraft_match_nullables_round_trip_as_none(engine):
    recording_id = _seed_recording(engine)
    pk = _persist(
        engine,
        AircraftMatch(
            recording_id=recording_id,
            source=FlightDataSource.OPENSKY,
            icao24="4ca4e8",
            callsign=None,
            airline_name=None,
            flight_number_guess=None,
            lat=51.70,
            lon=0.10,
            alt_ft=None,
            gs_kt=None,
            distance_km=2.2,
            match_confidence=0.35,
            rank=3,
            queried_at=T1,
            created_at=T1,
            updated_at=T1,
        ),
    )
    row = _reload(engine, AircraftMatch, pk)
    assert row.callsign is None
    assert row.airline_name is None
    assert row.flight_number_guess is None
    assert row.alt_ft is None
    assert row.gs_kt is None


def test_feedback_round_trip(engine):
    recording_id = _seed_recording(engine)
    pk = _persist(
        engine,
        Feedback(
            recording_id=recording_id,
            verdict=FeedbackVerdict.UP,
            note="Genuinely interesting go-around.",
            created_at=T1,
            updated_at=T1,
        ),
    )
    row = _reload(engine, Feedback, pk)

    assert row.id == pk
    assert row.recording_id == recording_id
    assert isinstance(row.verdict, FeedbackVerdict)
    assert row.verdict == FeedbackVerdict.UP
    assert row.note == "Genuinely interesting go-around."
    _assert_utc(row.created_at, T1)
    _assert_utc(row.updated_at, T1)


def test_api_usage_round_trip(engine):
    pk = _persist(
        engine,
        ApiUsage(
            provider=ApiProvider.OPENSKY,
            day=date(2026, 7, 1),
            calls=42,
            tokens=None,
            created_at=T0,
            updated_at=T1,
        ),
    )
    row = _reload(engine, ApiUsage, pk)

    assert row.id == pk
    assert isinstance(row.provider, ApiProvider)
    assert row.provider == ApiProvider.OPENSKY
    assert isinstance(row.day, date)
    assert row.day == date(2026, 7, 1)
    assert isinstance(row.calls, int)
    assert row.calls == 42
    assert row.tokens is None
    _assert_utc(row.created_at, T0)
    _assert_utc(row.updated_at, T1)


def test_api_usage_tokens_round_trip(engine):
    pk = _persist(
        engine,
        ApiUsage(
            provider=ApiProvider.GEMINI,
            day=date(2026, 7, 1),
            calls=7,
            tokens=15321,
            created_at=T0,
            updated_at=T0,
        ),
    )
    row = _reload(engine, ApiUsage, pk)
    assert isinstance(row.tokens, int)
    assert row.tokens == 15321


def test_api_usage_provider_day_unique(engine):
    _persist(
        engine,
        ApiUsage(provider=ApiProvider.GROQ, day=date(2026, 7, 2), calls=1, created_at=T0),
    )
    with pytest.raises(IntegrityError), Session(engine) as s:
        s.add(ApiUsage(provider=ApiProvider.GROQ, day=date(2026, 7, 2), calls=9, created_at=T0))
        s.commit()


def test_setting_round_trip(engine):
    _persist(
        engine,
        Setting(key="station_name", value="Dad's Tower", created_at=T0, updated_at=T1),
    )
    row = _reload(engine, Setting, "station_name")

    assert row.key == "station_name"
    assert row.value == "Dad's Tower"
    _assert_utc(row.created_at, T0)
    _assert_utc(row.updated_at, T1)
