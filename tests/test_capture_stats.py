"""Parser for the rtl_airband statistics file.

The fixture text mirrors the real file: Prometheus-style lines with a TAB
between the closing brace and the value, ``freq`` labels always present and
``label`` only when the channel has one, plus metrics the meters do not use.
"""

import os
import time
from pathlib import Path

from skywatch.capture.stats import default_stats_path, read_stats

SAMPLE = (
    "# HELP channel_dbfs_signal_level Channel signal level in dBFS\n"
    "# TYPE channel_dbfs_signal_level gauge\n"
    'channel_dbfs_signal_level{freq="118.480"}\t-21.5\n'
    'channel_dbfs_signal_level{freq="121.500",label="Guard 121.500"}\t-35.25\n'
    "# HELP channel_dbfs_noise_level Channel noise level in dBFS\n"
    "# TYPE channel_dbfs_noise_level gauge\n"
    'channel_dbfs_noise_level{freq="118.480"}\t-40.0\n'
    'channel_dbfs_noise_level{freq="121.500",label="Guard 121.500"}\t-41.0\n'
    'channel_squelch_level{freq="118.480"}\t-28.0\n'
    'channel_squelch_level{freq="121.500",label="Guard 121.500"}\t-30.5\n'
    'channel_squelch_counter{freq="118.480"}\t17\n'
    'channel_squelch_counter{freq="121.500",label="Guard 121.500"}\t3\n'
    'channel_flappy_counter{freq="118.480"}\t2\n'
    'channel_flappy_counter{freq="121.500",label="Guard 121.500"}\t0\n'
    'channel_activity_counter{freq="118.480"}\t912\n'
    'buffer_overflow_count{device="0"}\t0\n'
)


def write_sample(path: Path, text: str = SAMPLE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestParsing:
    def test_extracts_every_meter_metric_per_channel(self, tmp_path):
        snapshot = read_stats(write_sample(tmp_path / "stats.txt"))

        assert snapshot.file_present is True
        assert snapshot.stale is False
        assert snapshot.updated_at is not None
        assert len(snapshot.channels) == 2

        plain = snapshot.channel_for(118.480)
        assert plain is not None
        assert plain.label is None
        assert plain.signal_dbfs == -21.5
        assert plain.noise_dbfs == -40.0
        assert plain.squelch_level_dbfs == -28.0
        assert plain.squelch_open_count == 17
        assert plain.flappy_count == 2
        assert plain.snr_db == 18.5

        guard = snapshot.channel_for(121.5)
        assert guard is not None
        assert guard.label == "Guard 121.500"
        assert guard.signal_dbfs == -35.25
        assert guard.snr_db == 5.75

    def test_tolerates_spaces_instead_of_tabs(self, tmp_path):
        text = SAMPLE.replace("\t", "  ")
        snapshot = read_stats(write_sample(tmp_path / "stats.txt", text))
        assert snapshot.channel_for(118.480).signal_dbfs == -21.5

    def test_non_finite_values_read_as_none(self, tmp_path):
        text = (
            'channel_dbfs_signal_level{freq="118.480"}\tnan\n'
            'channel_dbfs_noise_level{freq="118.480"}\t-inf\n'
        )
        snapshot = read_stats(write_sample(tmp_path / "stats.txt", text))
        channel = snapshot.channel_for(118.480)
        assert channel.signal_dbfs is None
        assert channel.noise_dbfs is None
        assert channel.snr_db is None

    def test_unknown_frequency_lookup_returns_none(self, tmp_path):
        snapshot = read_stats(write_sample(tmp_path / "stats.txt"))
        assert snapshot.channel_for(999.999) is None

    def test_garbled_lines_are_skipped(self, tmp_path):
        text = "not a metric line\n" + SAMPLE + 'channel_squelch_counter{freq="bad"}\tx\n'
        snapshot = read_stats(write_sample(tmp_path / "stats.txt", text))
        assert len(snapshot.channels) == 2


class TestFileStates:
    def test_missing_file(self, tmp_path):
        snapshot = read_stats(tmp_path / "absent.txt")
        assert snapshot.file_present is False
        assert snapshot.stale is False
        assert snapshot.updated_at is None
        assert snapshot.channels == []

    def test_stale_file_flagged_by_mtime(self, tmp_path):
        path = write_sample(tmp_path / "stats.txt")
        old = time.time() - 300
        os.utime(path, (old, old))

        snapshot = read_stats(path, stale_after_s=60.0)

        assert snapshot.file_present is True
        assert snapshot.stale is True
        assert snapshot.channels  # stale data is still parsed, just flagged

    def test_fresh_file_is_not_stale(self, tmp_path):
        snapshot = read_stats(write_sample(tmp_path / "stats.txt"), stale_after_s=60.0)
        assert snapshot.stale is False


class TestDefaultPath:
    def test_lives_under_the_data_root(self, tmp_path):
        assert default_stats_path(tmp_path) == tmp_path / "stats" / "rtl_airband_stats.txt"
