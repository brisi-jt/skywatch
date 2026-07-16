"""The contract every capture source honours.

A capture source is anything that makes clip files appear in the recordings
directory: a live rtl_airband process, or a fixture replay during
development. The pipeline worker only ever talks to this protocol.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceStatus:
    """A point-in-time snapshot of a capture source."""

    running: bool
    detail: str = ""


@runtime_checkable
class CaptureSource(Protocol):
    def start(self) -> None:
        """Begin producing clip files. Idempotent when already running."""
        ...

    def stop(self) -> None:
        """Stop producing clip files. Idempotent when already stopped."""
        ...

    def status(self) -> SourceStatus:
        """Report whether the source is currently producing."""
        ...
