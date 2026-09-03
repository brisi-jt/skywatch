"""The weekly summary email: a week's narrative, top clips, and a stats strip.

Sent by the worker's maintenance pass on the station-local configured day and
hour (``digest.email`` in settings). Building the input and rendering the
HTML have zero network dependencies; sending is the only I/O, isolated in
``send_email`` so a mail-server outage never reaches the rest of the
maintenance pass. The week's narrative is stitched from the daily narratives
already cached by the daily-narrative feature, rather than a fresh model
call — it costs nothing extra against the classifier budget and degrades
cleanly to a stats-only email on a station with narratives disabled or
unbudgeted.

This module lives in the pipeline layer deliberately: it depends only on the
database and stdlib email/smtp, never on the API, so both the worker and any
future caller can drive it.
"""

import logging
import smtplib
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from skywatch.db.enums import ClassificationCategory
from skywatch.db.models import Classification, Frequency, Recording
from skywatch.pipeline import narrative as narrative_cache

logger = logging.getLogger(__name__)

WEEK_DAYS = 7

TOP_CLIPS_LIMIT = 8

CATEGORY_WEIGHTS: dict[ClassificationCategory, float] = {
    ClassificationCategory.EMERGENCY: 5.0,
    ClassificationCategory.GUARD_ACTIVITY: 4.0,
    ClassificationCategory.GO_AROUND: 3.0,
}
DEFAULT_WEIGHT = 1.0

_DAY_NAME_TO_WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

WEEKLY_EMAIL_SENT_PREFIX = "weekly_email:sent:"
"""Settings-table key prefix; one row per calendar day the email was sent,
which — because it is only ever sent on the configured weekday — doubles as
the once-a-week idempotency guard."""

STATION_NAME_KEY = "station_name"
"""Mirrors the API layer's key of the same name (``api/services/status.py``);
duplicated rather than imported so this module stays API-independent."""


def sent_marker_key(day: date) -> str:
    return f"{WEEKLY_EMAIL_SENT_PREFIX}{day.isoformat()}"


@dataclass(frozen=True)
class EmailDigestConfig:
    """Everything the weekly email needs, gathered in one place for injection."""

    enabled: bool = False
    to: tuple[str, ...] = field(default_factory=tuple)
    day: str = "sun"
    hour: int = 8
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    public_base_url: str | None = None


@dataclass(frozen=True)
class WeeklyTopClip:
    recording_id: int
    local_time: str
    freq_label: str
    category: str
    reason: str


@dataclass(frozen=True)
class WeeklyEmailInput:
    week_start: date
    week_end: date
    """Exclusive: the window is [week_start, week_end)."""
    total_count: int
    interesting_count: int
    category_counts: dict[str, int]
    top_clips: list[WeeklyTopClip]
    narrative_text: str | None


def is_due(*, day: str, hour: int, now_local: datetime) -> bool:
    """Whether the configured send window has arrived, station-local."""
    return now_local.weekday() == _DAY_NAME_TO_WEEKDAY[day] and now_local.hour >= hour


def _day_start_utc(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)


def _latest_classifications(session: Session, ids: list[int]) -> dict[int, Classification]:
    if not ids:
        return {}
    latest: dict[int, Classification] = {}
    for row in session.exec(
        select(Classification)
        .where(Classification.recording_id.in_(ids))  # type: ignore[attr-defined]
        .order_by(Classification.id)  # type: ignore[arg-type]
    ).all():
        latest[row.recording_id] = row
    return latest


def _week_narrative(session: Session, *, week_start: date, week_end: date) -> str | None:
    """Stitch the week's cached daily narratives into one paragraph.

    Only the days that actually have a narrative contribute a sentence; a
    week with none (narratives disabled, or every day's budget was tight)
    yields None, and the email falls back to its stats strip alone.
    """
    sentences: list[str] = []
    day = week_start
    while day < week_end:
        cached = narrative_cache.cached_narrative(session, day)
        if cached is not None:
            sentences.append(f"{day.strftime('%A')}: {cached.text}")
        day += timedelta(days=1)
    return " ".join(sentences) if sentences else None


