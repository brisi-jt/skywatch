"""Contract tests for GET /sky: the live 'what's overhead' view.

All external HTTP is respx-mocked against the real default source hosts;
there is no live network in this suite.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx
from sqlmodel import Session, select

from skywatch.db.enums import ApiProvider, FlightDataSource
from skywatch.pipeline import budget
from skywatch.settings import ReceiverSettings, Settings, SkySettings

RECEIVER_LAT, RECEIVER_LON = 51.5, -0.1
# settings.sky.radius_nm is a float field; 25 (int) coerces to 25.0 and
# renders with a decimal point in the built URL.
RADIUS_NM = 25.0
AIRPLANES_LIVE_URL = (
    f"https://api.airplanes.live/v2/point/{RECEIVER_LAT}/{RECEIVER_LON}/{RADIUS_NM}"
)
ADSB_LOL_URL = f"https://api.adsb.lol/v2/point/{RECEIVER_LAT}/{RECEIVER_LON}/{RADIUS_NM}"
ADSB_FI_URL = (
    f"https://opendata.adsb.fi/api/v3/lat/{RECEIVER_LAT}/lon/{RECEIVER_LON}/dist/{RADIUS_NM}"
)
TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
)
STATES_URL = "https://opensky-network.org/api/states/all"


def _token_response():
    return httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})


@pytest.fixture()
def sky_station(engine, tmp_path, monkeypatch):
    """A wired API app with receiver coordinates set, for the /sky route."""
    from skywatch.api.app import create_app
    from skywatch.api.services.capture import CaptureController

    monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
    data_root = tmp_path / "data"
    data_root.mkdir()
    content_dir = tmp_path / "content"
    content_dir.mkdir()
    settings = Settings(
        data_root=data_root,
        receiver=ReceiverSettings(lat=RECEIVER_LAT, lon=RECEIVER_LON),
        sky=SkySettings(radius_nm=25, opensky_daily_cap=500, heard_window_hours=12),
        opensky_client_id="cid",
        opensky_client_secret="secret",
        _env_file=None,
    )
    capture = CaptureController(engine=engine, settings=settings)
    app = create_app(
        settings,
        engine=engine,
        capture=capture,
        content_dir=content_dir,
        static_dir=tmp_path / "no-static",
        ws_poll_interval=0.05,
    )
    return SimpleNamespace(app=app, engine=engine, settings=settings, data_root=data_root)


@pytest.fixture()
def sky_client(sky_station) -> Iterator:
    from fastapi.testclient import TestClient

    with TestClient(sky_station.app) as c:
        yield c


@pytest.fixture()
def sky_session(sky_station) -> Iterator[Session]:
    with Session(sky_station.engine) as s:
        yield s


def _seed_match(session: Session, *, icao24="aaaaaa", started_at):
    from skywatch.db.enums import FrequencyCategory, RecordingStage
    from skywatch.db.models import AircraftMatch, Frequency, Recording

    freq = session.exec(select(Frequency)).first()
    if freq is None:
        freq = Frequency(
            label="Stansted Tower",
            mhz=123.805,
            facility="London Stansted",
            category=FrequencyCategory.TOWER,
            tuner_group=1,
        )
        session.add(freq)
        session.commit()
        session.refresh(freq)
    rec = Recording(
        freq_id=freq.id,
        started_at_utc=started_at,
        ended_at_utc=started_at + timedelta(seconds=8),
        duration_s=8.0,
        file_path="recordings/x.mp3",
        sample_rate=8000,
        stage=RecordingStage.CLASSIFIED,
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    match = AircraftMatch(
        recording_id=rec.id,
        source=FlightDataSource.OPENSKY,
        icao24=icao24,
        lat=RECEIVER_LAT,
        lon=RECEIVER_LON,
        distance_km=1.0,
        match_confidence=0.9,
        rank=1,
        queried_at=started_at,
    )
    session.add(match)
    session.commit()
    return rec


class TestSkyRoute:
    @respx.mock
    def test_primary_source_normalizes(self, sky_client):
        respx.get(AIRPLANES_LIVE_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "ac": [
                        {
                            "hex": "aaaaaa",
                            "flight": "BAW472",
                            "lat": RECEIVER_LAT,
                            "lon": RECEIVER_LON,
                            "alt_baro": 3200,
                            "gs": 180.0,
                        }
                    ]
                },
            )
        )
        response = sky_client.get("/sky")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "airplanes_live"
        assert body["attribution"]
        assert body["radius_nm"] == 25
        assert len(body["aircraft"]) == 1
        aircraft = body["aircraft"][0]
        assert aircraft["hex"] == "aaaaaa"
        assert aircraft["callsign"] == "BAW472"
        assert aircraft["alt_ft"] == 3200.0
        assert aircraft["heard_recently"] is False
        assert aircraft["heard_recording_ids"] == []
        assert body["_links"]["self"]["href"] == "/sky"

    @respx.mock
    def test_primary_failure_falls_through(self, sky_client):
        respx.get(AIRPLANES_LIVE_URL).mock(return_value=httpx.Response(500))
        respx.get(ADSB_LOL_URL).mock(return_value=httpx.Response(200, json={"ac": [{"hex": "bb"}]}))
        response = sky_client.get("/sky")
        assert response.status_code == 200
        assert response.json()["source"] == "adsb_lol"

    @respx.mock
    def test_all_sources_down_is_honest_200(self, sky_client):
        respx.get(AIRPLANES_LIVE_URL).mock(return_value=httpx.Response(500))
        respx.get(ADSB_LOL_URL).mock(return_value=httpx.Response(500))
        respx.get(ADSB_FI_URL).mock(return_value=httpx.Response(500))
        respx.post(TOKEN_URL).mock(return_value=httpx.Response(500))
        response = sky_client.get("/sky")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] is None
        assert body["aircraft"] == []
        assert body["attribution"] is None

    def test_no_receiver_coordinates_is_honest_empty(self, engine, tmp_path, monkeypatch):
        from skywatch.api.app import create_app
        from skywatch.api.services.capture import CaptureController

        monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
        data_root = tmp_path / "data"
        data_root.mkdir()
        settings = Settings(data_root=data_root, _env_file=None)  # receiver.lat/lon unset
        capture = CaptureController(engine=engine, settings=settings)
        app = create_app(
            settings,
            engine=engine,
            capture=capture,
            content_dir=tmp_path / "content",
            static_dir=tmp_path / "no-static",
            ws_poll_interval=0.05,
        )
        from fastapi.testclient import TestClient

        with TestClient(app) as c:
            response = c.get("/sky")
        assert response.status_code == 200
        assert response.json()["source"] is None

    @respx.mock
    def test_cache_collapses_rapid_calls(self, sky_client):
        route = respx.get(AIRPLANES_LIVE_URL).mock(
            return_value=httpx.Response(200, json={"ac": [{"hex": "cc"}]})
        )
        sky_client.get("/sky")
        sky_client.get("/sky")
        sky_client.get("/sky")
        assert route.call_count == 1

    @respx.mock
    def test_credit_guard_blocks_opensky_leg_past_cap(self, sky_client, sky_session):
        respx.get(AIRPLANES_LIVE_URL).mock(return_value=httpx.Response(500))
        respx.get(ADSB_LOL_URL).mock(return_value=httpx.Response(500))
        respx.get(ADSB_FI_URL).mock(return_value=httpx.Response(500))
        token_route = respx.post(TOKEN_URL).mock(return_value=_token_response())
        today = datetime.now(UTC).date()
        budget.record_call(sky_session, ApiProvider.OPENSKY, today, count=500)
        sky_session.commit()

        response = sky_client.get("/sky")

        assert response.status_code == 200
        assert response.json()["source"] is None
        assert token_route.call_count == 0

    @respx.mock
    def test_heard_recently_annotation(self, sky_client, sky_session):
        respx.get(AIRPLANES_LIVE_URL).mock(
            return_value=httpx.Response(200, json={"ac": [{"hex": "aaaaaa"}, {"hex": "dddddd"}]})
        )
        now = datetime.now(UTC)
        heard_rec = _seed_match(sky_session, icao24="aaaaaa", started_at=now - timedelta(hours=1))
        _seed_match(sky_session, icao24="dddddd", started_at=now - timedelta(hours=48))

        response = sky_client.get("/sky")

        assert response.status_code == 200
        by_hex = {a["hex"]: a for a in response.json()["aircraft"]}
        assert by_hex["aaaaaa"]["heard_recently"] is True
        assert by_hex["aaaaaa"]["heard_recording_ids"] == [heard_rec.id]
        assert by_hex["dddddd"]["heard_recently"] is False
        assert by_hex["dddddd"]["heard_recording_ids"] == []
