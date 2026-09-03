"""The station API application.

``create_app`` wires the FastAPI app from settings; ``main`` is the
``skywatch-api`` entry point that serves it with uvicorn. The app is one of
three station processes (capture, worker, API) that share only the SQLite
database — it never talks to the worker directly.
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from skywatch.api.errors import register_error_handlers
from skywatch.api.routes import (
    clips,
    content,
    digest,
    eval,
    frequencies,
    recordings,
    station_settings,
    stats,
    status,
    tuning,
)
from skywatch.api.services.capture import CaptureController
from skywatch.api.services.deep_tune import (
    DeepTuneManager,
    IQSourceFactory,
    PyRtlSdrSourceFactory,
)
from skywatch.api.services.recordings import build_summaries
from skywatch.api.services.status import build_status
from skywatch.api.ws import ChangePoller, StreamHub, run_poller
from skywatch.db import fts
from skywatch.db.engine import create_db_engine, default_db_path
from skywatch.db.models import Frequency, Recording, Setting, utcnow
from skywatch.pipeline.retention import DEEP_TUNE_ACTIVE_KEY
from skywatch.providers.llm import build_classifier_chain
from skywatch.settings import Settings
from skywatch.tuning import TuningService

logger = logging.getLogger(__name__)

API_DESCRIPTION = """\
The complete contract for a skywatch station: a receive-only SDR aviation
monitor that records VHF airband transmissions, transcribes them locally,
flags the interesting ones, and attaches probable aircraft.

Reading the data:

- `/status` — station health; `/frequencies` — the listening plan.
- `/recordings` — the clip library; `/clips/interesting` — the good bits;
  `/digest` — one day summarised for a "today" view.
- `/runbook` and `/glossary` — station documents as Markdown.

