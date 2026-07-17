"""Reader for the rtl_airband statistics file.

rtl_airband rewrites a Prometheus-format text file every 15 seconds with
per-channel signal and noise levels (updated even while squelch is closed),
which makes it the station's only always-on meter source. The format is
loose — a TAB separates the value from the closing brace, and the ``label``
label appears only when the channel has one — so this parser splits on
whitespace rather than expecting strict Prometheus text.
"""

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

STATS_FILENAME = "rtl_airband_stats.txt"

# how far apart two frequencies can be and still mean the same channel
_FREQ_TOLERANCE_MHZ = 0.0005

_METRIC_LINE_RE = re.compile(r"^(?P<name>[A-Za-z_:][\w:]*)\{(?P<labels>[^}]*)\}\s+(?P<value>\S+)")
_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')

_METRIC_FIELDS = {
    "channel_dbfs_signal_level": "signal_dbfs",
    "channel_dbfs_noise_level": "noise_dbfs",
    "channel_squelch_level": "squelch_level_dbfs",
    "channel_squelch_counter": "squelch_open_count",
    "channel_flappy_counter": "flappy_count",
}
_COUNTER_FIELDS = {"squelch_open_count", "flappy_count"}


def default_stats_path(data_root: Path) -> Path:
    """Where the station keeps the rtl_airband statistics file."""
    root = Path(data_root)
    if not root.is_absolute():
        root = root.resolve()
    return root / "stats" / STATS_FILENAME


@dataclass
class ChannelStats:
    """One channel's readings from the statistics file."""

    freq_mhz: float
    label: str | None = None
    signal_dbfs: float | None = None
    noise_dbfs: float | None = None
    squelch_level_dbfs: float | None = None
    squelch_open_count: int | None = None
    flappy_count: int | None = None

    @property
    def snr_db(self) -> float | None:
        """Signal above the noise floor; the number squelch thresholds compare against."""
        if self.signal_dbfs is None or self.noise_dbfs is None:
            return None
        return self.signal_dbfs - self.noise_dbfs


@dataclass
class StatsSnapshot:
    """The statistics file as last written, plus its freshness."""

    file_present: bool
    stale: bool
    updated_at: datetime | None
    channels: list[ChannelStats] = field(default_factory=list)

    def channel_for(self, mhz: float) -> ChannelStats | None:
        for channel in self.channels:
            if abs(channel.freq_mhz - mhz) <= _FREQ_TOLERANCE_MHZ:
                return channel
        return None


def read_stats(
    path: Path, *, stale_after_s: float = 60.0, now: datetime | None = None
) -> StatsSnapshot:
    """Parse the statistics file at ``path``.

    A missing file is a normal state (capture not started yet) and returns
    an empty snapshot. A file whose modification time is older than
    ``stale_after_s`` is still parsed but flagged stale, because rtl_airband
    rewrites it every 15 seconds — an old file means the numbers describe a
    process that is no longer reporting.
    """
    path = Path(path)
    try:
        text = path.read_text()
        mtime = path.stat().st_mtime
    except OSError:
        return StatsSnapshot(file_present=False, stale=False, updated_at=None)

    updated_at = datetime.fromtimestamp(mtime, tz=UTC)
    current = now or datetime.now(UTC)
    stale = (current - updated_at).total_seconds() > stale_after_s

    channels: dict[float, ChannelStats] = {}
    for line in text.splitlines():
        match = _METRIC_LINE_RE.match(line)
        if match is None:
            continue
        target = _METRIC_FIELDS.get(match.group("name"))
        if target is None:
            continue
        labels = dict(_LABEL_RE.findall(match.group("labels")))
        try:
            freq_mhz = float(labels["freq"])
            value = float(match.group("value"))
        except (KeyError, ValueError):
            continue
        channel = channels.setdefault(freq_mhz, ChannelStats(freq_mhz=freq_mhz))
        if labels.get("label"):
            channel.label = labels["label"]
        if not math.isfinite(value):
            continue
        if target in _COUNTER_FIELDS:
            setattr(channel, target, int(value))
        else:
            setattr(channel, target, value)

    ordered = [channels[key] for key in sorted(channels)]
    return StatsSnapshot(file_present=True, stale=stale, updated_at=updated_at, channels=ordered)
