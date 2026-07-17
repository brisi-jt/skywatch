"""Tuning bench views and actions.

Value logic lives in :mod:`skywatch.tuning` (shared with the worker); this
module shapes it for the API — validation into problem details, HAL links,
and the meters view that merges the rtl_airband statistics file with
recording activity.
"""

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlmodel import Session, select
from starlette import status

from skywatch.api.errors import APIErrorCode, ProblemException
from skywatch.api.schemas import (
    AppliedTuning,
    ChannelMeter,
    DeepTuneSessionResponse,
    DeepTuneState,
    FactoryTuning,
    Link,
    MetersResponse,
    SinceLastApply,
    SquelchOverride,
    StatsFileState,
    TuningApplyRequest,
    TuningApplyResponse,
    TuningResponse,
)
from skywatch.api.services.capture import CaptureController
from skywatch.api.services.deep_tune import (
    DeepTuneActive,
    DeepTuneChannel,
    DeepTuneConfig,
    DeepTuneManager,
    DeepTuneNotActive,
)
from skywatch.capture.stats import default_stats_path, read_stats
from skywatch.capture.validate import validate_frequencies
from skywatch.db.models import Frequency, Recording, utcnow
from skywatch.settings import Settings
from skywatch.tuning import (
    FACTORY_GAIN_DB,
    FACTORY_PPM,
    FACTORY_SQUELCH_SNR_DB,
    R820T_GAIN_STEPS_DB,
    TuningService,
    TuningValues,
    snap_gain_db,
)

SQUELCH_MIN_SNR_DB = 0.0
SQUELCH_MAX_SNR_DB = 50.0
PPM_LIMIT = 200

_LINKS = {
    "self": Link(href="/tuning"),
    "apply": Link(href="/tuning/apply"),
    "baseline": Link(href="/tuning/baseline"),
    "meters": Link(href="/tuning/meters"),
}


def _invalid(detail: str, **extensions) -> ProblemException:
    return ProblemException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        APIErrorCode.TUNING_INVALID_VALUE,
        detail,
        extensions=extensions or None,
    )


def _override_resources(session: Session, overrides: dict[int, float]) -> list[SquelchOverride]:
    resources = []
    for freq_id in sorted(overrides):
        freq = session.get(Frequency, freq_id)
        if freq is None:
            # the frequency has left the plan since the override was stored
            continue
        resources.append(
            SquelchOverride(
                freq_id=freq_id,
                label=freq.label,
                mhz=freq.mhz,
                squelch_snr_db=overrides[freq_id],
            )
        )
    return resources


def _applied_model(session: Session, values: TuningValues) -> AppliedTuning:
    return AppliedTuning(
        gain_db=values.gain_db,
        squelch_default_snr_db=values.squelch_default_snr_db,
        ppm=values.ppm,
        squelch_overrides=_override_resources(session, values.squelch_overrides),
    )


def _deep_tune_state(deep_tune: DeepTuneManager | None) -> DeepTuneState:
    if deep_tune is None:
        return DeepTuneState(active=False)
    status_ = deep_tune.state()
    return DeepTuneState(
        active=status_.active,
        started_at=status_.started_at,
        seconds_remaining_before_timeout=status_.seconds_remaining_before_timeout,
    )


def tuning_view(
    session: Session, settings: Settings, *, deep_tune: DeepTuneManager | None = None
) -> TuningResponse:
    service = TuningService(settings.capture)
    baseline = service.baseline(session)
    return TuningResponse(
        applied=_applied_model(session, service.current(session)),
        baseline=_applied_model(session, baseline) if baseline is not None else None,
        factory=FactoryTuning(
            gain_db=FACTORY_GAIN_DB,
            squelch_default_snr_db=FACTORY_SQUELCH_SNR_DB,
            ppm=FACTORY_PPM,
        ),
        gain_steps_db=list(R820T_GAIN_STEPS_DB),
        last_applied_at=service.last_applied_at(session),
        deep_tune=_deep_tune_state(deep_tune),
        links=_LINKS,
    )


