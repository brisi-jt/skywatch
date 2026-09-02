"""plane-alert database: loader, enrichment annotation, prefilter, and API."""

from fastapi.testclient import TestClient
from sqlmodel import select

from skywatch.db.enums import FrequencyCategory
from skywatch.db.models import AircraftMatch
from skywatch.pipeline.prefilters import INTERESTING_AIRCRAFT_PREFIX, run_prefilters
from skywatch.pipeline.stages.classify import best_aircraft_alert
from skywatch.providers.flightdata.airlines import AirlineDirectory
from skywatch.providers.flightdata.opensky import OpenSkyEnricher, StateVector
from skywatch.providers.flightdata.plane_alert import PlaneAlertDb

_HEADER = "$ICAO,$Registration,$Operator,$Type,$ICAO Type,#CMPG,$Tag 1,$Tag 2,$Tag 3,Category,$Link"


def _write_db(tmp_path, rows: list[str]):
    path = tmp_path / "plane_alert_db.csv"
    path.write_text("\n".join([_HEADER, *rows]) + "\n")
    return path


class TestLoader:
    def test_lookup_by_icao_case_insensitive(self, tmp_path):
        path = _write_db(tmp_path, ["ADFEB7,N12345,US Army,UH-60,H60,,,,,Military,http://x"])
        db = PlaneAlertDb.load(path)
        assert len(db) == 1
        assert db.lookup("adfeb7") == "Military"
        assert db.lookup("ADFEB7") == "Military"
        assert db.lookup("000000") is None
        assert db.lookup(None) is None

    def test_missing_file_is_empty_noop(self, tmp_path):
        db = PlaneAlertDb.load(tmp_path / "absent.csv")
        assert len(db) == 0
        assert db.lookup("adfeb7") is None

    def test_header_only_is_empty(self, tmp_path):
        db = PlaneAlertDb.load(_write_db(tmp_path, []))
        assert len(db) == 0

    def test_rows_without_category_are_skipped(self, tmp_path):
        path = _write_db(tmp_path, ["ABC123,reg,op,type,T,,,,,,link"])
        assert len(PlaneAlertDb.load(path)) == 0

    def test_missing_columns_disables_badges(self, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("foo,bar\n1,2\n")
        assert len(PlaneAlertDb.load(path)) == 0


class TestPrefilterAircraftAlert:
    def test_interesting_aircraft_flags_routine_clip(self):
        verdict = run_prefilters(
            transcript_text="cleared to land runway two two",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
            aircraft_alert=("Military", 1),
        )
        assert verdict.is_interesting
        assert f"{INTERESTING_AIRCRAFT_PREFIX}Military" in verdict.flags
        assert "Military" in verdict.reason

    def test_confidence_weighted_by_rank(self):
        rank1 = run_prefilters(
            transcript_text="routine",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
            aircraft_alert=("Historic", 1),
        )
        rank4 = run_prefilters(
            transcript_text="routine",
            duration_s=6.0,
            freq_category=FrequencyCategory.TOWER,
            aircraft_alert=("Historic", 4),
        )
        assert rank1.confidence > rank4.confidence


class TestBestAircraftAlert:
    def _match(self, session, recording, **kwargs):
        from skywatch.db.enums import FlightDataSource
        from skywatch.db.models import utcnow

        defaults = dict(
            source=FlightDataSource.OPENSKY,
            icao24="abc123",
            lat=51.7,
            lon=0.1,
            distance_km=3.0,
            match_confidence=0.8,
            queried_at=utcnow(),
        )
        defaults.update(kwargs)
        row = AircraftMatch(recording_id=recording.id, **defaults)
        session.add(row)
        session.commit()

    def test_picks_best_ranked_alerted(self, session, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        self._match(session, rec, rank=1, alert_category=None)
        self._match(session, rec, rank=2, alert_category="Military")
        self._match(session, rec, rank=3, alert_category="Historic")
        assert best_aircraft_alert(session, rec.id) == ("Military", 2)

    def test_none_when_no_alerted_matches(self, session, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)
        self._match(session, rec, rank=1, alert_category=None)
        assert best_aircraft_alert(session, rec.id) is None


def test_enricher_annotates_alert_category(session, monkeypatch):
    from skywatch.db.enums import FrequencyCategory as FC

    airlines = AirlineDirectory({})
    plane_alert = PlaneAlertDb({"adfeb7": "Military"})

    class _Client:
        pass

    enricher = OpenSkyEnricher(
        _Client(),
        receiver_lat=51.7,
        receiver_lon=0.1,
        radius_km=40,
        bucket_seconds=30,
        daily_credit_cap=3000,
        airlines=airlines,
        plane_alert=plane_alert,
    )
    monkeypatch.setattr(
        enricher,
        "_states_for",
        lambda s, at: [
            StateVector("adfeb7", "RCH123", 51.71, 0.11, 3000.0, False, 200.0),
            StateVector("000abc", "BAW1", 51.72, 0.12, 3000.0, False, 200.0),
        ],
    )
    from skywatch.db.models import Frequency, Recording, utcnow

    freq = Frequency(label="Twr", mhz=123.8, facility="f", category=FC.TOWER, tuner_group=1)
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

    matches = {m.icao24: m.alert_category for m in session.exec(select(AircraftMatch)).all()}
    assert matches["adfeb7"] == "Military"
    assert matches["000abc"] is None


def test_recording_detail_exposes_alert_category(client: TestClient, seed, session):
    freq = seed.frequency()
    rec = seed.recording(freq)
    seed.match(rec, rank=1, icao24="adfeb7", alert_category="Military")
    body = client.get(f"/recordings/{rec.id}").json()
    assert body["matches"][0]["alert_category"] == "Military"
