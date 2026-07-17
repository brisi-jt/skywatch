"""Error surface: every failure is an RFC 7807 problem detail.

All error responses share one JSON shape (``ProblemDetail``) served as
``application/problem+json``: ``title``/``status``/``detail`` plus a stable
machine-readable ``code`` the dashboard can switch on. Some problems carry
extra fields (a window conflict includes ``offenders`` and
``suggested_centerfreq_mhz``); those are additive extensions to the same
shape.
"""

import logging
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"


class APIErrorCode(StrEnum):
    """Stable machine-readable error codes for problem responses."""

    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    FREQUENCY_NOT_FOUND = "frequency_not_found"
    RECORDING_NOT_FOUND = "recording_not_found"
    DOCUMENT_NOT_FOUND = "document_not_found"
    AUDIO_DELETED = "audio_deleted"
    AUDIO_FILE_MISSING = "audio_file_missing"
    WINDOW_CONFLICT = "window_conflict"
    UNKNOWN_SETTING_KEY = "unknown_setting_key"
    INVALID_SETTING_VALUE = "invalid_setting_value"
    TUNING_INVALID_VALUE = "tuning_invalid_value"
    TUNING_UNKNOWN_FREQUENCY = "tuning_unknown_frequency"
    DEEP_TUNE_UNAVAILABLE = "deep_tune_unavailable"
    DEEP_TUNE_ACTIVE = "deep_tune_active"
    DEEP_TUNE_NOT_ACTIVE = "deep_tune_not_active"
    RECORDING_NOT_CLASSIFIABLE = "recording_not_classifiable"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    INTERNAL_ERROR = "internal_error"


class ProblemDetail(BaseModel):
    """RFC 7807 problem details; the body of every error response."""

    model_config = ConfigDict(extra="allow")

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: APIErrorCode


class ProblemException(Exception):
    """Raise from any handler to return a problem-details response."""

    def __init__(
        self,
        status_code: int,
        code: APIErrorCode,
        detail: str,
        *,
        title: str | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.title = title or HTTPStatus(status_code).phrase
        self.extensions = extensions or {}


def problem_response(
    status_code: int,
    code: APIErrorCode,
    detail: str,
    *,
    title: str | None = None,
    extensions: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ProblemDetail(
        title=title or HTTPStatus(status_code).phrase,
        status=status_code,
        detail=detail,
        code=code,
    ).model_dump()
    body.update(extensions or {})
    return JSONResponse(body, status_code=status_code, media_type=PROBLEM_MEDIA_TYPE)


_HTTP_CODE_MAP = {
    status.HTTP_404_NOT_FOUND: APIErrorCode.NOT_FOUND,
    status.HTTP_405_METHOD_NOT_ALLOWED: APIErrorCode.METHOD_NOT_ALLOWED,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemException)
    async def _problem_exception(request: Request, exc: ProblemException) -> JSONResponse:
        return problem_response(
            exc.status_code, exc.code, exc.detail, title=exc.title, extensions=exc.extensions
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "loc": [str(part) for part in error.get("loc", [])],
                "msg": error.get("msg", ""),
                "type": error.get("type", ""),
            }
            for error in exc.errors()
        ]
        return problem_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            APIErrorCode.VALIDATION_ERROR,
            "one or more request parameters failed validation",
            extensions={"errors": errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("unhandled HTTP %s on %s: %s", exc.status_code, request.url, exc.detail)
        code = _HTTP_CODE_MAP.get(exc.status_code, APIErrorCode.INTERNAL_ERROR)
        return problem_response(exc.status_code, code, str(exc.detail))
