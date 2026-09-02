"""Owner-editable station settings behind GET/PATCH /settings.

Only whitelisted keys are readable or writable here. The settings table
also carries worker-internal state (like the disk-guard pause flag), which
is deliberately outside this surface — it is reported via /status instead.
"""

from sqlmodel import Session
from starlette import status

from skywatch.api.errors import APIErrorCode, ProblemException
from skywatch.api.schemas import Link, SettingsResponse
from skywatch.db.models import Setting

WALKTHROUGH_KEY = "tuning.walkthrough_done"
FIRST_CLIP_CELEBRATED_KEY = "first_clip_celebrated"
EARCON_ENABLED_KEY = "earcon_enabled"

EDITABLE_KEYS = (
    "station_name",
    WALKTHROUGH_KEY,
    FIRST_CLIP_CELEBRATED_KEY,
    EARCON_ENABLED_KEY,
)

# Keys that hold a boolean, stored as the strings "true" / "false".
BOOLEAN_KEYS = (WALKTHROUGH_KEY, FIRST_CLIP_CELEBRATED_KEY, EARCON_ENABLED_KEY)


def _flag(session: Session, key: str) -> bool:
    row = session.get(Setting, key)
    return row is not None and row.value == "true"


def settings_view(session: Session) -> SettingsResponse:
    row = session.get(Setting, "station_name")
    return SettingsResponse(
        station_name=row.value if row is not None else None,
        tuning_walkthrough_done=_flag(session, WALKTHROUGH_KEY),
        first_clip_celebrated=_flag(session, FIRST_CLIP_CELEBRATED_KEY),
        earcon_enabled=_flag(session, EARCON_ENABLED_KEY),
        links={"self": Link(href="/settings")},
    )


def apply_patch(session: Session, payload: dict[str, str]) -> SettingsResponse:
    unknown = sorted(set(payload) - set(EDITABLE_KEYS))
    if unknown:
        raise ProblemException(
            status.HTTP_400_BAD_REQUEST,
            APIErrorCode.UNKNOWN_SETTING_KEY,
            f"unknown setting key(s): {', '.join(unknown)}",
            extensions={"unknown_keys": unknown, "allowed_keys": list(EDITABLE_KEYS)},
        )
    for key, value in payload.items():
        cleaned = value.strip()
        if not cleaned:
            raise ProblemException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                APIErrorCode.INVALID_SETTING_VALUE,
                f"{key} must not be blank",
            )
        if key in BOOLEAN_KEYS and cleaned not in ("true", "false"):
            raise ProblemException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                APIErrorCode.INVALID_SETTING_VALUE,
                f"{key} must be 'true' or 'false'",
            )
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=cleaned))
        else:
            row.value = cleaned
            session.add(row)
    session.commit()
    return settings_view(session)
