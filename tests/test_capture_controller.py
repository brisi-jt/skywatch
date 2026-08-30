"""CaptureController: every restart path honours the worker's disk pause."""

from sqlmodel import Session

from conftest import FakeCaptureSource
from skywatch.api.services.capture import CaptureController
from skywatch.db.models import Setting
from skywatch.pipeline.retention import CAPTURE_PAUSED_KEY
from skywatch.settings import Settings


def _controller(engine, tmp_path) -> tuple[CaptureController, FakeCaptureSource]:
    settings = Settings(data_root=tmp_path / "data", _env_file=None)
    source = FakeCaptureSource()
    return CaptureController(engine=engine, settings=settings, source=source), source


def test_restart_starts_when_not_paused(engine, tmp_path):
    capture, source = _controller(engine, tmp_path)
    restarted, warning = capture.restart(has_active=True)
    assert restarted is True
    assert warning is None
    assert source.calls == ["stop", "start"]


def test_restart_leaves_capture_paused_for_disk(engine, tmp_path):
    """A low-disk pause must survive any restart — deep tune exit included.

    The worker is the only process allowed to clear the pause, so restart
    stops the source but never starts it again while the flag is set.
    """
    capture, source = _controller(engine, tmp_path)
    with Session(engine) as s:
        s.add(Setting(key=CAPTURE_PAUSED_KEY, value="1"))
        s.commit()

    restarted, warning = capture.restart(has_active=True)

    assert restarted is False
    assert "paused" in (warning or "")
    assert source.calls == ["stop"]