def _validate_apply(session: Session, payload: TuningApplyRequest) -> None:
    if not R820T_GAIN_STEPS_DB[0] <= payload.gain_db <= R820T_GAIN_STEPS_DB[-1]:
        raise _invalid(
            f"gain must be between {R820T_GAIN_STEPS_DB[0]} and {R820T_GAIN_STEPS_DB[-1]} dB",
            field="gain_db",
        )
    if not SQUELCH_MIN_SNR_DB <= payload.squelch_default_snr_db <= SQUELCH_MAX_SNR_DB:
        raise _invalid(
            f"squelch threshold must be between {SQUELCH_MIN_SNR_DB:g} and "
            f"{SQUELCH_MAX_SNR_DB:g} dB",
            field="squelch_default_snr_db",
        )
    if abs(payload.ppm) > PPM_LIMIT:
        raise _invalid(
            f"frequency correction must be between -{PPM_LIMIT} and {PPM_LIMIT} ppm",
            field="ppm",
        )
    seen: set[int] = set()
    for override in payload.squelch_overrides:
        if override.freq_id in seen:
            raise _invalid(
                f"frequency {override.freq_id} appears more than once in squelch_overrides",
                freq_id=override.freq_id,
            )
        seen.add(override.freq_id)
        if not SQUELCH_MIN_SNR_DB <= override.squelch_snr_db <= SQUELCH_MAX_SNR_DB:
            raise _invalid(
                f"squelch threshold must be between {SQUELCH_MIN_SNR_DB:g} and "
                f"{SQUELCH_MAX_SNR_DB:g} dB",
                freq_id=override.freq_id,
            )
        freq = session.get(Frequency, override.freq_id)
        if freq is None:
            raise ProblemException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                APIErrorCode.TUNING_UNKNOWN_FREQUENCY,
                f"no frequency with id {override.freq_id} in the plan",
                extensions={"freq_id": override.freq_id},
            )
        if not freq.is_active:
            raise _invalid(
                f"{freq.label} is not being recorded; squelch overrides apply "
                "to active frequencies only",
                freq_id=override.freq_id,
            )


def apply_tuning(
    session: Session,
    payload: TuningApplyRequest,
    *,
    settings: Settings,
    capture: CaptureController,
    deep_tune: DeepTuneManager | None = None,
) -> TuningApplyResponse:
    if deep_tune is not None and deep_tune.active:
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.DEEP_TUNE_ACTIVE,
            "a deep tune session has the receiver; exit deep tune before applying tuning changes",
        )
    _validate_apply(session, payload)
    service = TuningService(settings.capture)
    values = TuningValues(
        gain_db=snap_gain_db(payload.gain_db),
        squelch_default_snr_db=payload.squelch_default_snr_db,
        ppm=payload.ppm,
        squelch_overrides={
            override.freq_id: override.squelch_snr_db for override in payload.squelch_overrides
        },
    )
    service.store(session, values, applied_at=utcnow())

    has_active = session.exec(select(Frequency).where(Frequency.is_active)).first() is not None
    restarted, warning = capture.restart(has_active=has_active)

    view = tuning_view(session, settings, deep_tune=deep_tune)
    return TuningApplyResponse(
        **view.model_dump(),
        capture_restarted=restarted,
        warnings=[warning] if warning else [],
    )


def save_baseline(
    session: Session, settings: Settings, *, deep_tune: DeepTuneManager | None = None
) -> TuningResponse:
    service = TuningService(settings.capture)
    service.save_baseline(session, service.current(session))
    return tuning_view(session, settings, deep_tune=deep_tune)


# -- deep tune sessions --------------------------------------------------------------


def _deep_tune_links(active: bool) -> dict[str, Link]:
    links = {"tuning": Link(href="/tuning"), "stream": Link(href="/stream")}
    if active:
        links["stop"] = Link(href="/tuning/deep-tune/stop")
        links["ping"] = Link(href="/tuning/deep-tune/ping")
    else:
        links["start"] = Link(href="/tuning/deep-tune/start")
    return links


def _deep_tune_response(deep_tune: DeepTuneManager) -> DeepTuneSessionResponse:
    status_ = deep_tune.state()
    return DeepTuneSessionResponse(
        deep_tune=_deep_tune_state(deep_tune),
        center_mhz=status_.center_mhz,
        span_mhz=status_.span_mhz,
        links=_deep_tune_links(status_.active),
    )


def _unavailable(detail: str) -> ProblemException:
    return ProblemException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        APIErrorCode.DEEP_TUNE_UNAVAILABLE,
        detail,
    )


