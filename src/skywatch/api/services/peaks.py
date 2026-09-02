"""Waveform peaks for the player's scrubber.

A clip's peaks are a short array of normalised amplitudes (0..1), one per
horizontal bucket, cheap enough to draw a static waveform behind the seek
bar. They are computed lazily the first time a clip's waveform is asked for,
then cached in a sidecar JSON file under the data root keyed by recording id
so the MP3 is only decoded once.

Decoding is deliberately optional: it reuses faster-whisper's audio decoder
(the same code path transcription already relies on), and when that extra is
not installed the endpoint simply reports no peaks rather than failing — the
scrubber falls back to a plain range input.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

# Enough detail to read a waveform at player width without shipping a big array.
PEAK_BUCKETS = 400

# The clip is captured at 8 kHz mono; decode at the same rate.
_DECODE_SAMPLE_RATE = 8000


def sidecar_path(data_root: Path, recording_id: int) -> Path:
    """Where a clip's cached peaks live, under the station's data root."""
    return data_root / "peaks" / f"{recording_id}.json"


def compute_peaks(samples: Sequence[float], buckets: int = PEAK_BUCKETS) -> list[float]:
    """Downsample absolute amplitudes to `buckets` normalised peaks in [0, 1]."""
    n = len(samples)
    if n == 0:
        return []
    count = min(buckets, n)
    raw: list[float] = []
    for k in range(count):
        start = k * n // count
        end = (k + 1) * n // count
        raw.append(float(max(samples[start:end])))
    ceiling = max(raw)
    if ceiling <= 0:
        return [0.0 for _ in raw]
    return [round(value / ceiling, 3) for value in raw]


def _decode_abs_samples(path: Path) -> list[float] | None:
    """Absolute-valued audio samples for a clip, or None when decoding is
    unavailable. Isolated so tests can substitute a synthetic signal."""
    try:
        from faster_whisper.audio import decode_audio
    except Exception:  # pragma: no cover - environment-dependent
        return None
    try:
        import numpy as np

        samples = decode_audio(str(path), sampling_rate=_DECODE_SAMPLE_RATE)
        return np.abs(np.asarray(samples, dtype="float32"))
    except Exception:  # pragma: no cover - a bad clip should not 500 the endpoint
        logger.warning("could not decode audio for peaks: %s", path, exc_info=True)
        return None


def _write_sidecar(path: Path, peaks: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(peaks))
    os.replace(tmp, path)


def load_or_compute(data_root: Path, recording_id: int, audio_path: Path) -> list[float]:
    """Peaks for a clip: the cached array if present, otherwise decode the MP3,
    cache, and return. Returns an empty list when the audio cannot be decoded."""
    cache = sidecar_path(data_root, recording_id)
    if cache.is_file():
        try:
            cached = json.loads(cache.read_text())
            if isinstance(cached, list):
                return [float(v) for v in cached]
        except (ValueError, OSError):  # pragma: no cover - corrupt cache: recompute
            logger.warning("ignoring unreadable peaks cache: %s", cache)

    samples = _decode_abs_samples(audio_path)
    if samples is None or len(samples) == 0:
        return []
    peaks = compute_peaks(samples)
    try:
        _write_sidecar(cache, peaks)
    except OSError:  # pragma: no cover - a read-only data dir should still serve peaks
        logger.warning("could not cache peaks for recording %s", recording_id)
    return peaks
