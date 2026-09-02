"""Contract tests for the waveform peaks endpoint and the peak builder."""

import pytest

from skywatch.api.services import peaks as peaks_service

PROBLEM_TYPE = "application/problem+json"


class _CountingDecoder:
    """A stand-in for the MP3 decode path that records how often it ran."""

    def __init__(self, samples):
        self.samples = samples
        self.calls = 0

    def __call__(self, path):
        self.calls += 1
        return self.samples


class TestPeaksBuilder:
    def test_buckets_and_normalises_to_unit_range(self):
        ramp = [i / 1000 for i in range(1000)]
        result = peaks_service.compute_peaks(ramp, buckets=400)

        assert len(result) == 400
        assert all(0.0 <= value <= 1.0 for value in result)
        # a monotonically rising signal peaks at the end after normalisation
        assert result[-1] == pytest.approx(1.0, abs=0.01)
        assert result[0] < result[-1]

    def test_empty_signal_yields_no_peaks(self):
        assert peaks_service.compute_peaks([], buckets=400) == []

    def test_silent_signal_stays_flat_zero(self):
        assert peaks_service.compute_peaks([0.0, 0.0, 0.0], buckets=400) == [0.0, 0.0, 0.0]


class TestPeaksEndpoint:
    def test_lazy_compute_then_cache_hit(self, client, seed, station, monkeypatch):
        freq = seed.frequency()
        rec = seed.recording(freq, audio_bytes=b"not-real-mp3-bytes")
        decoder = _CountingDecoder([i / 1000 for i in range(1000)])
        monkeypatch.setattr(peaks_service, "_decode_abs_samples", decoder)

        first = client.get(f"/recordings/{rec.id}/peaks")
        assert first.status_code == 200
        body = first.json()
        assert len(body["peaks"]) > 0
        assert all(0.0 <= value <= 1.0 for value in body["peaks"])
        assert decoder.calls == 1
        # the sidecar cache was written under the data root, keyed by id
        assert peaks_service.sidecar_path(station.data_root, rec.id).is_file()

        second = client.get(f"/recordings/{rec.id}/peaks")
        assert second.status_code == 200
        assert second.json()["peaks"] == body["peaks"]
        # a second request is served from the sidecar; the MP3 is not decoded again
        assert decoder.calls == 1

    def test_pruned_audio_is_410(self, client, seed, monkeypatch):
        freq = seed.frequency()
        rec = seed.recording(freq, audio_deleted=True)
        decoder = _CountingDecoder([0.5])
        monkeypatch.setattr(peaks_service, "_decode_abs_samples", decoder)

        response = client.get(f"/recordings/{rec.id}/peaks")

        assert response.status_code == 410
        assert response.headers["content-type"].startswith(PROBLEM_TYPE)
        assert response.json()["code"] == "audio_deleted"
        assert decoder.calls == 0

    def test_unknown_recording_is_404(self, client):
        response = client.get("/recordings/999/peaks")
        assert response.status_code == 404
        assert response.json()["code"] == "recording_not_found"

    def test_missing_file_is_404(self, client, seed):
        freq = seed.frequency()
        rec = seed.recording(freq)  # row exists, no audio written to disk

        response = client.get(f"/recordings/{rec.id}/peaks")

        assert response.status_code == 404
        assert response.json()["code"] == "audio_file_missing"

    def test_undecodable_audio_returns_empty_peaks(self, client, seed, station, monkeypatch):
        freq = seed.frequency()
        rec = seed.recording(freq, audio_bytes=b"bytes")
        monkeypatch.setattr(peaks_service, "_decode_abs_samples", lambda path: None)

        response = client.get(f"/recordings/{rec.id}/peaks")

        assert response.status_code == 200
        assert response.json()["peaks"] == []
        # nothing is cached when the decode path is unavailable
        assert not peaks_service.sidecar_path(station.data_root, rec.id).is_file()

    def test_real_decode_path_on_a_fixture_clip(self, client, seed):
        pytest.importorskip("faster_whisper")
        from pathlib import Path

        mp3 = (Path(__file__).resolve().parent.parent / "fixtures" / "mayday.mp3").read_bytes()
        freq = seed.frequency()
        rec = seed.recording(freq, audio_bytes=mp3)

        response = client.get(f"/recordings/{rec.id}/peaks")

        assert response.status_code == 200
        assert len(response.json()["peaks"]) > 0
