"""Frequency-plan routes: list the plan, switch channels on and off."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from starlette import status

from skywatch.api.deps import get_capture, get_deep_tune, get_session, get_settings
from skywatch.api.errors import APIErrorCode, ProblemDetail, ProblemException
from skywatch.api.schemas import (
    FrequencyActionResponse,
    FrequencyListResponse,
    FrequencyResource,
    Link,
)
from skywatch.api.services.capture import CaptureController
from skywatch.api.services.deep_tune import DeepTuneManager
from skywatch.capture.validate import validate_frequencies
from skywatch.db.models import Frequency
from skywatch.settings import Settings

router = APIRouter(tags=["frequencies"])


def _resource(freq: Frequency) -> FrequencyResource:
    action = "deactivate" if freq.is_active else "activate"
    return FrequencyResource(
        id=freq.id,
        label=freq.label,
        mhz=freq.mhz,
        mode=freq.mode,
        facility=freq.facility,
        category=freq.category,
        description=freq.description,
        is_active=freq.is_active,
        tuner_group=freq.tuner_group,
        verified=freq.verified,
        links={
            action: Link(href=f"/frequencies/{freq.id}/{action}"),
            "recordings": Link(href=f"/recordings?freq_id={freq.id}"),
        },
    )


def _reject_while_deep_tune_active(deep_tune: DeepTuneManager) -> None:
    """Changing the plan restarts capture, which cannot claim the receiver
    while a deep tune session holds it — the same guard as tuning apply."""
    if deep_tune.active:
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.DEEP_TUNE_ACTIVE,
            "a deep tune session has the receiver; exit deep tune before "
            "changing which frequencies are recorded",
        )


def _get_frequency(session: Session, freq_id: int) -> Frequency:
    freq = session.get(Frequency, freq_id)
    if freq is None:
        raise ProblemException(
            status.HTTP_404_NOT_FOUND,
            APIErrorCode.FREQUENCY_NOT_FOUND,
            f"no frequency with id {freq_id} in the plan",
        )
    return freq


@router.get(
    "/frequencies",
    response_model=FrequencyListResponse,
    summary="List the frequency plan",
    description=(
        "Every frequency the station knows about, active or not, ordered by "
        "MHz. Rows with `verified: false` carry placeholder frequencies that "
        "have not been checked against a current source and should be "
        "displayed with a caveat. Each item links to the action currently "
        "available on it (activate or deactivate) and to its recordings."
    ),
)
def list_frequencies(
    session: Annotated[Session, Depends(get_session)],
) -> FrequencyListResponse:
    rows = session.exec(select(Frequency).order_by(Frequency.mhz)).all()  # type: ignore[arg-type]
    return FrequencyListResponse(
        items=[_resource(freq) for freq in rows],
        links={"self": Link(href="/frequencies")},
    )


@router.post(
    "/frequencies/{freq_id}/activate",
    response_model=FrequencyActionResponse,
    summary="Start recording a frequency",
    description=(
        "Adds the frequency to the active plan, rewrites the capture "
        "configuration, and restarts capture (a restart drops a few seconds "
        "of audio — there is no hot retune). In multichannel mode every "
        "active frequency must fit one 2.56 MHz tuner window; when the new "
        "set does not fit, the response is a 409 problem detail whose "
        "`offenders` lists the frequencies to deactivate and whose "
        "`suggested_centerfreq_mhz` is the centre frequency for the largest "
        "set that does fit. Switching the station to scan mode is the "
        "alternative escape hatch, at the cost of missing concurrent "
        "transmissions. Activating an already-active frequency changes "
        "nothing. While a deep tune session holds the receiver the plan "
        "cannot change: the response is a 409 problem detail with code "
        "`deep_tune_active`."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown frequency."},
        409: {
            "model": ProblemDetail,
            "description": (
                "The active set would not fit one tuner window, or a deep "
                "tune session has the receiver."
            ),
        },
    },
)
def activate_frequency(
    freq_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    capture: Annotated[CaptureController, Depends(get_capture)],
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> FrequencyActionResponse:
    _reject_while_deep_tune_active(deep_tune)
    freq = _get_frequency(session, freq_id)
    if freq.is_active:
        return FrequencyActionResponse(
            frequency=_resource(freq), warnings=[], capture_restarted=False
        )

    active = session.exec(select(Frequency).where(Frequency.is_active)).all()
    prospective = list(active) + [freq]
    validation = validate_frequencies(prospective, settings.capture.mode)
    if not validation.ok:
        raise ProblemException(
            status.HTTP_409_CONFLICT,
            APIErrorCode.WINDOW_CONFLICT,
            " ".join(validation.errors),
            extensions={
                "offenders": validation.offenders,
                "suggested_centerfreq_mhz": validation.suggested_centerfreq_mhz,
            },
        )

    freq.is_active = True
    session.add(freq)
    session.commit()
    session.refresh(freq)

    restarted, warning = capture.restart(has_active=True)
    warnings = list(validation.warnings)
    if warning:
        warnings.append(warning)
    return FrequencyActionResponse(
        frequency=_resource(freq), warnings=warnings, capture_restarted=restarted
    )


@router.post(
    "/frequencies/{freq_id}/deactivate",
    response_model=FrequencyActionResponse,
    summary="Stop recording a frequency",
    description=(
        "Removes the frequency from the active plan, rewrites the capture "
        "configuration, and restarts capture. Deactivating the last active "
        "frequency stops capture entirely (with a warning in the response) "
        "until something is activated again. Deactivating an already-inactive "
        "frequency changes nothing. While a deep tune session holds the "
        "receiver the plan cannot change: the response is a 409 problem "
        "detail with code `deep_tune_active`."
    ),
    responses={
        404: {"model": ProblemDetail, "description": "Unknown frequency."},
        409: {
            "model": ProblemDetail,
            "description": "A deep tune session has the receiver.",
        },
    },
)
def deactivate_frequency(
    freq_id: int,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    capture: Annotated[CaptureController, Depends(get_capture)],
    deep_tune: Annotated[DeepTuneManager, Depends(get_deep_tune)],
) -> FrequencyActionResponse:
    _reject_while_deep_tune_active(deep_tune)
    freq = _get_frequency(session, freq_id)
    if not freq.is_active:
        return FrequencyActionResponse(
            frequency=_resource(freq), warnings=[], capture_restarted=False
        )

    freq.is_active = False
    session.add(freq)
    session.commit()
    session.refresh(freq)

    remaining = session.exec(select(Frequency).where(Frequency.is_active)).all()
    validation = validate_frequencies(list(remaining), settings.capture.mode)
    restarted, warning = capture.restart(has_active=bool(remaining))
    warnings = list(validation.warnings) if remaining else list(validation.errors)
    if warning:
        warnings.append(warning)
    return FrequencyActionResponse(
        frequency=_resource(freq), warnings=warnings, capture_restarted=restarted
    )
