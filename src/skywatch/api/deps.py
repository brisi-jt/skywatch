"""Request-scoped dependencies shared by the route modules."""

from collections.abc import Iterator
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlmodel import Session

from skywatch.api.services.capture import CaptureController
from skywatch.api.services.deep_tune import DeepTuneManager
from skywatch.settings import Settings


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_capture(request: Request) -> CaptureController:
    return request.app.state.capture


def get_deep_tune(request: Request) -> DeepTuneManager:
    return request.app.state.deep_tune


def get_timezone(request: Request) -> ZoneInfo:
    return request.app.state.timezone


def get_fts_available(request: Request) -> bool:
    return request.app.state.fts_available


def get_classifier_chain(request: Request) -> list:
    """The LLM provider chain the API uses for on-demand narrative summaries."""
    return request.app.state.classifier_chain
