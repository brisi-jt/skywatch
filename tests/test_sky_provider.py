"""Sky live-position provider: per-source normalizers and the fallback chain.

All external HTTP is respx-mocked; there is no live network in this suite.
"""

from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlmodel import select

from skywatch.db.enums import ApiProvider
from skywatch.db.models import ApiUsage
from skywatch.pipeline import budget
from skywatch.providers.flightdata.opensky import OpenSkyClient, StateVector
from skywatch.providers.flightdata.sky import (
    SkyAircraft,
    SkySource,
    SkySourceChain,
    parse_adsb_fi,
    parse_adsb_lol,
    parse_airplanes_live,
    parse_opensky_states,
)

RECEIVER_LAT, RECEIVER_LON = 51.5, -0.1
AIRPLANES_LIVE_BASE = "https://api.airplanes.live"
ADSB_LOL_BASE = "https://api.adsb.lol"
ADSB_FI_BASE = "https://opendata.adsb.fi"
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"


def _airplanes_live_url(radius_nm=25):
    return f"{AIRPLANES_LIVE_BASE}/v2/point/{RECEIVER_LAT}/{RECEIVER_LON}/{radius_nm}"


def _adsb_lol_url(radius_nm=25):
    return f"{ADSB_LOL_BASE}/v2/point/{RECEIVER_LAT}/{RECEIVER_LON}/{radius_nm}"


def _adsb_fi_url(radius_nm=25):
    return f"{ADSB_FI_BASE}/api/v3/lat/{RECEIVER_LAT}/lon/{RECEIVER_LON}/dist/{radius_nm}"


def _token_response():
    return httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})


class TestAirplanesLiveNormalizer:
    def test_parses_ac_entries(self):
        payload = {
            "ac": [
                {
                    "hex": "4009f9",
                    "flight": "BAW472  ",
                    "lat": 51.70,
                    "lon": 0.05,
                    "alt_baro": 3200,
                    "gs": 180.0,
                    "track": 95.0,
                    "t": "A320",
                    "r": "G-EUYW",
                    "squawk": "0451",
                    "seen": 1.2,
                }
            ]
        }
        aircraft = parse_airplanes_live(payload)
        assert aircraft == [
            SkyAircraft(
                hex="4009f9",
                callsign="BAW472",
                lat=51.70,
                lon=0.05,
                alt_ft=3200.0,
                gs_kt=180.0,
                track=95.0,
                type="A320",
                registration="G-EUYW",
                squawk="0451",
                seen_s=1.2,
            )
        ]

    def test_ground_altitude_normalizes_to_zero(self):
        payload = {"ac": [{"hex": "abc123", "alt_baro": "ground"}]}
        aircraft = parse_airplanes_live(payload)
        assert aircraft[0].alt_ft == 0.0

    def test_missing_hex_dropped(self):
        payload = {"ac": [{"flight": "NOHEX"}]}
        assert parse_airplanes_live(payload) == []

    def test_empty_or_missing_ac_key(self):
        assert parse_airplanes_live({}) == []
        assert parse_airplanes_live({"ac": None}) == []


class TestAdsbLolNormalizer:
    def test_parses_ac_entries(self):
        payload = {"ac": [{"hex": "a1b2c3", "flight": "RYR1", "lat": 51.9, "lon": 0.3}]}
        aircraft = parse_adsb_lol(payload)
        assert aircraft[0].hex == "a1b2c3"
        assert aircraft[0].callsign == "RYR1"


class TestAdsbFiNormalizer:
    def test_parses_aircraft_entries(self):
        payload = {
            "aircraft": [
                {
                    "hex": "d1e2f3",
                    "flight": "EZY45XY",
                    "lat": 51.69,
                    "lon": 0.02,
                    "alt_baro": 11000,
                    "gs": 250.0,
                }
            ]
        }
        aircraft = parse_adsb_fi(payload)
        assert aircraft[0].hex == "d1e2f3"
        assert aircraft[0].callsign == "EZY45XY"
        assert aircraft[0].alt_ft == 11000.0

    def test_no_aircraft_key(self):
        assert parse_adsb_fi({}) == []


class TestOpenSkyNormalizer:
    def test_parses_state_vectors(self):
        states = [
            StateVector(
                icao24="4009f9",
                callsign="BAW472",
                lat=51.70,
                lon=0.05,
                baro_alt_m=900.0,
                on_ground=False,
                velocity_ms=120.0,
            )
        ]
        aircraft = parse_opensky_states(states)
        assert aircraft[0].hex == "4009f9"
        assert aircraft[0].callsign == "BAW472"
        assert aircraft[0].alt_ft == pytest.approx(900.0 * 3.28084)
        assert aircraft[0].gs_kt == pytest.approx(120.0 * 1.94384)
        assert aircraft[0].track is None
        assert aircraft[0].registration is None

    def test_positionless_states_dropped(self):
        states = [
            StateVector(
                icao24="ffffff",
                callsign=None,
                lat=None,
                lon=None,
                baro_alt_m=None,
                on_ground=False,
                velocity_ms=None,
            )
        ]
        assert parse_opensky_states(states) == []


