"""OpenSky Network flight-data provider.

Authentication is OAuth2 client-credentials only; access tokens live 30
minutes and are refreshed just before expiry. State queries are bounded to
a bbox around the receiver (a bbox this size costs one credit per call
against the daily allowance) and cached in time buckets so clips captured
within the same window share one lookup. Historical lookback is capped at
one hour by OpenSky, which is why enrichment runs at capture time.
"""

import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlmodel import Session, delete

from skywatch.db.enums import ApiProvider, FlightDataSource, FrequencyCategory
from skywatch.db.models import AircraftMatch, Recording, utcnow
from skywatch.pipeline import budget
from skywatch.providers.flightdata.airlines import AirlineDirectory, flight_number_guess

logger = logging.getLogger(__name__)

TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"
TOKEN_REFRESH_MARGIN_S = 60.0

M_TO_FT = 3.28084
MS_TO_KT = 1.94384
KM_PER_DEG_LAT = 111.32


class OpenSkyError(RuntimeError):
    """A lookup failed; safe to retry after a backoff."""


class OpenSkyRateLimited(OpenSkyError):
    """OpenSky returned 429; back off before the next call."""


@dataclass(frozen=True)
class BoundingBox:
    lamin: float
    lamax: float
    lomin: float
    lomax: float


def bbox_around(lat: float, lon: float, radius_km: float) -> BoundingBox:
    dlat = radius_km / KM_PER_DEG_LAT
    dlon = radius_km / (KM_PER_DEG_LAT * max(0.1, math.cos(math.radians(lat))))
    return BoundingBox(lamin=lat - dlat, lamax=lat + dlat, lomin=lon - dlon, lomax=lon + dlon)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class StateVector:
    """The fields of an OpenSky state vector the station cares about."""

    icao24: str
    callsign: str | None
    lat: float | None
    lon: float | None
    baro_alt_m: float | None
    on_ground: bool
    velocity_ms: float | None


