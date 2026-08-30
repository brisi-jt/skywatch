"""Tuning bench routes: read levers and meters, apply values, save a baseline,
and run exclusive deep tune spectrum sessions."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session

from skywatch.api.deps import get_capture, get_deep_tune, get_session, get_settings
from skywatch.api.errors import ProblemDetail
from skywatch.api.schemas import (
    DeepTuneSessionResponse,
    MetersResponse,
    TuningApplyRequest,
    TuningApplyResponse,
    TuningResponse,
)
from skywatch.api.services.capture import CaptureController
from skywatch.api.services.deep_tune import DeepTuneManager
from skywatch.api.services.tuning import (
    apply_tuning,
    meters_view,
    ping_deep_tune,
    save_baseline,
    start_deep_tune,
    stop_deep_tune,
    tuning_view,
)
from skywatch.settings import Settings

router = APIRouter(tags=["tuning"])


@router.get(
    "/tuning",
    response_model=TuningResponse,
    summary="Read the station's tuning state",
    description=(
        "The tuning levers as currently applied — tuner gain, the squelch "
        "threshold (station default plus any per-frequency overrides), and "
        "the frequency correction in ppm — alongside the saved baseline "
        "(null until one is saved), the shipped factory values, and the "
        "tuner's real gain steps. Gain controls should offer exactly the "
        "listed steps: the hardware cannot sit between them. "
        "`deep_tune` reports whether an exclusive off-air spectrum session "
        "is running, and if so how long it has left before the idle timeout."
    ),
)
def get_tuning(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> TuningResponse:
    return tuning_view(session, settings, deep_tune=deep_tune)


@router.post(
    "/tuning/apply",
    response_model=TuningApplyResponse,
    summary="Apply a new set of tuning values",
    description=(
        "Persists a complete set of tuning values, rewrites the capture "
        "configuration, and restarts capture — the station is off-air for "
        "around five seconds. The request is the full value set, not a "
        "delta: send the current value for levers that are not changing, "
        "and omit a per-frequency override to remove it. Gain is snapped to "
        "the tuner's nearest real step. When any value fails validation, "
        "nothing is applied and the 422 problem detail names the offender."
    ),
    responses={
        409: {
            "model": ProblemDetail,
            "description": (
                "A deep tune session has the receiver (stop it first), or "
                "capture is paused for low disk (code `capture_paused_low_disk`)."
            ),
        },
        422: {
            "model": ProblemDetail,
            "description": "A value is out of range or names an unknown frequency.",
        },
    },
)
def post_apply(
    payload: TuningApplyRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    capture: Annotated[CaptureController, Depends(get_capture)],
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> TuningApplyResponse:
    return apply_tuning(session, payload, settings=settings, capture=capture, deep_tune=deep_tune)


@router.post(
    "/tuning/baseline",
    response_model=TuningResponse,
    summary="Save the applied values as the station baseline",
    description=(
        "Snapshots the currently applied tuning values as the station's "
        "baseline — the values each lever's reset control returns to. "
        "Replaces any previously saved baseline."
    ),
)
def post_baseline(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> TuningResponse:
    return save_baseline(session, settings, deep_tune=deep_tune)


@router.get(
    "/tuning/meters",
    response_model=MetersResponse,
    summary="Read the live channel meters",
    description=(
        "Per-frequency readings from the capture process's statistics file "
        "(rewritten every 15 seconds while capture runs) merged with "
        "recording activity: signal and noise in dBFS, the derived "
        "signal-to-noise ratio, squelch opens, clips in the last hour, when "
        "each frequency last heard a transmission, and clip counts since "
        "tuning was last applied. When `stats.present` is false the file "
        "has not been written yet — the station may still be starting — and "
        "when `stats.stale` is true the numbers are old and meters should "
        "show a paused state rather than live values."
    ),
)
def get_meters(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MetersResponse:
    return meters_view(session, settings)


@router.post(
    "/tuning/deep-tune/start",
    response_model=DeepTuneSessionResponse,
    summary="Start an exclusive off-air spectrum session",
    description=(
        "Stops capture, opens the receiver directly, and streams "
        "`spectrum.frame` events over `WS /stream` a few times a second — "
        "the station records nothing while the session runs. The server "
        "ends the session itself after ten minutes without a ping (a "
        "`deep_tune.state` warning event fires one minute beforehand) or "
        "within about thirty seconds of every stream client disappearing; "
        "every exit path restarts capture."
    ),
    responses={
        409: {
            "model": ProblemDetail,
            "description": "A deep tune session is already running.",
        },
        503: {
            "model": ProblemDetail,
            "description": (
                "The station cannot stream a spectrum: it is in replay mode, "
                "receiver support is not installed, or nothing is active."
            ),
        },
    },
)
def post_deep_tune_start(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> DeepTuneSessionResponse:
    return start_deep_tune(session, settings=settings, deep_tune=deep_tune)


@router.post(
    "/tuning/deep-tune/stop",
    response_model=DeepTuneSessionResponse,
    summary="Stop the deep tune session",
    description=(
        "Ends the running spectrum session and restarts capture before "
        "responding — the station is back on air when this returns."
    ),
    responses={
        409: {"model": ProblemDetail, "description": "No deep tune session is running."},
    },
)
def post_deep_tune_stop(
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> DeepTuneSessionResponse:
    return stop_deep_tune(deep_tune)


@router.post(
    "/tuning/deep-tune/ping",
    response_model=DeepTuneSessionResponse,
    summary="Keep the deep tune session alive",
    description=(
        "Resets the session's idle countdown. Send one whenever the "
        "operator interacts with the tuning bench, and periodically while "
        "the spectrum view is open."
    ),
    responses={
        409: {"model": ProblemDetail, "description": "No deep tune session is running."},
    },
)
def post_deep_tune_ping(
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> DeepTuneSessionResponse:
    return ping_deep_tune(deep_tune)
