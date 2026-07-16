"""Builds the station status view.

Everything comes from the database and the filesystem — the API never
reaches into the worker process. The capture trace compares three
independent facts (what the database says should be captured, what the
rendered config file on disk says, whether the process is running) so a
stalled frequency change is visible as a mismatch between steps.
"""

import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from skywatch.api.schemas import (
    BudgetInfo,
    CaptureStatus,
    CaptureTrace,
    ConfState,
    DiskInfo,
    Link,
    StatusBudgets,
    StatusResponse,
    TraceChannel,
    TraceConf,
    TraceIntent,
    TraceProcess,
)
from skywatch.api.services.capture import CaptureController
from skywatch.capture.conf_render import render_conf
from skywatch.capture.validate import validate_frequencies
from skywatch.db.enums import ApiProvider
from skywatch.db.models import Frequency, Setting
from skywatch.pipeline import budget
from skywatch.pipeline.retention import CAPTURE_PAUSED_KEY, check_disk
from skywatch.pipeline.worker import queue_depths
from skywatch.settings import Settings

logger = logging.getLogger(__name__)

STATION_NAME_KEY = "station_name"


def active_frequencies(session: Session) -> list[Frequency]:
    return list(
        session.exec(
            select(Frequency).where(Frequency.is_active).order_by(Frequency.mhz)  # type: ignore[arg-type]
        ).all()
    )


def station_name(session: Session) -> str | None:
    row = session.get(Setting, STATION_NAME_KEY)
    return row.value if row is not None else None


def _conf_state(
    settings: Settings, capture: CaptureController, active: list[Frequency]
) -> TraceConf:
    if settings.capture.source != "live":
        return TraceConf(state=ConfState.NOT_APPLICABLE, path=None)
    conf_path = capture.conf_path
    if not conf_path.exists():
        return TraceConf(state=ConfState.MISSING, path=str(conf_path))
    try:
        recordings_dir = settings.capture.output_dir
        if not recordings_dir.is_absolute():
            recordings_dir = recordings_dir.resolve()
        expected = render_conf(active, settings.capture, recordings_dir=recordings_dir)
    except ValueError:
        # the database plan is not renderable (e.g. nothing active), so
        # whatever is on disk cannot reflect it
        return TraceConf(state=ConfState.STALE, path=str(conf_path))
    state = ConfState.MATCH if conf_path.read_text() == expected else ConfState.STALE
    return TraceConf(state=state, path=str(conf_path))


def _budgets(session: Session, settings: Settings) -> StatusBudgets:
    today = datetime.now(UTC).date()
    llm = None
    if settings.llm.provider != "none":
        provider = ApiProvider(settings.llm.provider)
        calls = budget.calls_today(session, provider, today)
        llm = BudgetInfo(
            provider=provider.value,
            calls_today=calls,
            daily_cap=settings.llm.daily_call_cap,
            remaining=max(0, settings.llm.daily_call_cap - calls),
        )
    opensky = None
    if settings.enrichment.provider == "opensky":
        calls = budget.calls_today(session, ApiProvider.OPENSKY, today)
        opensky = BudgetInfo(
            provider=ApiProvider.OPENSKY.value,
            calls_today=calls,
            daily_cap=settings.enrichment.daily_credit_cap,
            remaining=max(0, settings.enrichment.daily_credit_cap - calls),
        )
    return StatusBudgets(llm=llm, opensky=opensky)


def build_status(
    session: Session, *, settings: Settings, capture: CaptureController
) -> StatusResponse:
    active = active_frequencies(session)
    validation = validate_frequencies(active, settings.capture.mode)
    centerfreq = (
        validation.suggested_centerfreq_mhz if settings.capture.mode == "multichannel" else None
    )

    source_status = capture.status()
    running = source_status.running if source_status else False
    detail = source_status.detail if source_status else "capture is driven by the worker process"
    paused_row = session.get(Setting, CAPTURE_PAUSED_KEY)
    paused = paused_row is not None and paused_row.value == "1"

    # before first capture the data root may not exist yet; measure the
    # filesystem it will live on
    disk_path = settings.data_root
    while not disk_path.exists() and disk_path != disk_path.parent:
        disk_path = disk_path.parent
    disk = check_disk(disk_path, settings.retention.min_free_disk_gb)

    return StatusResponse(
        station_name=station_name(session),
        capture=CaptureStatus(
            source=settings.capture.source,
            mode=settings.capture.mode,
            running=running,
            detail=detail,
            paused_for_disk=paused,
            dongle_present=capture.dongle_present(),
            centerfreq_mhz=centerfreq,
        ),
        trace=CaptureTrace(
            db_intent=TraceIntent(
                mode=settings.capture.mode,
                channels=[TraceChannel(label=f.label, mhz=f.mhz) for f in active],
            ),
            rendered_conf=_conf_state(settings, capture, active),
            process=TraceProcess(running=running, detail=detail),
        ),
        queues=queue_depths(session),
        disk=DiskInfo(
            free_gb=disk.free_gb,
            total_gb=disk.total_gb,
            min_free_gb=disk.min_free_gb,
            low=disk.low,
        ),
        budgets=_budgets(session, settings),
        links={"self": Link(href="/status")},
    )