class OpenSkyClient:
    """Authenticated, token-refreshing HTTP client for the states endpoint."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        http: httpx.Client | None = None,
        token_url: str = TOKEN_URL,
        states_url: str = STATES_URL,
        clock=time.time,
        timeout_s: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http or httpx.Client(timeout=timeout_s)
        self._token_url = token_url
        self._states_url = states_url
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def access_token(self) -> str:
        if self._token is None or self._clock() >= self._token_expires_at:
            try:
                response = self._http.post(
                    self._token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                )
                response.raise_for_status()
                payload = response.json()
                self._token = payload["access_token"]
                expires_in = float(payload.get("expires_in", 1800))
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise OpenSkyError(f"token request failed: {exc}") from exc
            self._token_expires_at = self._clock() + expires_in - TOKEN_REFRESH_MARGIN_S
        return self._token

    def states(self, at_ts: int, box: BoundingBox) -> list[StateVector]:
        try:
            response = self._http.get(
                self._states_url,
                params={
                    "time": at_ts,
                    "lamin": round(box.lamin, 4),
                    "lamax": round(box.lamax, 4),
                    "lomin": round(box.lomin, 4),
                    "lomax": round(box.lomax, 4),
                },
                headers={"Authorization": f"Bearer {self.access_token()}"},
            )
        except httpx.HTTPError as exc:
            raise OpenSkyError(f"states request failed: {exc}") from exc
        if response.status_code == 429:
            raise OpenSkyRateLimited("opensky rate limit hit (429)")
        if response.status_code >= 400:
            raise OpenSkyError(f"states request returned {response.status_code}")
        try:
            rows = response.json().get("states") or []
        except ValueError as exc:
            raise OpenSkyError(f"states response unparseable: {exc}") from exc
        vectors: list[StateVector] = []
        for row in rows:
            callsign = (row[1] or "").strip() or None
            vectors.append(
                StateVector(
                    icao24=row[0],
                    callsign=callsign,
                    lon=row[5],
                    lat=row[6],
                    baro_alt_m=row[7],
                    on_ground=bool(row[8]),
                    velocity_ms=row[9],
                )
            )
        return vectors


@dataclass(frozen=True)
class RankedCandidate:
    state: StateVector
    distance_km: float
    match_confidence: float
    rank: int


def _facility_fit(category: FrequencyCategory, alt_ft: float | None, on_ground: bool) -> float:
    """How plausibly an aircraft at this altitude is talking on this facility."""
    if category in (FrequencyCategory.TOWER, FrequencyCategory.GROUND, FrequencyCategory.AIRFIELD):
        if on_ground or (alt_ft is not None and alt_ft < 3_000):
            return 1.0
        if alt_ft is not None and alt_ft < 8_000:
            return 0.6
        return 0.2
    if category in (FrequencyCategory.APPROACH, FrequencyCategory.RADAR):
        if alt_ft is not None and 1_000 <= alt_ft <= 20_000:
            return 1.0
        return 0.4
    if category is FrequencyCategory.AREA_CONTROL:
        if alt_ft is not None and alt_ft > 15_000:
            return 1.0
        if alt_ft is not None and alt_ft > 8_000:
            return 0.6
        return 0.3
    return 0.5  # guard / atis: any altitude is plausible


def rank_candidates(
    states: list[StateVector],
    *,
    receiver_lat: float,
    receiver_lon: float,
    radius_km: float,
    freq_category: FrequencyCategory,
    limit: int = 5,
) -> list[RankedCandidate]:
    """Order aircraft by plausibility for a clip on this frequency."""
    scored: list[tuple[float, float, StateVector]] = []
    for state in states:
        if state.lat is None or state.lon is None:
            continue
        distance = haversine_km(receiver_lat, receiver_lon, state.lat, state.lon)
        proximity = max(0.0, 1.0 - distance / max(radius_km, 1.0))
        alt_ft = state.baro_alt_m * M_TO_FT if state.baro_alt_m is not None else None
        fit = _facility_fit(freq_category, alt_ft, state.on_ground)
        confidence = round(0.6 * proximity + 0.4 * fit, 4)
        scored.append((confidence, distance, state))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        RankedCandidate(
            state=state, distance_km=round(distance, 2), match_confidence=confidence, rank=index + 1
        )
        for index, (confidence, distance, state) in enumerate(scored[:limit])
    ]


class OpenSkyEnricher:
    """Turns one recording into ranked ``aircraft_matches`` rows."""

    def __init__(
        self,
        client: OpenSkyClient,
        *,
        receiver_lat: float,
        receiver_lon: float,
        radius_km: float,
        bucket_seconds: int,
        daily_credit_cap: int,
        airlines: AirlineDirectory,
        candidate_limit: int = 5,
        cache_size: int = 32,
        plane_alert=None,
        aircraft_db=None,
    ) -> None:
        self._client = client
        self._receiver_lat = receiver_lat
        self._receiver_lon = receiver_lon
        self._radius_km = radius_km
        self._bucket_seconds = max(1, bucket_seconds)
        self.daily_credit_cap = daily_credit_cap
        self._airlines = airlines
        self._plane_alert = plane_alert
        self._aircraft_db = aircraft_db
        self._candidate_limit = candidate_limit
        self._cache_size = cache_size
        self._bbox = bbox_around(receiver_lat, receiver_lon, radius_km)
        self._cache: dict[int, list[StateVector]] = {}

    def _bucket(self, at: datetime) -> int:
        epoch = int(at.timestamp())
        return epoch - (epoch % self._bucket_seconds)

    def _states_for(self, session: Session, at: datetime) -> list[StateVector] | None:
        """Bucket-cached states; ``None`` when the credit budget is spent."""
        bucket = self._bucket(at)
        if bucket in self._cache:
            return self._cache[bucket]
        today = datetime.now(UTC).date()
        if budget.remaining(session, ApiProvider.OPENSKY, today, self.daily_credit_cap) <= 0:
            logger.warning("opensky daily credit cap reached; skipping enrichment")
            return None
        states = self._client.states(bucket, self._bbox)
        budget.record_call(session, ApiProvider.OPENSKY, today)
        if len(self._cache) >= self._cache_size:
            self._cache.pop(min(self._cache), None)
        self._cache[bucket] = states
        return states

    def enrich(
        self, session: Session, recording: Recording, freq_category: FrequencyCategory
    ) -> list[AircraftMatch]:
        """Write ranked candidate rows for one recording (idempotent)."""
        states = self._states_for(session, recording.started_at_utc)
        if states is None:
            return []
        session.exec(delete(AircraftMatch).where(AircraftMatch.recording_id == recording.id))
        candidates = rank_candidates(
            states,
            receiver_lat=self._receiver_lat,
            receiver_lon=self._receiver_lon,
            radius_km=self._radius_km,
            freq_category=freq_category,
            limit=self._candidate_limit,
        )
        matches: list[AircraftMatch] = []
        queried_at = utcnow()
        for candidate in candidates:
            state = candidate.state
            airline = self._airlines.lookup_callsign(state.callsign)
            identity = self._aircraft_db.lookup(state.icao24) if self._aircraft_db else None
            match = AircraftMatch(
                recording_id=recording.id,
                source=FlightDataSource.OPENSKY,
                icao24=state.icao24,
                callsign=state.callsign,
                airline_name=airline.name if airline else None,
                flight_number_guess=flight_number_guess(state.callsign, airline),
                registration=identity.registration if identity else None,
                aircraft_type=identity.aircraft_type if identity else None,
                operator_name=identity.operator_name if identity else None,
                lat=state.lat,
                lon=state.lon,
                alt_ft=state.baro_alt_m * M_TO_FT if state.baro_alt_m is not None else None,
                gs_kt=state.velocity_ms * MS_TO_KT if state.velocity_ms is not None else None,
                distance_km=candidate.distance_km,
                match_confidence=candidate.match_confidence,
                rank=candidate.rank,
                queried_at=queried_at,
                alert_category=(
                    self._plane_alert.lookup(state.icao24) if self._plane_alert else None
                ),
            )
            session.add(match)
            matches.append(match)
        return matches
