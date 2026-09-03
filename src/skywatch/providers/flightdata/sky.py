"""Live 'what's overhead' positions: community aggregators with an OpenSky fallback.

Three keyless, non-commercial-OK aggregators (airplanes.live, adsb.lol,
adsb.fi) each serve live positions within a radius under a slightly
different JSON shape; a per-source failure falls through to the next, and
OpenSky's bbox states endpoint is the last resort when all three are down.
Every shape normalizes to :class:`SkyAircraft`, and each leg carries an
identifying User-Agent as the aggregators' usage policies ask for.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from sqlmodel import Session

from skywatch.db.enums import ApiProvider
from skywatch.pipeline import budget
from skywatch.providers.flightdata.opensky import (
    M_TO_FT,
    MS_TO_KT,
    OpenSkyClient,
    OpenSkyError,
    StateVector,
    bbox_around,
)

logger = logging.getLogger(__name__)

NM_TO_KM = 1.852

IDENTIFYING_USER_AGENT = (
    "skywatch-station/1.0 (+https://github.com/; receive-only aviation monitor)"
)


class SkySource(StrEnum):
    """Which chain leg answered a /sky lookup."""

    AIRPLANES_LIVE = "airplanes_live"
    ADSB_LOL = "adsb_lol"
    ADSB_FI = "adsb_fi"
    OPENSKY = "opensky"


ATTRIBUTIONS: dict[SkySource, str] = {
    SkySource.AIRPLANES_LIVE: "Aircraft positions courtesy of airplanes.live.",
    SkySource.ADSB_LOL: "Aircraft positions © adsb.lol contributors, ODbL 1.0.",
    SkySource.ADSB_FI: "Aircraft positions courtesy of adsb.fi.",
    SkySource.OPENSKY: "Aircraft positions courtesy of The OpenSky Network.",
}


@dataclass(frozen=True)
class SkyAircraft:
    """One live position, normalized to a single shape regardless of source."""

    hex: str
    callsign: str | None
    lat: float | None
    lon: float | None
    alt_ft: float | None
    gs_kt: float | None
    track: float | None
    type: str | None
    registration: str | None
    squawk: str | None
    seen_s: float | None


@dataclass(frozen=True)
class SkyResult:
    """What the source chain produced: which leg answered, and with what."""

    source: SkySource | None
    aircraft: list[SkyAircraft]
    attribution: str | None


def _normalize_tar1090_entry(entry: dict) -> SkyAircraft | None:
    """Normalize one dump1090/tar1090-shaped entry (the ``ac``/``aircraft`` shape
    shared by airplanes.live, adsb.lol, and adsb.fi)."""
    hex_ = entry.get("hex")
    if not hex_:
        return None
    alt_baro = entry.get("alt_baro")
    if alt_baro == "ground":
        alt_ft: float | None = 0.0
    elif isinstance(alt_baro, int | float):
        alt_ft = float(alt_baro)
    else:
        alt_ft = None
    squawk = entry.get("squawk")
    callsign = (entry.get("flight") or "").strip() or None
    return SkyAircraft(
        hex=str(hex_).lower(),
        callsign=callsign,
        lat=entry.get("lat"),
        lon=entry.get("lon"),
        alt_ft=alt_ft,
        gs_kt=entry.get("gs"),
        track=entry.get("track"),
        type=entry.get("t"),
        registration=entry.get("r"),
        squawk=str(squawk) if squawk is not None else None,
        seen_s=entry.get("seen"),
    )


def parse_airplanes_live(payload: dict) -> list[SkyAircraft]:
    entries = payload.get("ac") or []
    return [a for e in entries if (a := _normalize_tar1090_entry(e)) is not None]


def parse_adsb_lol(payload: dict) -> list[SkyAircraft]:
    entries = payload.get("ac") or []
    return [a for e in entries if (a := _normalize_tar1090_entry(e)) is not None]


def parse_adsb_fi(payload: dict) -> list[SkyAircraft]:
    entries = payload.get("aircraft") or []
    return [a for e in entries if (a := _normalize_tar1090_entry(e)) is not None]


def parse_opensky_states(states: list[StateVector]) -> list[SkyAircraft]:
    """OpenSky state vectors carry no track/type/registration/squawk; those
    fields are simply null on this leg."""
    aircraft: list[SkyAircraft] = []
    for state in states:
        if state.lat is None or state.lon is None:
            continue
        aircraft.append(
            SkyAircraft(
                hex=state.icao24,
                callsign=state.callsign,
                lat=state.lat,
                lon=state.lon,
                alt_ft=state.baro_alt_m * M_TO_FT if state.baro_alt_m is not None else None,
                gs_kt=state.velocity_ms * MS_TO_KT if state.velocity_ms is not None else None,
                track=None,
                type=None,
                registration=None,
                squawk=None,
                seen_s=None,
            )
        )
    return aircraft


class SkySourceChain:
    """Tries the community aggregators in order, falling back to OpenSky.

    A per-source failure (timeout, HTTP error, unparseable body) falls
    through to the next leg; when every leg is unavailable ``fetch`` returns
    an honest empty result rather than raising.
    """

    def __init__(
        self,
        *,
        http: httpx.Client,
        airplanes_live_base_url: str,
        adsb_lol_base_url: str,
        adsb_fi_base_url: str,
        radius_nm: float,
        opensky_client: OpenSkyClient | None,
        opensky_daily_cap: int,
        user_agent: str = IDENTIFYING_USER_AGENT,
    ) -> None:
        self._http = http
        self._radius_nm = radius_nm
        self._opensky_client = opensky_client
        self._opensky_daily_cap = opensky_daily_cap
        self._user_agent = user_agent
        self._community_legs: list[tuple[SkySource, str, Callable[[dict], list[SkyAircraft]]]] = [
            (
                SkySource.AIRPLANES_LIVE,
                f"{airplanes_live_base_url}/v2/point",
                parse_airplanes_live,
            ),
            (SkySource.ADSB_LOL, f"{adsb_lol_base_url}/v2/point", parse_adsb_lol),
            (SkySource.ADSB_FI, f"{adsb_fi_base_url}/api/v3/lat", parse_adsb_fi),
        ]

    def _url(self, source: SkySource, url_prefix: str, lat: float, lon: float) -> str:
        if source is SkySource.ADSB_FI:
            return f"{url_prefix}/{lat}/lon/{lon}/dist/{self._radius_nm}"
        return f"{url_prefix}/{lat}/{lon}/{self._radius_nm}"

    def _fetch_community_leg(self, source: SkySource, url: str, parser) -> list[SkyAircraft] | None:
        try:
            response = self._http.get(url, headers={"User-Agent": self._user_agent})
            response.raise_for_status()
            return parser(response.json())
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.warning("sky source %s unavailable: %s", source.value, exc)
            return None

    def _fetch_opensky_leg(
        self, session: Session, lat: float, lon: float
    ) -> list[SkyAircraft] | None:
        if self._opensky_client is None:
            return None
        today = datetime.now(UTC).date()
        if budget.remaining(session, ApiProvider.OPENSKY, today, self._opensky_daily_cap) <= 0:
            logger.warning("sky opensky leg skipped: daily credit cap reached")
            return None
        box = bbox_around(lat, lon, self._radius_nm * NM_TO_KM)
        try:
            states = self._opensky_client.states(int(datetime.now(UTC).timestamp()), box)
        except OpenSkyError as exc:
            logger.warning("sky opensky leg unavailable: %s", exc)
            return None
        budget.record_call(session, ApiProvider.OPENSKY, today)
        return parse_opensky_states(states)

    def fetch(self, session: Session, *, lat: float, lon: float) -> SkyResult:
        for source, url_prefix, parser in self._community_legs:
            url = self._url(source, url_prefix, lat, lon)
            aircraft = self._fetch_community_leg(source, url, parser)
            if aircraft is not None:
                return SkyResult(source=source, aircraft=aircraft, attribution=ATTRIBUTIONS[source])

        aircraft = self._fetch_opensky_leg(session, lat, lon)
        if aircraft is not None:
            return SkyResult(
                source=SkySource.OPENSKY,
                aircraft=aircraft,
                attribution=ATTRIBUTIONS[SkySource.OPENSKY],
            )

        return SkyResult(source=None, aircraft=[], attribution=None)