Live updates come from `WS /stream`. Every message is an envelope
`{"type": <event>, "payload": <object>}` with five event types:
`recording.new` (payload: a /recordings list item), `recording.updated`
(same shape, sent when a clip's pipeline stage or verdicts change),
`status.changed` (payload: the /status shape, sent when station settings
change), and — only while a deep tune session is running — `spectrum.frame`
(payload: frequency axis metadata plus a dB curve and per-channel powers)
and `deep_tune.state` (payload: started/warning/stopped with a reason).
The stream sends events only — anything a client sends is ignored.

Errors are RFC 7807 problem details (`application/problem+json`) with a
stable `code` field to switch on.

The API is unauthenticated by design: it is meant for a private LAN or
Tailscale network only, and must not be exposed to the public internet.
Transmissions are received for personal monitoring; audio must not be
rebroadcast.
"""


def _default_content_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    for candidate in (Path("content"), repo_root / "content"):
        if candidate.is_dir():
            return candidate
    return repo_root / "content"


def _default_static_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    for candidate in (Path("web/out"), repo_root / "web" / "out"):
        if candidate.is_dir():
            return candidate
    return repo_root / "web" / "out"


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    capture: CaptureController | None = None,
    content_dir: Path | None = None,
    static_dir: Path | None = None,
    ws_poll_interval: float = 1.0,
    deep_tune_factory: IQSourceFactory | None = None,
    fts_available: bool | None = None,
) -> FastAPI:
    settings = settings or Settings()
    engine = engine or create_db_engine(default_db_path(settings.data_root))
    capture = capture or CaptureController(engine=engine, settings=settings)
    content_dir = Path(content_dir) if content_dir else _default_content_dir()
    static_dir = Path(static_dir) if static_dir else _default_static_dir()
    if fts_available is None:
        fts_available = fts.search_available(engine)
    if not fts_available:
        logger.info("transcript search using LIKE fallback: FTS5 index unavailable")

    try:
        with Session(engine) as session:
            TuningService(settings.capture).ensure_seeded(session)
    except OperationalError:
        # the schema is not migrated yet (fresh checkout, schema export);
        # seeding happens on the first start after `make migrate`
        logger.warning("tuning values not seeded: database schema missing")

    hub = StreamHub()

    def _recording_payload(session: Session, recording: Recording) -> dict:
        return build_summaries(session, [recording])[0].model_dump(mode="json", by_alias=True)

    def _status_payload(session: Session) -> dict:
        return build_status(
            session, settings=settings, capture=capture, deep_tune=deep_tune
        ).model_dump(mode="json", by_alias=True)

    poller = ChangePoller(
        engine=engine,
        hub=hub,
        recording_payload=_recording_payload,
        status_payload=_status_payload,
        interval=ws_poll_interval,
    )

    # deep tune runs in its own thread; events reach websocket clients by
    # hopping onto the server's event loop, captured at startup below
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}

    def _publish_event(message: dict) -> None:
        loop = loop_holder.get("loop")
        if loop is None or loop.is_closed():
            logger.warning("dropping %s event: no running event loop", message.get("type"))
            return
        asyncio.run_coroutine_threadsafe(hub.broadcast(message), loop)

    def _restart_capture() -> None:
        with Session(engine) as session:
            has_active = (
                session.exec(select(Frequency).where(Frequency.is_active)).first() is not None
            )
        capture.restart(has_active=has_active)

    def _set_deep_tune_flag(active: bool) -> None:
        # the worker reads this to avoid starting rtl_airband while a deep
        # tune session holds the dongle; updated_at is the heartbeat
        with Session(engine) as session:
            row = session.get(Setting, DEEP_TUNE_ACTIVE_KEY)
            value = "1" if active else "0"
            if row is None:
                session.add(Setting(key=DEEP_TUNE_ACTIVE_KEY, value=value))
            else:
                row.value = value
                row.updated_at = utcnow()  # force a heartbeat even when unchanged
                session.add(row)
            session.commit()

    deep_tune = DeepTuneManager(
        source_factory=deep_tune_factory or PyRtlSdrSourceFactory(),
        publish=_publish_event,
        stop_capture=capture.stop,
        restart_capture=_restart_capture,
        clients_connected=lambda: hub.client_count > 0,
        set_active_flag=_set_deep_tune_flag,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        loop_holder["loop"] = asyncio.get_running_loop()
        try:
            async with run_poller(poller):
                yield
        finally:
            # a session left running at shutdown must not strand the station
            # off-air; stop() joins the thread, whose exit restarts capture
            await asyncio.to_thread(deep_tune.shutdown)

    app = FastAPI(
        title="skywatch station",
        version="0.1.0",
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.engine = engine
    app.state.settings = settings
    app.state.capture = capture
    app.state.content_dir = content_dir
    app.state.timezone = ZoneInfo(settings.server.timezone)
    app.state.fts_available = fts_available
    # The API drives on-demand narrative summaries through the same provider
    # chain and budget as the worker; missing credentials yield an empty chain.
    app.state.classifier_chain = build_classifier_chain(
        settings.llm,
        gemini_api_key=settings.gemini_api_key,
        groq_api_key=settings.groq_api_key,
    )
    app.state.stream_hub = hub
    app.state.deep_tune = deep_tune

    # The dashboard is served same-origin in normal use; the permissive CORS
    # policy exists for dashboard development servers on other local ports,
    # in keeping with the LAN-only, unauthenticated posture.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    app.include_router(status.router)
    app.include_router(frequencies.router)
    app.include_router(recordings.router)
    app.include_router(clips.router)
    app.include_router(digest.router)
    app.include_router(content.router)
    app.include_router(station_settings.router)
    app.include_router(tuning.router)
    app.include_router(eval.router)
    app.include_router(stats.router)

    @app.websocket("/stream")
    async def stream(websocket: WebSocket) -> None:
        await hub.connect(websocket)
        try:
            while True:
                # the stream is send-only; drain and ignore client messages
                await websocket.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(websocket)

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="dashboard")

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.server.host, port=settings.server.port)


if __name__ == "__main__":
    main()
