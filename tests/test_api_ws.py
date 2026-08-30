"""WS /stream event tests: the DB-polling watcher behind the live dashboard."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlmodel import Session

from skywatch.api.ws import ChangePoller, StreamHub
from skywatch.db.models import Recording, Setting
from skywatch.pipeline.retention import DEEP_TUNE_ACTIVE_KEY

_TIE_TS = datetime(2026, 7, 16, 10, 0, 0, tzinfo=UTC)


def _poller(engine) -> ChangePoller:
    return ChangePoller(
        engine=engine,
        hub=StreamHub(),
        recording_payload=lambda _session, recording: {"id": recording.id},
        status_payload=lambda _session: {"ok": True},
        interval=1.0,
    )


def _set_updated_at(engine, model, ident_col, ident, when) -> None:
    with Session(engine) as s:
        s.exec(update(model).where(ident_col == ident).values(updated_at=when))
        s.commit()


class TestWatermarkTies:
    def test_recording_update_sharing_watermark_timestamp_is_not_skipped(self, engine, seed):
        freq = seed.frequency()
        rec_a = seed.recording(freq)  # lower id — carries the newest updated_at
        rec_b = seed.recording(freq)  # higher id — will tie the watermark later
        _set_updated_at(engine, Recording, Recording.id, rec_a.id, _TIE_TS)
        _set_updated_at(engine, Recording, Recording.id, rec_b.id, _TIE_TS - timedelta(minutes=1))

        poller = _poller(engine)
        poller.baseline()  # watermark = (_TIE_TS, rec_a.id)

        # rec_b is updated to exactly the watermark timestamp, higher id
        _set_updated_at(engine, Recording, Recording.id, rec_b.id, _TIE_TS)
        messages = poller.collect()

        updated = [m["payload"]["id"] for m in messages if m["type"] == "recording.updated"]
        assert updated == [rec_b.id]

    def test_setting_change_sharing_watermark_timestamp_is_not_skipped(self, engine):
        with Session(engine) as s:
            s.add(Setting(key="alpha", value="1"))
            s.commit()
        _set_updated_at(engine, Setting, Setting.key, "alpha", _TIE_TS)

        poller = _poller(engine)
        poller.baseline()  # watermark = (_TIE_TS, "alpha")

        with Session(engine) as s:
            s.add(Setting(key="beta", value="2"))
            s.commit()
        _set_updated_at(engine, Setting, Setting.key, "beta", _TIE_TS)
        messages = poller.collect()

        assert any(m["type"] == "status.changed" for m in messages)

    def test_deep_tune_heartbeat_does_not_emit_status_changed(self, engine):
        poller = _poller(engine)
        poller.baseline()

        with Session(engine) as s:
            s.add(Setting(key=DEEP_TUNE_ACTIVE_KEY, value="1"))
            s.commit()
        messages = poller.collect()

        assert not any(m["type"] == "status.changed" for m in messages)


def _receive_until(ws, wanted_type: str, attempts: int = 10) -> dict:
    for _ in range(attempts):
        message = ws.receive_json()
        if message["type"] == wanted_type:
            return message
    raise AssertionError(f"no {wanted_type} event within {attempts} messages")


class TestStream:
    def test_new_recording_emits_recording_new(self, client, seed):
        freq = seed.frequency()
        with client.websocket_connect("/stream") as ws:
            rec = seed.recording(freq)
            message = _receive_until(ws, "recording.new")
        assert message["payload"]["id"] == rec.id
        assert message["payload"]["frequency"]["label"] == "Stansted Tower"

    def test_stage_change_emits_recording_updated(self, client, seed, session):
        from skywatch.db.enums import RecordingStage
        from skywatch.db.models import Recording

        freq = seed.frequency()
        rec = seed.recording(freq, stage=RecordingStage.CAPTURED)
        with client.websocket_connect("/stream") as ws:
            # let the poller absorb the freshly inserted row as recording.new
            _receive_until(ws, "recording.new")
            row = session.get(Recording, rec.id)
            row.stage = RecordingStage.TRANSCRIBED
            session.add(row)
            session.commit()
            message = _receive_until(ws, "recording.updated")
        assert message["payload"]["id"] == rec.id
        assert message["payload"]["stage"] == "transcribed"

    def test_rename_emits_status_changed(self, client):
        with client.websocket_connect("/stream") as ws:
            client.patch("/settings", json={"station_name": "My Airband Station"})
            message = _receive_until(ws, "status.changed")
        assert message["payload"]["station_name"] == "My Airband Station"

    def test_preexisting_rows_do_not_replay_on_connect(self, station, seed):
        from fastapi.testclient import TestClient

        freq = seed.frequency()
        seed.recording(freq)
        with TestClient(station.app) as fresh_client:  # noqa: SIM117
            with fresh_client.websocket_connect("/stream") as ws:
                # trigger one fresh event; it must be the FIRST thing received
                new_rec = seed.recording(freq)
                message = ws.receive_json()
        assert message["type"] == "recording.new"
        assert message["payload"]["id"] == new_rec.id