def build_weekly_email_input(
    session: Session, *, tz: ZoneInfo, now: datetime | None = None
) -> WeeklyEmailInput:
    """Summarise the last seven station-local days, ending today."""
    now = now or datetime.now(UTC)
    today = now.astimezone(tz).date()
    week_start = today - timedelta(days=WEEK_DAYS - 1)
    week_end = today + timedelta(days=1)  # exclusive: through the end of today

    start_utc = _day_start_utc(week_start, tz)
    end_utc = _day_start_utc(week_end, tz)
    recordings = list(
        session.exec(
            select(Recording).where(
                Recording.started_at_utc >= start_utc, Recording.started_at_utc < end_utc
            )
        ).all()
    )
    latest = _latest_classifications(session, [rec.id for rec in recordings])
    freq_labels = {
        f.id: f.label
        for f in session.exec(
            select(Frequency).where(
                Frequency.id.in_({rec.freq_id for rec in recordings})  # type: ignore[attr-defined]
            )
        ).all()
    }

    category_counts: dict[str, int] = {}
    scored: list[tuple[float, Recording, Classification]] = []
    interesting_count = 0
    for rec in recordings:
        verdict = latest.get(rec.id)
        if verdict is None or not verdict.is_interesting:
            continue
        interesting_count += 1
        category_counts[verdict.category.value] = category_counts.get(verdict.category.value, 0) + 1
        weight = CATEGORY_WEIGHTS.get(verdict.category, DEFAULT_WEIGHT)
        scored.append((weight * verdict.confidence, rec, verdict))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_clips = [
        WeeklyTopClip(
            recording_id=rec.id,
            local_time=rec.started_at_utc.astimezone(tz).strftime("%a %H:%M"),
            freq_label=freq_labels.get(rec.freq_id, "an unknown frequency"),
            category=verdict.category.value,
            reason=verdict.reason,
        )
        for _, rec, verdict in scored[:TOP_CLIPS_LIMIT]
    ]

    return WeeklyEmailInput(
        week_start=week_start,
        week_end=week_end,
        total_count=len(recordings),
        interesting_count=interesting_count,
        category_counts=category_counts,
        top_clips=top_clips,
        narrative_text=_week_narrative(session, week_start=week_start, week_end=week_end),
    )


def _dashboard_link(base_url: str | None, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}" if base_url else path


def _clip_list_item(clip: WeeklyTopClip, base_url: str | None) -> str:
    href = escape(_dashboard_link(base_url, f"/clips/?clip={clip.recording_id}"))
    when_where = escape(f"{clip.local_time} on {clip.freq_label}")
    reason = escape(clip.reason)
    return f'<li><a href="{href}">{when_where}</a> — {reason}</li>'


def render_weekly_email(
    result: WeeklyEmailInput, *, station_name: str | None, base_url: str | None
) -> tuple[str, str]:
    """Returns ``(subject, html_body)``."""
    name = station_name or "your listening post"
    subject = (
        f"{station_name or 'Skywatch'} — the week of "
        f"{result.week_start.strftime('%-d %B')} to {result.week_end.strftime('%-d %B')}"
    )

    if result.total_count == 0:
        body_html = "<p>It was a quiet week on the air — nothing was recorded.</p>"
    else:
        narrative_html = f"<p>{escape(result.narrative_text)}</p>" if result.narrative_text else ""
        stats_html = (
            f"<p><strong>{result.total_count}</strong> transmissions heard, "
            f"<strong>{result.interesting_count}</strong> worth a second listen.</p>"
        )
        clips_html = ""
        if result.top_clips:
            items = "".join(_clip_list_item(c, base_url) for c in result.top_clips)
            clips_html = f"<h2>This week's clips</h2><ul>{items}</ul>"
        body_html = narrative_html + stats_html + clips_html

    html = (
        '<html><body style="font-family: sans-serif; color: #222;">'
        f"<h1>{escape(name)}</h1>"
        f"{body_html}"
        f'<p><a href="{escape(_dashboard_link(base_url, "/"))}">Open the dashboard</a></p>'
        "</body></html>"
    )
    return subject, html


def send_email(cfg: EmailDigestConfig, *, subject: str, html_body: str) -> None:
    """Send one HTML email via SMTP. Raises on any failure — callers isolate it."""
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = cfg.smtp_from or cfg.smtp_username or "skywatch@localhost"
    message["To"] = ", ".join(cfg.to)
    message.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if cfg.smtp_username and cfg.smtp_password:
            smtp.login(cfg.smtp_username, cfg.smtp_password)
        smtp.sendmail(message["From"], list(cfg.to), message.as_string())
