"""The station's story in numbers: aggregate stats over a recent window.

Everything here is computed fresh from the same rows the daily digest reads
— there is no separate rollup table to keep in sync.
"""

from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from skywatch.api.schemas import (
    AirlineCount,
    DailyMovementCount,
    FrequencyRef,
    HourlyHeatCell,
    Link,
    StatsResponse,
)
from skywatch.api.services.recordings import day_start_utc
from skywatch.db.enums import ClassificationCategory
from skywatch.db.models import AircraftMatch, Classification, Frequency, Recording

STATS_WINDOW_DAYS = 30
TOP_AIRLINES_LIMIT = 10


def _latest_classifications(session: Session, ids: list[int]) -> dict[int, Classification]:
    if not ids:
        return {}
    latest: dict[int, Classification] = {}
    rows = session.exec(
        select(Classification)
        .where(Classification.recording_id.in_(ids))  # type: ignore[attr-defined]
        .order_by(Classification.id)  # type: ignore[arg-type]
    ).all()
    for row in rows:
        latest[row.recording_id] = row
    return latest


def _top_matches(session: Session, ids: list[int]) -> dict[int, AircraftMatch]:
    if not ids:
        return {}
    rows = session.exec(
        select(AircraftMatch).where(
            AircraftMatch.recording_id.in_(ids),  # type: ignore[attr-defined]
            AircraftMatch.rank == 1,
        )
    ).all()
    return {row.recording_id: row for row in rows}


def build_stats(
    session: Session,
    *,
    tz: ZoneInfo,
    today: date | None = None,
    window_days: int = STATS_WINDOW_DAYS,
) -> StatsResponse:
    today = today or datetime.now(tz).date()
    window_start_day = today - timedelta(days=window_days - 1)
    start = day_start_utc(window_start_day, tz)
    end = day_start_utc(today + timedelta(days=1), tz)

    recordings = list(
        session.exec(
            select(Recording)
            .where(Recording.started_at_utc >= start, Recording.started_at_utc < end)
            .order_by(Recording.id)  # type: ignore[arg-type]
        ).all()
    )
    ids = [rec.id for rec in recordings]
    latest = _latest_classifications(session, ids)
    top_matches = _top_matches(session, ids)
    frequencies = {f.id: f for f in session.exec(select(Frequency)).all()}

    daily_buckets: dict[date, dict[str, int]] = {
        window_start_day + timedelta(days=i): {"total": 0, "interesting": 0}
        for i in range(window_days)
    }
    hour_freq_counts: Counter[tuple[int, int]] = Counter()
    airline_counts: Counter[str] = Counter()
    days_with_activity: set[date] = set()
    interesting_count = 0
    go_around_count = 0

    for rec in recordings:
        local_dt = rec.started_at_utc.astimezone(tz)
        local_day = local_dt.date()
        days_with_activity.add(local_day)
        bucket = daily_buckets.get(local_day)
        if bucket is not None:
            bucket["total"] += 1

        verdict = latest.get(rec.id)
        is_interesting = verdict is not None and verdict.is_interesting
        if is_interesting:
            interesting_count += 1
            if bucket is not None:
                bucket["interesting"] += 1
            if verdict.category == ClassificationCategory.GO_AROUND:
                go_around_count += 1

        hour_freq_counts[(local_dt.hour, rec.freq_id)] += 1

        match = top_matches.get(rec.id)
        if match is not None and match.airline_name:
            airline_counts[match.airline_name] += 1

    daily_counts = [
        DailyMovementCount(date=day, total_count=c["total"], interesting_count=c["interesting"])
        for day, c in sorted(daily_buckets.items())
    ]

    heat_freq_ids = {freq_id for (_, freq_id) in hour_freq_counts}
    heat_frequencies = sorted(
        (
            FrequencyRef(id=freq_id, label=frequencies[freq_id].label, mhz=frequencies[freq_id].mhz)
            for freq_id in heat_freq_ids
            if freq_id in frequencies
        ),
        key=lambda f: f.label,
    )
    hourly_heat = [
        HourlyHeatCell(hour=hour, freq_id=freq_id, count=count)
        for (hour, freq_id), count in sorted(hour_freq_counts.items())
    ]
    top_airlines = [
        AirlineCount(airline_name=name, count=count)
        for name, count in airline_counts.most_common(TOP_AIRLINES_LIMIT)
    ]

    total_count = len(recordings)
    interesting_rate = interesting_count / total_count if total_count else None

    return StatsResponse(
        window_days=window_days,
        days_covered=len(days_with_activity),
        total_count=total_count,
        interesting_rate=round(interesting_rate, 4) if interesting_rate is not None else None,
        go_around_count=go_around_count,
        daily_counts=daily_counts,
        heat_frequencies=heat_frequencies,
        hourly_heat=hourly_heat,
        top_airlines=top_airlines,
        links={"self": Link(href="/stats")},
    )
