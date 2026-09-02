"""Turn an ICAO callsign into the words a controller would actually speak.

``BAW2761`` becomes ``speedbird two seven six one`` — the airline's R/T
callsign (from the vendored airlines database) followed by each digit as a
word. Unknown operator prefixes and any letters fall back to the phonetic
alphabet. These spoken forms bias the recogniser towards callsigns it would
otherwise mangle; contextual biasing has been shown to lift callsign
recognition substantially in ATC speech.
"""

import re
from collections.abc import Iterable

from skywatch.providers.flightdata.airlines import AirlineDirectory

_CALLSIGN_RE = re.compile(r"^(?P<icao>[A-Z]{3})(?P<suffix>[A-Z0-9]*)$")

# Plain English number words (not the "niner/tree" R/T variants) because the
# recogniser is trained on ordinary speech and emits these forms.
NUMBER_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}

NATO_LETTERS = {
    "A": "alpha",
    "B": "bravo",
    "C": "charlie",
    "D": "delta",
    "E": "echo",
    "F": "foxtrot",
    "G": "golf",
    "H": "hotel",
    "I": "india",
    "J": "juliett",
    "K": "kilo",
    "L": "lima",
    "M": "mike",
    "N": "november",
    "O": "oscar",
    "P": "papa",
    "Q": "quebec",
    "R": "romeo",
    "S": "sierra",
    "T": "tango",
    "U": "uniform",
    "V": "victor",
    "W": "whiskey",
    "X": "xray",
    "Y": "yankee",
    "Z": "zulu",
}


def _speak_chars(chars: str) -> list[str]:
    words: list[str] = []
    for char in chars:
        if char in NUMBER_WORDS:
            words.append(NUMBER_WORDS[char])
        elif char in NATO_LETTERS:
            words.append(NATO_LETTERS[char])
    return words


def verbalize_callsign(callsign: str | None, airlines: AirlineDirectory | None) -> str | None:
    """The spoken form of one callsign, or None when it cannot be parsed.

    The airline's radio name is used for the operator prefix when known and
    the directory is available; otherwise the prefix is spelled phonetically.
    """
    if not callsign:
        return None
    match = _CALLSIGN_RE.match(callsign.strip().upper())
    if match is None:
        return None
    icao, suffix = match["icao"], match["suffix"]

    airline = airlines.lookup_callsign(callsign) if airlines is not None else None
    if airline is not None and airline.radio:
        prefix_words = [airline.radio.lower()]
    else:
        prefix_words = _speak_chars(icao)

    words = prefix_words + _speak_chars(suffix)
    spoken = " ".join(words).strip()
    return spoken or None


def verbalize_callsigns(
    callsigns: Iterable[str | None], airlines: AirlineDirectory | None
) -> list[str]:
    """Spoken forms for a set of callsigns, de-duplicated, order preserved."""
    seen: dict[str, None] = {}
    for callsign in callsigns:
        spoken = verbalize_callsign(callsign, airlines)
        if spoken and spoken not in seen:
            seen[spoken] = None
    return list(seen)
