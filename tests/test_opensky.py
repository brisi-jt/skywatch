"""OpenSky flight-data provider tests: OAuth flow, caching, credits, ranking."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlmodel import select

from skywatch.db.enums import ApiProvider, FrequencyCategory, RecordingStage
from skywatch.db.models import AircraftMatch, ApiUsage, Frequency, Recording
from skywatch.pipeline import budget
from skywatch.providers.flightdata.airlines import AirlineDirectory, flight_number_guess
from skywatch.providers.flightdata.opensky import (
    STATES_URL,
    TOKEN_URL,
    OpenSkyClient,
    OpenSkyEnricher,
    OpenSkyError,
    OpenSkyRateLimited,
    StateVector,
    bbox_around,
    rank_candidates,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RECEIVER_LAT, RECEIVER_LON = 51.5, -0.1


def _token_response(expires_in=1800):
    return httpx.Response(200, json={"access_token": "tok", "expires_in": expires_in})


def _states_payload():
    # index: 0 icao24, 1 callsign, 5 lon, 6 lat, 7 baro alt (m), 8 on_ground, 9 velocity (m/s)
    def state(icao, callsign, lon, lat, alt_m, on_ground=False, vel=120.0):
        row = [icao, callsign, "United Kingdom", None, None, lon, lat, alt_m, on_ground, vel]
        row += [None] * 7
        return row

    return {
        "time": 1_752_600_000,
        "states": [
            state("4009f9", "BAW472  ", 0.05, 51.70, 900.0),  # close, low — tower fit
            state("4ca7b4", "RYR815B ", 0.30, 51.90, 3500.0),  # further out
            state("a1b2c3", "EZY45XY ", 0.02, 51.69, 11000.0),  # close but high
        ],
    }


class TestBBox:
    def test_bbox_spans_radius(self):
        box = bbox_around(RECEIVER_LAT, RECEIVER_LON, radius_km=40)
        assert box.lamin < RECEIVER_LAT < box.lamax
        assert box.lomin < RECEIVER_LON < box.lomax
        # 40 km of latitude is ~0.36 degrees
        assert box.lamax - box.lamin == pytest.approx(2 * 40 / 111.32, rel=0.01)
        # longitude degrees are shorter at 51.7N
        assert (box.lomax - box.lomin) > (box.lamax - box.lamin)


class TestClient:
    @respx.mock
    def test_token_fetch_and_bearer(self):
        token_route = respx.post(TOKEN_URL).mock(return_value=_token_response())
        states_route = respx.get(STATES_URL).mock(
            return_value=httpx.Response(200, json=_states_payload())
        )
        client = OpenSkyClient("cid", "secret")
        states = client.states(1_752_600_000, bbox_around(RECEIVER_LAT, RECEIVER_LON, 40))
        assert len(states) == 3
        assert isinstance(states[0], StateVector)
        assert token_route.call_count == 1
        sent = states_route.calls.last.request
        assert sent.headers["authorization"] == "Bearer tok"
        assert "lamin" in str(sent.url)
        body = token_route.calls.last.request.content.decode()
        assert "grant_type=client_credentials" in body
        assert "client_id=cid" in body

    @respx.mock
    def test_token_cached_within_lifetime(self):
        token_route = respx.post(TOKEN_URL).mock(return_value=_token_response())
        respx.get(STATES_URL).mock(return_value=httpx.Response(200, json=_states_payload()))
        client = OpenSkyClient("cid", "secret")
        box = bbox_around(RECEIVER_LAT, RECEIVER_LON, 40)
        client.states(1, box)
        client.states(2, box)
        assert token_route.call_count == 1

    @respx.mock
    def test_token_refreshed_after_expiry(self):
        now = {"t": 1000.0}
        token_route = respx.post(TOKEN_URL).mock(return_value=_token_response(expires_in=1800))
        respx.get(STATES_URL).mock(return_value=httpx.Response(200, json=_states_payload()))
        client = OpenSkyClient("cid", "secret", clock=lambda: now["t"])
        box = bbox_around(RECEIVER_LAT, RECEIVER_LON, 40)
        client.states(1, box)
        now["t"] += 1800 - 30  # inside the refresh margin of the 30-minute lifetime
        client.states(2, box)
        assert token_route.call_count == 2

    @respx.mock
    def test_429_raises_rate_limited(self):
        respx.post(TOKEN_URL).mock(return_value=_token_response())
        respx.get(STATES_URL).mock(return_value=httpx.Response(429, text="slow down"))
        client = OpenSkyClient("cid", "secret")
        with pytest.raises(OpenSkyRateLimited):
            client.states(1, bbox_around(RECEIVER_LAT, RECEIVER_LON, 40))

    @respx.mock
    def test_server_error_raises(self):
        respx.post(TOKEN_URL).mock(return_value=_token_response())
        respx.get(STATES_URL).mock(return_value=httpx.Response(502, text="bad gateway"))
        client = OpenSkyClient("cid", "secret")
        with pytest.raises(OpenSkyError):
            client.states(1, bbox_around(RECEIVER_LAT, RECEIVER_LON, 40))


def _vectors():
    return [
        StateVector(
            "4009f9",
            "BAW472",
            lat=51.70,
            lon=0.05,
            baro_alt_m=900.0,
            on_ground=False,
            velocity_ms=120.0,
        ),
        StateVector(
            "4ca7b4",
            "RYR815B",
            lat=51.90,
            lon=0.30,
            baro_alt_m=3500.0,
            on_ground=False,
            velocity_ms=140.0,
        ),
        StateVector(
            "a1b2c3",
            "EZY45XY",
            lat=51.69,
            lon=0.02,
            baro_alt_m=11000.0,
            on_ground=False,
            velocity_ms=230.0,
        ),
    ]


class TestRanking:
    def test_tower_prefers_close_and_low(self):
        ranked = rank_candidates(
            _vectors(),
            receiver_lat=RECEIVER_LAT,
            receiver_lon=RECEIVER_LON,
            radius_km=40,
            freq_category=FrequencyCategory.TOWER,
        )
        assert [c.rank for c in ranked] == [1, 2, 3]
        assert ranked[0].state.icao24 == "4009f9"  # close AND low beats close-but-high
        assert ranked[0].match_confidence > ranked[-1].match_confidence
        assert 0.0 <= ranked[-1].match_confidence <= 1.0

    def test_area_control_prefers_high(self):
        ranked = rank_candidates(
            _vectors(),
            receiver_lat=RECEIVER_LAT,
            receiver_lon=RECEIVER_LON,
            radius_km=40,
            freq_category=FrequencyCategory.AREA_CONTROL,
        )
        assert ranked[0].state.icao24 == "a1b2c3"

    def test_positionless_states_dropped_and_limit(self):
        vectors = _vectors() + [
            StateVector(
                "ffffff",
                None,
                lat=None,
                lon=None,
                baro_alt_m=None,
                on_ground=False,
                velocity_ms=None,
            )
        ]
        ranked = rank_candidates(
            vectors,
            receiver_lat=RECEIVER_LAT,
            receiver_lon=RECEIVER_LON,
            radius_km=40,
            freq_category=FrequencyCategory.TOWER,
            limit=2,
        )
        assert len(ranked) == 2


class TestAirlines:
    def test_lookup_from_vendored_data(self):
        directory = AirlineDirectory.load(REPO_ROOT / "content" / "airlines.dat")
        airline = directory.lookup_callsign("BAW472")
        assert airline is not None
        assert airline.name == "British Airways"
        assert airline.iata == "BA"
        assert flight_number_guess("BAW472", airline) == "BA472"

    def test_unknown_prefix(self):
        directory = AirlineDirectory.load(REPO_ROOT / "content" / "airlines.dat")
        assert directory.lookup_callsign("XQZ999") is None
        assert directory.lookup_callsign(None) is None

    def test_no_digits_means_no_guess(self):
        directory = AirlineDirectory.load(REPO_ROOT / "content" / "airlines.dat")
        airline = directory.lookup_callsign("BAW472")
        assert flight_number_guess("BAWXX", airline) is None


def _recording(session, *, category=FrequencyCategory.TOWER, started=None):
    freq = session.exec(select(Frequency)).first()
    if freq is None:
        freq = Frequency(
            label="Stansted Tower",
            mhz=123.805,
            facility="London Stansted",
            category=category,
            tuner_group=1,
        )
        session.add(freq)
        session.commit()
    started = started or datetime.now(UTC)
    rec = Recording(
        freq_id=freq.id,
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=8),
        duration_s=8.0,
        file_path="recordings/x.mp3",
        sample_rate=8000,
        stage=RecordingStage.CAPTURED,
    )
    session.add(rec)
    session.commit()
    return rec, freq


def _enricher(cap=3000, bucket_seconds=30):
    directory = AirlineDirectory.load(REPO_ROOT / "content" / "airlines.dat")
    client = OpenSkyClient("cid", "secret")
    return OpenSkyEnricher(
        client,
        receiver_lat=RECEIVER_LAT,
        receiver_lon=RECEIVER_LON,
        radius_km=40,
        bucket_seconds=bucket_seconds,
        daily_credit_cap=cap,
        airlines=directory,
    )


class TestEnricher:
    @respx.mock
    def test_enrich_writes_ranked_matches_and_credits(self, session):
        respx.post(TOKEN_URL).mock(return_value=_token_response())
        respx.get(STATES_URL).mock(return_value=httpx.Response(200, json=_states_payload()))
        rec, freq = _recording(session)
        enricher = _enricher()
        matches = enricher.enrich(session, rec, freq.category)
        session.commit()
        assert len(matches) == 3
        rows = session.exec(select(AircraftMatch)).all()
        assert {r.rank for r in rows} == {1, 2, 3}
        top = next(r for r in rows if r.rank == 1)
        assert top.icao24 == "4009f9"
        assert top.callsign == "BAW472"
        assert top.airline_name == "British Airways"
        assert top.flight_number_guess == "BA472"
        assert top.distance_km < 5
        assert top.alt_ft == pytest.approx(900.0 * 3.28084)
        assert top.gs_kt == pytest.approx(120.0 * 1.94384)
        usage = session.exec(select(ApiUsage)).one()
        assert usage.provider is ApiProvider.OPENSKY
        assert usage.calls == 1

    @respx.mock
    def test_bucket_cache_shares_one_call(self, session):
        respx.post(TOKEN_URL).mock(return_value=_token_response())
        states_route = respx.get(STATES_URL).mock(
            return_value=httpx.Response(200, json=_states_payload())
        )
        started = datetime.now(UTC)
        rec1, freq = _recording(session, started=started)
        rec2, _ = _recording(session, started=started + timedelta(seconds=3))
        enricher = _enricher(bucket_seconds=600)
        enricher.enrich(session, rec1, freq.category)
        enricher.enrich(session, rec2, freq.category)
        session.commit()
        assert states_route.call_count == 1
        assert budget.calls_today(session, ApiProvider.OPENSKY, datetime.now(UTC).date()) == 1

    @respx.mock
    def test_credit_cap_skips_without_calling(self, session):
        states_route = respx.get(STATES_URL).mock(
            return_value=httpx.Response(200, json=_states_payload())
        )
        respx.post(TOKEN_URL).mock(return_value=_token_response())
        rec, freq = _recording(session)
        enricher = _enricher(cap=0)
        matches = enricher.enrich(session, rec, freq.category)
        assert matches == []
        assert states_route.call_count == 0
