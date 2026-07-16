"""Request-scoped dependencies shared by the route modules."""

from collections.abc import Iterator
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlmodel import Session

from skywatch.api.services.capture import CaptureController
from skywatch.settings import Settings


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_capture(request: Request) -> CaptureController:
    return request.app.state.capture


def get_timezone(request: Request) -> ZoneInfo:
    return request.app.state.timezone
