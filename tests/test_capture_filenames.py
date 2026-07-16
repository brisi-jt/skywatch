"""Filename contract shared by the conf renderer, ReplaySource, and watcher.

rtl_airband with ``split_on_transmission`` + ``include_freq`` names clips
``<template>_<YYYYMMDD>_<HHMMSS>_<freq-in-Hz>.mp3`` (UTC), inside nested
``YYYY/MM/DD`` directories when ``dated_subdirectories`` is on.
"""

from datetime import UTC, datetime
from pathlib import Path

from skywatch.capture.filenames import (
    dated_subdir,
    format_recording_filename,
    parse_recording_filename,
    slugify_label,
)

TS = datetime(2026, 7, 16, 9, 30, 5, tzinfo=UTC)


def test_format_matches_rtl_airband_shape():
    name = format_recording_filename("stansted_tower", TS, 123_805_000)
    assert name == "stansted_tower_20260716_093005_123805000.mp3"


def test_round_trip():
    name = format_recording_filename("guard_121500", TS, 121_500_000)
    parsed = parse_recording_filename(name)
    assert parsed is not None
    assert parsed.template == "guard_121500"
    assert parsed.started_at_utc == TS
    assert parsed.freq_hz == 121_500_000


def test_parse_template_with_underscores_and_digits():
    parsed = parse_recording_filename("london_control_2_20260716_093005_118825000.mp3")
    assert parsed is not None
    assert parsed.template == "london_control_2"
    assert parsed.freq_hz == 118_825_000


def test_parse_returns_utc_aware_timestamp():
    parsed = parse_recording_filename("x_20260101_000000_121500000.mp3")
    assert parsed is not None
    assert parsed.started_at_utc.tzinfo is UTC


def test_parse_rejects_foreign_files():
    assert parse_recording_filename("notes.txt") is None
    assert parse_recording_filename("clip.mp3") is None
    assert parse_recording_filename("x_2026_093005_121500000.mp3") is None
    assert parse_recording_filename("x_20260716_093005.mp3") is None  # no freq suffix
    assert parse_recording_filename("x_20261341_996161_121500000.mp3") is None  # bad date


def test_dated_subdir_is_nested_utc():
    assert dated_subdir(TS) == Path("2026/07/16")


def test_slugify_label():
    assert slugify_label("Stansted Approach (Essex Radar)") == "stansted_approach_essex_radar"
    assert slugify_label("Guard 121.500") == "guard_121_500"
