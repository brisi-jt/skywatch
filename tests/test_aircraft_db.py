"""Aircraft identity: loader, enrichment fill, and API exposure."""

from fastapi.testclient import TestClient
from sqlmodel import select

from skywatch.db.enums import FrequencyCategory
from skywatch.db.models import AircraftMatch, Frequency, Recording, utcnow
from skywatch.providers.flightdata.aircraft_db import AircraftDb, AircraftInfo
from skywatch.providers.flightdata.airlines import AirlineDirectory
from skywatch.providers.flightdata.opensky import OpenSkyEnricher, StateVector

_HEADER = "icao24,registration,manufacturername,model,typecode,operator"


def _write_db(tmp_path, rows: list[str]):
    path = tmp_path / "aircraft_db.csv"
    path.write_text("\n".join([_HEADER, *rows]) + "\n")
    return path


class TestLoader:
    def test_lookup(self, tmp_path):
        path = _write_db(tmp_path, ["4009f9,G-EUYW,Airbus,A320-232,A320,British Airways"])
        db = AircraftDb.load(path)
        assert len(db) == 1
        info = db.lookup("4009F9")
        assert info.registration == "G-EUYW"
        assert info.aircraft_type == "A320"
        assert info.operator_name == "British Airways"

    def test_missing_file_is_empty(self, tmp_path):
        db = AircraftDb.load(tmp_path / "absent.csv")
        assert len(db) == 0
        assert db.lookup("4009f9") is None

    def test_falls_back_to_model_when_no_typecode(self, tmp_path):
        path = tmp_path / "aircraft_db.csv"
        path.write_text("icao24,registration,model,operator\nabc123,G-XX,A320 neo,BA\n")
        assert AircraftDb.load(path).lookup("abc123").aircraft_type == "A320 neo"

    def test_rows_with_only_icao_are_skipped(self, tmp_path):
        path = _write_db(tmp_path, ["deadbe,,,,,"])
        assert len(AircraftDb.load(path)) == 0


def test_enricher_fills_identity(session, monkeypatch):
    enricher = OpenSkyEnricher(
        object(),
        receiver_lat=51.7,
        receiver_lon=0.1,
        radius_km=40,
        bucket_seconds=30,
        daily_credit_cap=3000,
        airlines=AirlineDirectory({}),
        aircraft_db=AircraftDb({"4009f9": AircraftInfo("G-EUYW", "A320", "British Airways")}),
    )
    monkeypatch.setattr(
        enricher,
        "_states_for",
        lambda s, at: [StateVector("4009f9", "BAW1", 51.71, 0.11, 3000.0, False, 200.0)],
    )
    freq = Frequency(
        label="Twr", mhz=123.8, facility="f", category=FrequencyCategory.TOWER, tuner_group=1
    )
    session.add(freq)
    session.commit()
    rec = Recording(
        freq_id=freq.id,
        started_at_utc=utcnow(),
        ended_at_utc=utcnow(),
        duration_s=6.0,
        file_path="x.mp3",
        sample_rate=8000,
    )
    session.add(rec)
    session.commit()
    enricher.enrich(session, rec, freq.category)
    session.commit()

    match = session.exec(select(AircraftMatch)).one()
    assert match.registration == "G-EUYW"
    assert match.aircraft_type == "A320"
    assert match.operator_name == "British Airways"


def test_recording_detail_exposes_identity(client: TestClient, seed):
    freq = seed.frequency()
    rec = seed.recording(freq)
    seed.match(
        rec,
        rank=1,
        icao24="4009f9",
        registration="G-EUYW",
        aircraft_type="A320",
        operator_name="British Airways",
    )
    match = client.get(f"/recordings/{rec.id}").json()["matches"][0]
    assert match["registration"] == "G-EUYW"
    assert match["aircraft_type"] == "A320"
    assert match["operator_name"] == "British Airways"