def start_deep_tune(
    session: Session, *, settings: Settings, deep_tune: DeepTuneManager
) -> DeepTuneSessionResponse:
    if settings.capture.source != "live":
        raise _unavailable(
            "this station is replaying fixture recordings rather than listening "
            "with a receiver, so there is no live spectrum to tune"
        )
    reason = deep_tune.availability()
    if reason is not None:
        raise _unavailable(reason)
    active = session.exec(
        select(Frequency).where(Frequency.is_active).order_by(Frequency.mhz)  # type: ignore[arg-type]
    ).all()
    if not active:
        raise _unavailable(
            "no active frequencies: activate at least one channel so the "
            "spectrum view has something to centre on"
        )
    # centre one tuner window over the active plan; in scan mode (or an
    # over-wide plan) this covers the largest fitting group and any channel
    # outside the window simply reads no power
    center_mhz = validate_frequencies(active, "multichannel").suggested_centerfreq_mhz
    values = TuningService(settings.capture).current(session)
    config = DeepTuneConfig(
        center_mhz=center_mhz,
        sample_rate_msps=settings.capture.sample_rate_msps,
        device_index=settings.capture.device_index,
        gain_db=values.gain_db,
        ppm=values.ppm,
        channels=[DeepTuneChannel(freq_id=f.id, label=f.label, mhz=f.mhz) for f in active],
    )
    try:
        deep_tune.start(config)
    except DeepTuneActive:
        raise _already_active() from None
    return _deep_tune_response(deep_tune)


def _already_active() -> ProblemException:
    return ProblemException(
        status.HTTP_409_CONFLICT,
        APIErrorCode.DEEP_TUNE_ACTIVE,
        "a deep tune session is already running; stop it before starting another",
    )


def stop_deep_tune(deep_tune: DeepTuneManager) -> DeepTuneSessionResponse:
    try:
        deep_tune.stop()
    except DeepTuneNotActive:
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.DEEP_TUNE_NOT_ACTIVE,
            "no deep tune session is running",
        ) from None
    return _deep_tune_response(deep_tune)


def ping_deep_tune(deep_tune: DeepTuneManager) -> DeepTuneSessionResponse:
    try:
        deep_tune.ping()
    except DeepTuneNotActive:
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.DEEP_TUNE_NOT_ACTIVE,
            "no deep tune session is running to keep alive",
        ) from None
    return _deep_tune_response(deep_tune)


def _clips_since(session: Session, freq_id: int, since: datetime) -> int:
    return session.exec(
        select(func.count())
        .select_from(Recording)
        .where(Recording.freq_id == freq_id, Recording.started_at_utc >= since)
    ).one()


def _last_heard(session: Session, freq_id: int) -> datetime | None:
    return session.exec(
        select(Recording.started_at_utc)
        .where(Recording.freq_id == freq_id)
        .order_by(Recording.started_at_utc.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()


def meters_view(session: Session, settings: Settings) -> MetersResponse:
    snapshot = read_stats(default_stats_path(settings.data_root))
    service = TuningService(settings.capture)
    applied_at = service.last_applied_at(session)
    now = utcnow()

    active = session.exec(
        select(Frequency).where(Frequency.is_active).order_by(Frequency.mhz)  # type: ignore[arg-type]
    ).all()

    channels = []
    total_since = 0
    for freq in active:
        reading = snapshot.channel_for(freq.mhz)
        clips_since = None
        if applied_at is not None:
            clips_since = _clips_since(session, freq.id, applied_at)
            total_since += clips_since
        channels.append(
            ChannelMeter(
                freq_id=freq.id,
                label=freq.label,
                mhz=freq.mhz,
                signal_dbfs=reading.signal_dbfs if reading else None,
                noise_dbfs=reading.noise_dbfs if reading else None,
                snr_db=reading.snr_db if reading else None,
                squelch_level_dbfs=reading.squelch_level_dbfs if reading else None,
                squelch_open_count=reading.squelch_open_count if reading else None,
                flappy_count=reading.flappy_count if reading else None,
                clips_last_hour=_clips_since(session, freq.id, now - timedelta(hours=1)),
                last_heard_utc=_last_heard(session, freq.id),
                clips_since_apply=clips_since,
            )
        )

    return MetersResponse(
        stats=StatsFileState(
            present=snapshot.file_present,
            stale=snapshot.stale,
            updated_at=snapshot.updated_at,
        ),
        channels=channels,
        since_last_apply=(
            SinceLastApply(applied_at=applied_at, total_clips=total_since)
            if applied_at is not None
            else None
        ),
        links={"self": Link(href="/tuning/meters"), "tuning": Link(href="/tuning")},
    )
