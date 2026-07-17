"""Contract tests for the tuning endpoints."""

from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from skywatch.capture.stats import default_stats_path
from skywatch.db.models import Setting
from skywatch.tuning import GAIN_KEY, LAST_APPLIED_AT_KEY, PPM_KEY, SQUELCH_DEFAULT_KEY


def apply_payload(**overrides):
    payload = {
        "gain_db": 32.8,
        "squelch_default_snr_db": 12.0,
        "ppm": 0,
        "squelch_overrides": [],
    }
    payload.update(overrides)
    return payload


class TestGetTuning:
    def test_fresh_station_shape(self, client):
        response = client.get("/tuning")

        assert response.status_code == 200
        body = response.json()
        # applied values come from the config-seeded rows
        assert body["applied"]["gain_db"] == 32.0
        assert body["applied"]["squelch_default_snr_db"] == 12.0
        assert body["applied"]["ppm"] == 0
        assert body["applied"]["squelch_overrides"] == []
        assert body["baseline"] is None
        assert body["factory"] == {"gain_db": 32.0, "squelch_default_snr_db": 12.0, "ppm": 0}
        assert len(body["gain_steps_db"]) == 29
        assert body["gain_steps_db"][0] == 0.0
        assert body["gain_steps_db"][-1] == 49.6
        assert body["deep_tune"] == {
            "active": False,
            "started_at": None,
            "seconds_remaining_before_timeout": None,
        }
        assert body["last_applied_at"] is None
        links = body["_links"]
        assert links["self"]["href"] == "/tuning"
        assert links["apply"]["href"] == "/tuning/apply"
        assert links["baseline"]["href"] == "/tuning/baseline"
        assert links["meters"]["href"] == "/tuning/meters"

    def test_startup_seeds_tuning_rows_once(self, station):
        # create_app seeded the three base rows from settings
        with Session(station.engine) as session:
            assert session.get(Setting, GAIN_KEY).value == "32"
            assert session.get(Setting, SQUELCH_DEFAULT_KEY).value == "12"
            assert session.get(Setting, PPM_KEY).value == "0"


class TestApply:
    def test_apply_round_trip(self, client, station, seed):
        freq = seed.frequency()
        station.source.calls.clear()

        response = client.post(
            "/tuning/apply",
            json=apply_payload(
                gain_db=33.0,  # not a real step: snapped to 32.8
                squelch_default_snr_db=10.0,
                ppm=-2,
                squelch_overrides=[{"freq_id": freq.id, "squelch_snr_db": 8.0}],
            ),
        )

        assert response.status_code == 200
        body = response.json()
        assert body["applied"]["gain_db"] == 32.8
        assert body["applied"]["squelch_default_snr_db"] == 10.0
        assert body["applied"]["ppm"] == -2
        (override,) = body["applied"]["squelch_overrides"]
        assert override["freq_id"] == freq.id
        assert override["label"] == "Stansted Tower"
        assert override["squelch_snr_db"] == 8.0
        assert body["last_applied_at"] is not None
        assert body["capture_restarted"] is True
        assert body["warnings"] == []

        # values persisted and capture bounced onto them
        with Session(station.engine) as session:
            assert session.get(Setting, GAIN_KEY).value == "32.8"
            assert session.get(Setting, PPM_KEY).value == "-2"
            assert session.get(Setting, f"tuning.squelch.{freq.id}").value == "8"
            assert session.get(Setting, LAST_APPLIED_AT_KEY) is not None
        assert station.source.calls == ["stop", "start"]

    def test_apply_without_an_override_removes_it(self, client, seed):
        freq = seed.frequency()
        client.post(
            "/tuning/apply",
            json=apply_payload(squelch_overrides=[{"freq_id": freq.id, "squelch_snr_db": 8.0}]),
        )

        response = client.post("/tuning/apply", json=apply_payload())

        assert response.status_code == 200
        assert response.json()["applied"]["squelch_overrides"] == []

    def test_gain_out_of_range(self, client):
        response = client.post("/tuning/apply", json=apply_payload(gain_db=60.0))

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "tuning_invalid_value"
        assert "gain" in body["detail"]

    def test_ppm_out_of_range(self, client):
        response = client.post("/tuning/apply", json=apply_payload(ppm=500))

        assert response.status_code == 422
        assert response.json()["code"] == "tuning_invalid_value"

    def test_squelch_out_of_range(self, client):
        response = client.post("/tuning/apply", json=apply_payload(squelch_default_snr_db=-1.0))

        assert response.status_code == 422
        assert response.json()["code"] == "tuning_invalid_value"

    def test_override_for_unknown_frequency(self, client):
        response = client.post(
            "/tuning/apply",
            json=apply_payload(squelch_overrides=[{"freq_id": 999, "squelch_snr_db": 8.0}]),
        )

        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "tuning_unknown_frequency"
        assert body["freq_id"] == 999

    def test_override_for_inactive_frequency(self, client, seed):
        freq = seed.frequency(is_active=False)

        response = client.post(
            "/tuning/apply",
            json=apply_payload(squelch_overrides=[{"freq_id": freq.id, "squelch_snr_db": 8.0}]),
        )

        assert response.status_code == 422
        assert response.json()["code"] == "tuning_invalid_value"

    def test_invalid_values_apply_nothing(self, client, station):
        station.source.calls.clear()

        client.post("/tuning/apply", json=apply_payload(gain_db=60.0, ppm=-2))

        assert station.source.calls == []
        with Session(station.engine) as session:
            assert session.get(Setting, PPM_KEY).value == "0"


