"""Callsign to airline resolution from the vendored OpenFlights data.

Airline callsigns open with a three-letter ICAO operator code (BAW472 is
British Airways); the marketed flight number is NOT derivable from free
data, so ``flight_number_guess`` swaps in the IATA code as a clearly
labelled heuristic and callers must present it as probable, never as fact.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

_CALLSIGN_RE = re.compile(r"^(?P<icao>[A-Z]{3})(?P<suffix>[A-Z0-9]*)$")


@dataclass(frozen=True)
class Airline:
    name: str
    icao: str
    iata: str | None
    radio: str | None = None
    """The spoken R/T callsign (e.g. SPEEDBIRD for BAW), when published."""


class AirlineDirectory:
    """ICAO operator code → airline, loaded from OpenFlights ``airlines.dat``."""

    def __init__(self, by_icao: dict[str, Airline]) -> None:
        self._by_icao = by_icao

    @classmethod
    def load(cls, path: Path) -> "AirlineDirectory":
        by_icao: dict[str, Airline] = {}
        with open(path, encoding="utf-8", errors="replace") as handle:
            for row in csv.reader(handle):
                if len(row) < 8:
                    continue
                _, name, _alias, iata, icao, callsign, _country, active = row[:8]
                if len(icao) != 3 or not icao.isalpha() or icao == "N/A":
                    continue
                icao = icao.upper()
                radio = callsign.strip() or None
                if radio in (r"\N", "N/A"):
                    radio = None
                airline = Airline(
                    name=name,
                    icao=icao,
                    iata=iata if len(iata) == 2 and iata != "-" else None,
                    radio=radio,
                )
                # Later rows only displace an earlier one if the earlier
                # airline was defunct and this one is active.
                if icao not in by_icao or active == "Y":
                    by_icao[icao] = airline
        return cls(by_icao)

    def lookup_callsign(self, callsign: str | None) -> Airline | None:
        if not callsign:
            return None
        match = _CALLSIGN_RE.match(callsign.strip().upper())
        if match is None:
            return None
        return self._by_icao.get(match["icao"])


def flight_number_guess(callsign: str | None, airline: Airline | None) -> str | None:
    """Probable marketed flight number, e.g. BAW472 + British Airways → BA472.

    Heuristic only: the numeric part of a callsign frequently differs from
    the marketed flight number. Returns ``None`` whenever any ingredient is
    missing rather than guessing harder.
    """
    if not callsign or airline is None or airline.iata is None:
        return None
    match = _CALLSIGN_RE.match(callsign.strip().upper())
    if match is None:
        return None
    suffix = match["suffix"]
    if not suffix or not any(ch.isdigit() for ch in suffix):
        return None
    return f"{airline.iata}{suffix}"
