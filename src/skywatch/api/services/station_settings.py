"""Owner-editable station settings behind GET/PATCH /settings.

Only whitelisted keys are readable or writable here. The settings table
also carries worker-internal state (like the disk-guard pause flag), which
is deliberately outside this surface — it is reported via /status instead.
"""

import json

from sqlmodel import Session
from starlette import status

from skywatch.api.errors import APIErrorCode, ProblemException
from skywatch.api.schemas import Link, SettingsResponse
from skywatch.db.models import Setting
from skywatch.pipeline.watch_phrases import (
    MAX_PHRASE_LENGTH,
    MAX_WATCH_PHRASES,
    WATCH_PHRASES_KEY,
    clean_watch_phrases,
    load_watch_phrases,
)

WALKTHROUGH_KEY = "tuning.walkthrough_done"
FIRST_CLIP_CELEBRATED_KEY = "first_clip_celebrated"
EARCON_ENABLED_KEY = "earcon_enabled"
TEXT_SIZE_KEY = "display.text_size"

TEXT_SIZES = ("normal", "large")
DEFAULT_TEXT_SIZE = "normal"

EDITABLE_KEYS = (
    "station_name",
    WALKTHROUGH_KEY,
    FIRST_CLIP_CELEBRATED_KEY,
    EARCON_ENABLED_KEY,
    WATCH_PHRASES_KEY,
    TEXT_SIZE_KEY,
)

# Keys that hold a boolean, stored as the strings "true" / "false".
BOOLEAN_KEYS = (WALKTHROUGH_KEY, FIRST_CLIP_CELEBRATED_KEY, EARCON_ENABLED_KEY)


def _flag(session: Session, key: str) -> bool:
    row = session.get(Setting, key)
    return row is not None and row.value == "true"


def settings_view(session: Session) -> SettingsResponse:
    row = session.get(Setting, "station_name")
    text_size_row = session.get(Setting, TEXT_SIZE_KEY)
    return SettingsResponse(
        station_name=row.value if row is not None else None,
        tuning_walkthrough_done=_flag(session, WALKTHROUGH_KEY),
        first_clip_celebrated=_flag(session, FIRST_CLIP_CELEBRATED_KEY),
        earcon_enabled=_flag(session, EARCON_ENABLED_KEY),
        watch_phrases=load_watch_phrases(session),
        text_size=text_size_row.value if text_size_row is not None else DEFAULT_TEXT_SIZE,
        links={"self": Link(href="/settings")},
    )


def _store(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
        session.add(row)


def _invalid(key: str, detail: str) -> ProblemException:
    return ProblemException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        APIErrorCode.INVALID_SETTING_VALUE,
        detail,
    )


def apply_patch(session: Session, payload: dict[str, object]) -> SettingsResponse:
    unknown = sorted(set(payload) - set(EDITABLE_KEYS))
    if unknown:
        raise ProblemException(
            status.HTTP_400_BAD_REQUEST,
            APIErrorCode.UNKNOWN_SETTING_KEY,
            f"unknown setting key(s): {', '.join(unknown)}",
            extensions={"unknown_keys": unknown, "allowed_keys": list(EDITABLE_KEYS)},
        )
    for key, value in payload.items():
        if key == WATCH_PHRASES_KEY:
            cleaned_list = clean_watch_phrases(value)
            if cleaned_list is None:
                raise _invalid(
                    key,
                    f"{key} must be a list of up to {MAX_WATCH_PHRASES} non-empty "
                    f"strings, each at most {MAX_PHRASE_LENGTH} characters",
                )
            _store(session, key, json.dumps(cleaned_list))
            continue

        if not isinstance(value, str):
            raise _invalid(key, f"{key} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise _invalid(key, f"{key} must not be blank")
        if key in BOOLEAN_KEYS and cleaned not in ("true", "false"):
            raise _invalid(key, f"{key} must be 'true' or 'false'")
        if key == TEXT_SIZE_KEY and cleaned not in TEXT_SIZES:
            raise _invalid(key, f"{key} must be one of {', '.join(TEXT_SIZES)}")
        _store(session, key, cleaned)
    session.commit()
    return settings_view(session)