def _chain(**overrides):
    kwargs = dict(
        http=httpx.Client(),
        airplanes_live_base_url=AIRPLANES_LIVE_BASE,
        adsb_lol_base_url=ADSB_LOL_BASE,
        adsb_fi_base_url=ADSB_FI_BASE,
        radius_nm=25,
        opensky_client=OpenSkyClient("cid", "secret"),
        opensky_daily_cap=500,
    )
    kwargs.update(overrides)
    return SkySourceChain(**kwargs)


class TestSourceChain:
    @respx.mock
    def test_primary_success_short_circuits(self, session):
        route = respx.get(_airplanes_live_url()).mock(
            return_value=httpx.Response(200, json={"ac": [{"hex": "aaaaaa", "flight": "TST1"}]})
        )
        lol_route = respx.get(_adsb_lol_url()).mock(return_value=httpx.Response(200, json={}))
        chain = _chain()
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.source is SkySource.AIRPLANES_LIVE
        assert [a.hex for a in result.aircraft] == ["aaaaaa"]
        assert route.call_count == 1
        assert lol_route.call_count == 0

    @respx.mock
    def test_primary_failure_falls_through_to_secondary(self, session):
        respx.get(_airplanes_live_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_lol_url()).mock(
            return_value=httpx.Response(200, json={"ac": [{"hex": "bbbbbb"}]})
        )
        chain = _chain()
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.source is SkySource.ADSB_LOL
        assert [a.hex for a in result.aircraft] == ["bbbbbb"]

    @respx.mock
    def test_falls_through_community_sources_to_opensky(self, session):
        respx.get(_airplanes_live_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_lol_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_fi_url()).mock(return_value=httpx.Response(500))
        respx.post(TOKEN_URL).mock(return_value=_token_response())
        respx.get(STATES_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "states": [
                        ["4009f9", "BAW472  ", None, None, None, 0.05, 51.70, 900.0, False, 120.0]
                        + [None] * 7
                    ]
                },
            )
        )
        chain = _chain()
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.source is SkySource.OPENSKY
        assert [a.hex for a in result.aircraft] == ["4009f9"]
        usage = session.exec(select(ApiUsage)).one()
        assert usage.calls == 1

    @respx.mock
    def test_all_sources_down_returns_honest_empty(self, session):
        respx.get(_airplanes_live_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_lol_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_fi_url()).mock(return_value=httpx.Response(500))
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(500))
        chain = _chain()
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.source is None
        assert result.aircraft == []
        assert result.attribution is None

    @respx.mock
    def test_no_opensky_client_skips_fallback_leg(self, session):
        respx.get(_airplanes_live_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_lol_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_fi_url()).mock(return_value=httpx.Response(500))
        chain = _chain(opensky_client=None)
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.source is None

    @respx.mock
    def test_credit_cap_blocks_opensky_leg_without_calling(self, session):
        respx.get(_airplanes_live_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_lol_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_fi_url()).mock(return_value=httpx.Response(500))
        token_route = respx.post(TOKEN_URL).mock(return_value=_token_response())
        today = datetime.now(UTC).date()
        budget.record_call(session, ApiProvider.OPENSKY, today, count=500)
        session.commit()
        chain = _chain(opensky_daily_cap=500)
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.source is None
        assert token_route.call_count == 0

    @respx.mock
    def test_credit_cap_is_independent_of_enrichment_cap(self, session):
        # A cap of 500 on the sky leg still permits calls while under 500,
        # even though enrichment's own cap (elsewhere, e.g. 3000) is unrelated.
        respx.get(_airplanes_live_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_lol_url()).mock(return_value=httpx.Response(500))
        respx.get(_adsb_fi_url()).mock(return_value=httpx.Response(500))
        respx.post(TOKEN_URL).mock(return_value=_token_response())
        respx.get(STATES_URL).mock(return_value=httpx.Response(200, json={"states": []}))
        today = datetime.now(UTC).date()
        budget.record_call(session, ApiProvider.OPENSKY, today, count=100)
        session.commit()
        chain = _chain(opensky_daily_cap=500)
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.source is SkySource.OPENSKY

    @respx.mock
    def test_attribution_present_for_each_source(self, session):
        respx.get(_airplanes_live_url()).mock(
            return_value=httpx.Response(200, json={"ac": [{"hex": "aaaaaa"}]})
        )
        chain = _chain()
        result = chain.fetch(session, lat=RECEIVER_LAT, lon=RECEIVER_LON)
        assert result.attribution
