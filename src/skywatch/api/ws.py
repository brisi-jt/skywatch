"""WS /stream: live events for the dashboard.

Every message is one envelope: ``{"type": <event>, "payload": <object>}``
with three event types:

- ``recording.new`` — a clip just landed; payload is the same summary shape
  as a /recordings list item.
- ``recording.updated`` — an existing clip changed (pipeline stage advance,
  new transcript/verdict); payload is the refreshed summary.
- ``status.changed`` — station settings changed (e.g. a rename); payload is
  the full /status shape.

The worker writes rows and never notifies anyone, so the API polls the
database for changes on a short interval — cheap under SQLite WAL at
station traffic rates, and it keeps the worker/API contract purely
database-shaped.
"""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, and_, or_
from sqlmodel import Session, select
from starlette.websockets import WebSocket

from skywatch.db.models import Recording, Setting
from skywatch.pipeline.retention import DEEP_TUNE_ACTIVE_KEY

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Settings keys that must not raise a status.changed event. The deep-tune
# heartbeat rewrites its row a few times a minute while a session runs; it is
# cross-process bookkeeping, not station state a client needs to refetch for.
_SILENT_SETTING_KEYS = (DEEP_TUNE_ACTIVE_KEY,)


class StreamHub:
    """Fan-out of event envelopes to every connected websocket."""

    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._clients:
            self._clients.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        for websocket in list(self._clients):
            try:
                await websocket.send_json(message)
            except Exception:
                self.disconnect(websocket)


class ChangePoller:
    """Watches the database and turns row changes into stream events."""

    def __init__(
        self,
        *,
        engine: Engine,
        hub: StreamHub,
        recording_payload: Callable[[Session, Recording], dict],
        status_payload: Callable[[Session], dict],
        interval: float = 1.0,
    ) -> None:
        self._engine = engine
        self._hub = hub
        self._recording_payload = recording_payload
        self._status_payload = status_payload
        self._interval = interval
        self._last_recording_id = 0
        # Composite (updated_at, id) / (updated_at, key) watermarks: a plain
        # ``> timestamp`` skips rows that share the boundary timestamp, so
        # updates committed in the same tick as the watermark are lost. The
        # tie-breaker on the primary key makes the boundary exclusive without
        # dropping same-timestamp rows that sort after it.
        self._recording_watermark: tuple[datetime, int] = (_EPOCH, 0)
        self._settings_watermark: tuple[datetime, str] = (_EPOCH, "")

    def baseline(self) -> None:
        """Absorb the current database state so history is not replayed to
        clients that connect later."""
        with Session(self._engine) as session:
            last = session.exec(
                select(Recording).order_by(Recording.id.desc())  # type: ignore[union-attr]
            ).first()
            if last is not None:
                self._last_recording_id = last.id
            newest_updated = session.exec(
                select(Recording).order_by(
                    Recording.updated_at.desc(),  # type: ignore[attr-defined]
                    Recording.id.desc(),  # type: ignore[union-attr]
                )
            ).first()
            if newest_updated is not None:
                self._recording_watermark = (newest_updated.updated_at, newest_updated.id)
            newest_setting = session.exec(
                select(Setting)
                .where(Setting.key.notin_(_SILENT_SETTING_KEYS))  # type: ignore[attr-defined]
                .order_by(
                    Setting.updated_at.desc(),  # type: ignore[attr-defined]
                    Setting.key.desc(),  # type: ignore[union-attr]
                )
            ).first()
            if newest_setting is not None:
                self._settings_watermark = (newest_setting.updated_at, newest_setting.key)

    def collect(self) -> list[dict]:
        """One polling pass: the events that happened since the last one."""
        messages: list[dict] = []
        with Session(self._engine) as session:
            new_rows = session.exec(
                select(Recording)
                .where(Recording.id > self._last_recording_id)
                .order_by(Recording.id)  # type: ignore[arg-type]
            ).all()
            previous_last = self._last_recording_id
            wm_ts, wm_id = self._recording_watermark
            for recording in new_rows:
                messages.append(
                    {
                        "type": "recording.new",
                        "payload": self._recording_payload(session, recording),
                    }
                )
                self._last_recording_id = max(self._last_recording_id, recording.id)
                self._recording_watermark = max(
                    self._recording_watermark, (recording.updated_at, recording.id)
                )
            updated_rows = session.exec(
                select(Recording)
                .where(
                    Recording.id <= previous_last,
                    or_(
                        Recording.updated_at > wm_ts,
                        and_(Recording.updated_at == wm_ts, Recording.id > wm_id),
                    ),
                )
                .order_by(
                    Recording.updated_at,  # type: ignore[arg-type]
                    Recording.id,  # type: ignore[arg-type]
                )
            ).all()
            for recording in updated_rows:
                messages.append(
                    {
                        "type": "recording.updated",
                        "payload": self._recording_payload(session, recording),
                    }
                )
                self._recording_watermark = max(
                    self._recording_watermark, (recording.updated_at, recording.id)
                )
            s_ts, s_key = self._settings_watermark
            changed_settings = session.exec(
                select(Setting)
                .where(
                    Setting.key.notin_(_SILENT_SETTING_KEYS),  # type: ignore[attr-defined]
                    or_(
                        Setting.updated_at > s_ts,
                        and_(Setting.updated_at == s_ts, Setting.key > s_key),
                    ),
                )
                .order_by(
                    Setting.updated_at,  # type: ignore[arg-type]
                    Setting.key,  # type: ignore[arg-type]
                )
            ).all()
            if changed_settings:
                self._settings_watermark = max(
                    (row.updated_at, row.key) for row in changed_settings
                )
                messages.append(
                    {"type": "status.changed", "payload": self._status_payload(session)}
                )
        return messages

    async def run(self) -> None:
        await asyncio.to_thread(self.baseline)
        while True:
            await asyncio.sleep(self._interval)
            try:
                messages = await asyncio.to_thread(self.collect)
            except Exception:
                logger.exception("stream poll failed; continuing")
                continue
            for message in messages:
                await self._hub.broadcast(message)


@contextlib.asynccontextmanager
async def run_poller(poller: ChangePoller):
    task = asyncio.create_task(poller.run())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
