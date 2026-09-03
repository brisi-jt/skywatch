"""The /sky route: a short-lived cache over the source chain, plus the
clip-fusion join that marks which live aircraft the station has heard.
"""

import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from sqlmodel import Session, select

from skywatch.api.schemas import Link, SkyAircraftResource, SkyResponse
from skywatch.db.models import AircraftMatch, Recording, utcnow
from skywatch.providers.flightdata.opensky import OpenSkyClient
from skywatch.providers.flightdata.sky import SkyResult, SkySourceChain
from skywatch.settings import Settings

# Multi-tab dashboards and a 10 s frontend poll would otherwise multiply
# requests against the upstream aggregators; this window collapses them
# into one upstream fetch regardless of how many clients are watching.
CACHE_TTL_S = 8.0


class SkyService:
    """Caches the source chain's result for a short, fixed window."""

    def __init__(
        self,
        chain: SkySourceChain,
        *,
        cache_ttl_s: float = CACHE_TTL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._chain = chain
        self._cache_ttl_s = cache_ttl_s
        self._clock = clock
        self._cached: SkyResult | None = None
        self._cached_at: float = -math.inf

    def fetch(self, session: Session, *, lat: float | None, lon: float | None) -> SkyResult:
        if lat is None or lon is None:
            return SkyResult(source=None, aircraft=[], attribution=None)
        now = self._clock()
        if self._cached is not None and (now - self._cached_at) < self._cache_ttl_s:
            return self._cached
        result = self._chain.fetch(session, lat=lat, lon=lon)
        self._cached = result
        self._cached_at = now
        return result


def build_sky_service(settings: Settings, *, http: httpx.Client | None = None) -> SkyService:
    """Wire a SkyService from settings; OpenSky fallback is omitted when
    credentials are not configured (the community legs still work)."""
    opensky_client = None
    if settings.opensky_client_id and settings.opensky_client_secret:
        opensky_client = OpenSkyClient(settings.opensky_client_id, settings.opensky_client_secret)
    chain = SkySourceChain(
        http=http or httpx.Client(timeout=10.0),
        airplanes_live_base_url=settings.sky.airplanes_live_base_url,
        adsb_lol_base_url=settings.sky.adsb_lol_base_url,
        adsb_fi_base_url=settings.sky.adsb_fi_base_url,
        radius_nm=settings.sky.radius_nm,
        opensky_client=opensky_client,
        opensky_daily_cap=settings.sky.opensky_daily_cap,
    )
    return SkyService(chain)


def _heard_recording_ids(
    session: Session, hexes: set[str], *, window_hours: int, now: datetime
) -> dict[str, list[int]]:
    """recording ids each hex was matched to within the heard window, newest first."""
    if not hexes:
        return {}
    cutoff = now - timedelta(hours=window_hours)
    rows = session.exec(
        select(AircraftMatch.icao24, AircraftMatch.recording_id, Recording.started_at_utc)
        .join(Recording, Recording.id == AircraftMatch.recording_id)  # type: ignore[arg-type]
        .where(
            AircraftMatch.icao24.in_(hexes),  # type: ignore[attr-defined]
            Recording.started_at_utc >= cutoff,
        )
        .order_by(Recording.started_at_utc.desc())  # type: ignore[arg-type,union-attr]
    ).all()
    heard: dict[str, list[int]] = {}
    for icao24, recording_id, _started_at in rows:
        heard.setdefault(icao24.lower(), []).append(recording_id)
    return heard


def build_sky_response(
    session: Session, sky_service: SkyService, *, settings: Settings
) -> SkyResponse:
    result = sky_service.fetch(session, lat=settings.receiver.lat, lon=settings.receiver.lon)
    hexes = {a.hex.lower() for a in result.aircraft}
    heard = _heard_recording_ids(
        session, hexes, window_hours=settings.sky.heard_window_hours, now=utcnow()
    )
    aircraft = [
        SkyAircraftResource(
            hex=a.hex,
            callsign=a.callsign,
            lat=a.lat,
            lon=a.lon,
            alt_ft=a.alt_ft,
            gs_kt=a.gs_kt,
            track=a.track,
            type=a.type,
            registration=a.registration,
            squawk=a.squawk,
            seen_s=a.seen_s,
            heard_recently=a.hex.lower() in heard,
            heard_recording_ids=heard.get(a.hex.lower(), []),
        )
        for a in result.aircraft
    ]
    return SkyResponse(
        source=result.source,
        attribution=result.attribution,
        radius_nm=settings.sky.radius_nm,
        generated_at=utcnow(),
        aircraft=aircraft,
        links={"self": Link(href="/sky")},
    )