class TestBaseline:
    def test_baseline_snapshots_the_applied_values(self, client, seed):
        freq = seed.frequency()
        client.post(
            "/tuning/apply",
            json=apply_payload(
                gain_db=36.4,
                squelch_default_snr_db=11.0,
                ppm=1,
                squelch_overrides=[{"freq_id": freq.id, "squelch_snr_db": 7.0}],
            ),
        )

        response = client.post("/tuning/baseline")

        assert response.status_code == 200
        baseline = response.json()["baseline"]
        assert baseline["gain_db"] == 36.4
        assert baseline["squelch_default_snr_db"] == 11.0
        assert baseline["ppm"] == 1
        (override,) = baseline["squelch_overrides"]
        assert override["freq_id"] == freq.id
        assert override["squelch_snr_db"] == 7.0

        # and GET /tuning reflects the saved baseline afterwards
        assert client.get("/tuning").json()["baseline"] == baseline


class TestMeters:
    def stats_text(self, mhz: float, label: str) -> str:
        freq = f"{mhz:.3f}"
        return (
            f'channel_dbfs_signal_level{{freq="{freq}",label="{label}"}}\t-24.0\n'
            f'channel_dbfs_noise_level{{freq="{freq}",label="{label}"}}\t-42.5\n'
            f'channel_squelch_level{{freq="{freq}",label="{label}"}}\t-30.0\n'
            f'channel_squelch_counter{{freq="{freq}",label="{label}"}}\t12\n'
            f'channel_flappy_counter{{freq="{freq}",label="{label}"}}\t1\n'
        )

    def write_stats(self, station, text: str) -> None:
        path = default_stats_path(station.settings.data_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_meters_merge_stats_and_activity(self, client, station, seed):
        freq = seed.frequency()
        now = datetime.now(UTC)
        seed.recording(freq, started=now - timedelta(minutes=10))
        seed.recording(freq, started=now - timedelta(hours=3))
        self.write_stats(station, self.stats_text(freq.mhz, freq.label))

        response = client.get("/tuning/meters")

        assert response.status_code == 200
        body = response.json()
        assert body["stats"]["present"] is True
        assert body["stats"]["stale"] is False
        assert body["stats"]["updated_at"] is not None
        (channel,) = body["channels"]
        assert channel["freq_id"] == freq.id
        assert channel["label"] == "Stansted Tower"
        assert channel["mhz"] == 123.805
        assert channel["signal_dbfs"] == -24.0
        assert channel["noise_dbfs"] == -42.5
        assert channel["snr_db"] == 18.5
        assert channel["squelch_level_dbfs"] == -30.0
        assert channel["squelch_open_count"] == 12
        assert channel["flappy_count"] == 1
        assert channel["clips_last_hour"] == 1
        assert channel["last_heard_utc"] is not None
        # nothing has been applied yet
        assert channel["clips_since_apply"] is None
        assert body["since_last_apply"] is None
        assert body["_links"]["self"]["href"] == "/tuning/meters"

    def test_meters_without_a_stats_file(self, client, seed):
        freq = seed.frequency()

        body = client.get("/tuning/meters").json()

        assert body["stats"]["present"] is False
        assert body["stats"]["stale"] is False
        (channel,) = body["channels"]
        assert channel["freq_id"] == freq.id
        assert channel["signal_dbfs"] is None
        assert channel["snr_db"] is None
        assert channel["clips_last_hour"] == 0
        assert channel["last_heard_utc"] is None

    def test_clip_counts_since_the_last_apply(self, client, station, seed):
        freq = seed.frequency()
        now = datetime.now(UTC)
        seed.recording(freq, started=now - timedelta(hours=2))  # before the apply

        response = client.post("/tuning/apply", json=apply_payload())
        assert response.status_code == 200
        seed.recording(freq, started=now + timedelta(seconds=1))  # after the apply

        body = client.get("/tuning/meters").json()

        (channel,) = body["channels"]
        assert channel["clips_since_apply"] == 1
        since = body["since_last_apply"]
        assert since["applied_at"] is not None
        assert since["total_clips"] == 1

    def test_only_active_frequencies_have_channel_strips(self, client, seed):
        seed.frequency()
        seed.frequency(label="North Weald", mhz=122.180, is_active=False)

        body = client.get("/tuning/meters").json()

        assert [c["label"] for c in body["channels"]] == ["Stansted Tower"]
