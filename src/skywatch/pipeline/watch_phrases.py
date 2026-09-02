"""Owner-editable phrases that always flag a clip as interesting.

The station ships with a set of distress phrases, but a listener can add
their own words to catch ("go around", a local airfield name, a squawk they
care about). The list lives in the settings table as a JSON array under
``classify.watch_phrases``; the prefilter reads it and, when the transcript
contains one, raises an upgrade-only flag naming the phrase. Reading falls
back to the defaults whenever the row is missing or unparseable, so a
misedited value never silences the built-in distress phrases.
"""

import json
import logging

from sqlmodel import Session

from skywatch.db.models import Setting

logger = logging.getLogger(__name__)

WATCH_PHRASES_KEY = "classify.watch_phrases"

MAX_WATCH_PHRASES = 100
MAX_PHRASE_LENGTH = 100

# Seeded from the station's built-in distress phrasings so a fresh station
# already flags the calls that matter; the owner edits the list from there.
DEFAULT_WATCH_PHRASES: list[str] = [
    "mayday",
    "pan pan",
    "declaring emergency",
    "emergency",
    "engine failure",
    "engine fire",
    "go around",
    "minimum fuel",
    "fuel emergency",
    "diverting",
    "medical emergency",
]


def load_watch_phrases(session: Session) -> list[str]:
    """The configured watch phrases, or the defaults when unset/invalid."""
    row = session.get(Setting, WATCH_PHRASES_KEY)
    if row is None:
        return list(DEFAULT_WATCH_PHRASES)
    try:
        parsed = json.loads(row.value)
    except (ValueError, TypeError):
        logger.warning("watch_phrases setting is not valid JSON; using defaults")
        return list(DEFAULT_WATCH_PHRASES)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        logger.warning("watch_phrases setting is not a list of strings; using defaults")
        return list(DEFAULT_WATCH_PHRASES)
    return [item for item in parsed if item.strip()]


def clean_watch_phrases(value: object) -> list[str] | None:
    """Validate an incoming watch-phrase list; None means invalid.

    Accepts a list of non-empty strings within the length caps, trimming
    each and dropping blanks and duplicates while preserving order.
    """
    if not isinstance(value, list):
        return None
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        trimmed = item.strip()
        if not trimmed:
            continue
        if len(trimmed) > MAX_PHRASE_LENGTH:
            return None
        if trimmed not in cleaned:
            cleaned.append(trimmed)
    if len(cleaned) > MAX_WATCH_PHRASES:
        return None
    return cleaned
