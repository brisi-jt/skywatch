"""WS /stream event tests: the DB-polling watcher behind the live dashboard."""


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
