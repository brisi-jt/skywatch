"""The station API application.

``create_app`` wires the FastAPI app from settings; ``main`` is the
``skywatch-api`` entry point that serves it with uvicorn. The app is one of
three station processes (capture, worker, API) that share only the SQLite
database — it never talks to the worker directly.
"""

import contextlib
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from skywatch.api.errors import register_error_handlers
from skywatch.api.routes import (
    clips,
    content,
    digest,
    frequencies,
    recordings,
    station_settings,
    status,
    tuning,
)
from skywatch.api.services.capture import CaptureController
from skywatch.api.services.recordings import build_summaries
from skywatch.api.services.status import build_status
from skywatch.api.ws import ChangePoller, StreamHub, run_poller
from skywatch.db.engine import create_db_engine, default_db_path
from skywatch.db.models import Recording
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
`{"type": <event>, "payload": <object>}` with three event types:
`recording.new` (payload: a /recordings list item), `recording.updated`
(same shape, sent when a clip's pipeline stage or verdicts change), and
`status.changed` (payload: the /status shape, sent when station settings
change). The stream sends events only — anything a client sends is ignored.

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
) -> FastAPI:
    settings = settings or Settings()
    engine = engine or create_db_engine(default_db_path(settings.data_root))
    capture = capture or CaptureController(engine=engine, settings=settings)
    content_dir = Path(content_dir) if content_dir else _default_content_dir()
    static_dir = Path(static_dir) if static_dir else _default_static_dir()

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
        return build_status(session, settings=settings, capture=capture).model_dump(
            mode="json", by_alias=True
        )

    poller = ChangePoller(
        engine=engine,
        hub=hub,
        recording_payload=_recording_payload,
        status_payload=_status_payload,
        interval=ws_poll_interval,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with run_poller(poller):
            yield

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
    app.state.stream_hub = hub

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
