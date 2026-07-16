"""Mode-aware validation of the active frequency set.

Multichannel capture records every channel simultaneously, but only within
one tuner window: at 2.56 Msps roughly 2.4 MHz is usable once the rolled-off
band edges are discarded. Scan mode accepts any spread of frequencies at the
cost of hopping — transmissions on the channels not currently tuned are lost.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from skywatch.db.models import Frequency

USABLE_WINDOW_MHZ = 2.4
"""Usable slice of the 2.56 MHz tuner window, edges discarded."""

DC_AVOID_MHZ = 0.025
"""Keep the centre frequency at least this far from every channel: the
tuner puts a DC spike at the centre of the window."""

_NUDGE_STEPS_MHZ = (0.0, 0.1, -0.1, 0.2, -0.2, 0.3, -0.3)

_EPSILON_MHZ = 1e-6
"""Float-comparison slack (1 Hz) so an exactly-window-wide span fits."""

SCAN_CONCURRENCY_WARNING = (
    "scan mode hops between frequencies, so transmissions on the channels "
    "not currently tuned are missed; multichannel mode records all channels "
    "at once when they fit one tuner window"
)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggested_centerfreq_mhz: float | None = None
    """Centre frequency for the plan when it fits, or for the largest
    fitting subset when it does not."""
    offenders: list[str] = field(default_factory=list)
    """Labels of frequencies that would have to be deactivated to fit."""


def pick_centerfreq(freqs_mhz: Sequence[float]) -> float:
    """A centre frequency whose window covers every channel, avoiding the
    DC spike landing on any of them.

    Callers must pass a set already known to span at most
    ``USABLE_WINDOW_MHZ``.
    """
    lo, hi = min(freqs_mhz), max(freqs_mhz)
    half = USABLE_WINDOW_MHZ / 2
    valid_lo, valid_hi = hi - half, lo + half
    midpoint = (lo + hi) / 2
    for step in _NUDGE_STEPS_MHZ:
        candidate = midpoint + step
        if not valid_lo <= candidate <= valid_hi:
            continue
        if all(abs(candidate - f) >= DC_AVOID_MHZ for f in freqs_mhz):
            return round(candidate, 4)
    return round(midpoint, 4)


def _best_window(freqs: Sequence[Frequency]) -> list[Frequency]:
    """The largest subset of channels that fits one usable window."""
    ordered = sorted(freqs, key=lambda f: f.mhz)
    best: list[Frequency] = []
    for anchor in ordered:
        upper = anchor.mhz + USABLE_WINDOW_MHZ + _EPSILON_MHZ
        covered = [f for f in ordered if anchor.mhz <= f.mhz <= upper]
        if len(covered) > len(best):
            best = covered
    return best


def validate_frequencies(freqs: Sequence[Frequency], mode: str) -> ValidationResult:
    """Check whether the active frequency set is capturable in ``mode``."""
    if not freqs:
        return ValidationResult(
            ok=False,
            errors=["no active frequencies: activate at least one channel before capturing"],
        )

    if mode == "scan":
        return ValidationResult(ok=True, warnings=[SCAN_CONCURRENCY_WARNING])

    ordered = sorted(freqs, key=lambda f: f.mhz)
    span = ordered[-1].mhz - ordered[0].mhz
    if span <= USABLE_WINDOW_MHZ + _EPSILON_MHZ:
        return ValidationResult(
            ok=True,
            suggested_centerfreq_mhz=pick_centerfreq([f.mhz for f in ordered]),
        )

    keep = _best_window(ordered)
    offenders = [f for f in ordered if f not in keep]
    offender_list = ", ".join(f"{f.label} ({f.mhz:.3f} MHz)" for f in offenders)
    keep_center = pick_centerfreq([f.mhz for f in keep])
    error = (
        f"active frequencies span {span:.3f} MHz but only {USABLE_WINDOW_MHZ} MHz is "
        f"usable within one 2.56 MHz tuner window in multichannel mode. "
        f"Deactivate {offender_list} to keep the largest fitting group of "
        f"{len(keep)} channels (centre frequency {keep_center} MHz), or switch "
        f"capture mode to scan to cycle through all of them"
    )
    return ValidationResult(
        ok=False,
        errors=[error],
        suggested_centerfreq_mhz=keep_center,
        offenders=[f.label for f in offenders],
    )
