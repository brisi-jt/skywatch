"""The clip filename contract shared by renderer, replay, and watcher.

rtl_airband, configured with ``split_on_transmission`` and ``include_freq``,
names each clip ``<template>_<YYYYMMDD>_<HHMMSS>_<frequency-in-Hz>.mp3``
using UTC timestamps, and nests files under ``YYYY/MM/DD`` directories when
``dated_subdirectories`` is on. This module is the single place that
encodes that shape; everything else formats and parses through it.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

FILENAME_RE = re.compile(
    r"^(?P<template>.+)_(?P<date>\d{8})_(?P<time>\d{6})_(?P<freq_hz>\d+)\.mp3$"
)


@dataclass(frozen=True)
class ParsedRecordingFilename:
    template: str
    started_at_utc: datetime
    freq_hz: int


def format_recording_filename(template: str, started_at_utc: datetime, freq_hz: int) -> str:
    """Name a clip exactly the way rtl_airband would."""
    stamp = started_at_utc.astimezone(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{template}_{stamp}_{freq_hz}.mp3"


def parse_recording_filename(name: str) -> ParsedRecordingFilename | None:
    """Recover template, start time, and frequency from a clip filename.

    Returns ``None`` for anything that does not match the contract, so
    foreign files in the recordings directory are ignored rather than fatal.
    """
    match = FILENAME_RE.match(name)
    if match is None:
        return None
    try:
        started = datetime.strptime(f"{match['date']}{match['time']}", "%Y%m%d%H%M%S").replace(
            tzinfo=UTC
        )
    except ValueError:
        return None
    return ParsedRecordingFilename(
        template=match["template"],
        started_at_utc=started,
        freq_hz=int(match["freq_hz"]),
    )


def dated_subdir(started_at_utc: datetime) -> Path:
    """The nested ``YYYY/MM/DD`` directory rtl_airband files a clip under."""
    stamped = started_at_utc.astimezone(UTC)
    return Path(f"{stamped.year:04d}") / f"{stamped.month:02d}" / f"{stamped.day:02d}"


def slugify_label(label: str) -> str:
    """A frequency label as a filesystem-safe filename template."""
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower())
    return slug.strip("_")
