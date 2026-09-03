"""Optional real-time push for interesting clips, via ntfy.sh or self-hosted.

Off by default (``digest.ntfy.enabled``). When on, a self-imposed cooldown
between pushes keeps a burst of simultaneous interesting clips from spamming
the listener's phone — the one channel here that leaves the LAN, so it gets
its own throttle rather than relying on any in-dashboard alert machinery.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
from sqlmodel import Session

from skywatch.db.models import Setting

logger = logging.getLogger(__name__)

NTFY_MIN_INTERVAL_S = 30.0
"""Minimum time between pushes, regardless of how many clips arrive at once."""

_LAST_SENT_KEY = "ntfy:last_sent_at"

_URGENT_CATEGORIES = {"emergency", "guard_activity"}


@dataclass(frozen=True)
class NtfyConfig:
    enabled: bool = False
    topic: str | None = None
    server: str = "https://ntfy.sh"


def _seconds_since_last_push(session: Session, now: datetime) -> float | None:
    row = session.get(Setting, _LAST_SENT_KEY)
    if row is None:
        return None
    try:
        last = datetime.fromisoformat(row.value)
    except ValueError:
        return None
    return (now - last).total_seconds()


def _header_value(value: str) -> str:
    """HTTP header values must be ASCII; ntfy's documented workaround for
    titles/messages with wider characters (e.g. an em dash) is to percent-
    encode the header — ntfy decodes it back on the other end."""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        return quote(value)


def _record_push(session: Session, now: datetime) -> None:
    row = session.get(Setting, _LAST_SENT_KEY)
    if row is None:
        session.add(Setting(key=_LAST_SENT_KEY, value=now.isoformat()))
    else:
        row.value = now.isoformat()
        session.add(row)


def push_interesting_clip(
    cfg: NtfyConfig,
    session: Session,
    *,
    title: str,
    message: str,
    category: str,
    click_url: str | None = None,
    now: datetime | None = None,
    http: httpx.Client | None = None,
) -> bool:
    """Push one clip notification, respecting the cooldown.

    Returns whether it actually sent — False for disabled, unconfigured, or
    within the cooldown window. Raises on an HTTP failure; the caller isolates
    that the same way it isolates the weekly email.
    """
    if not cfg.enabled or not cfg.topic:
        return False
    now = now or datetime.now(UTC)
    elapsed = _seconds_since_last_push(session, now)
    if elapsed is not None and elapsed < NTFY_MIN_INTERVAL_S:
        return False

    headers = {"Title": _header_value(title)}
    if click_url:
        headers["Click"] = _header_value(click_url)
    if category in _URGENT_CATEGORIES:
        headers["Priority"] = "urgent"

    client = http or httpx.Client(timeout=10)
    try:
        response = client.post(
            f"{cfg.server.rstrip('/')}/{cfg.topic}",
            content=message.encode("utf-8"),
            headers=headers,
        )
        response.raise_for_status()
    finally:
        if http is None:
            client.close()

    _record_push(session, now)
    return True
