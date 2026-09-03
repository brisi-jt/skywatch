"""The clip-library search mini-grammar.

A single ``q`` string carries both free text and a few structured filters, so
the search box can stay one field. Free words and quoted phrases become the
full-text query; a handful of ``key:value`` tokens become filters:

- ``freq:<mhz-or-label>`` — only clips on a matching frequency
- ``callsign:<x>`` — only clips with a matching aircraft candidate
- ``interesting`` — only clips whose latest verdict is interesting
- ``before:<date>`` / ``after:<date>`` — ISO dates (``YYYY-MM-DD``)

Anything that does not parse as one of those — a malformed date, an empty
value, an unknown key — falls back to being searched as plain text rather
than raising, so the box never punishes a typo with an error.

:func:`parse_search` is a pure function: give it the raw string, get back a
:class:`ParsedSearch`. All query building happens elsewhere.
"""

import re
from dataclasses import dataclass
from datetime import date

# A token is an optional ``key:`` prefix followed by either a quoted span
# (which may contain spaces) or a run of non-space, non-quote characters.
_TOKEN = re.compile(r'(?P<key>[a-zA-Z]+:)?(?:"(?P<quoted>[^"]*)"|(?P<word>[^\s"]+))')

_INTERESTING = "interesting"
_STRUCTURED_KEYS = {"freq", "callsign", "before", "after"}


@dataclass(frozen=True)
class ParsedSearch:
    """The structured result of parsing a search box string."""

    text_terms: tuple[str, ...] = ()
    """Free words and phrases, in order, for the full-text / LIKE query."""
    fts_match: str | None = None
    """A ready-to-use FTS5 MATCH string, or None when there is no free text."""
    freq: str | None = None
    callsign: str | None = None
    interesting: bool = False
    after: date | None = None
    before: date | None = None

    @property
    def has_text(self) -> bool:
        return bool(self.text_terms)


def _fts_match(terms: list[str]) -> str | None:
    """Build an FTS5 MATCH string that ANDs every term, each quoted.

    Quoting each term (and doubling any embedded quote) keeps user input away
    from FTS5 operator syntax, so a stray ``-`` or ``:`` searches literally
    instead of raising a query error. A multi-word phrase stays adjacent.
    """
    if not terms:
        return None
    quoted = [f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms]
    return " ".join(quoted)


def parse_search(q: str | None) -> ParsedSearch:
    """Parse a raw search box string into text and structured filters."""
    if not q or not q.strip():
        return ParsedSearch()

    terms: list[str] = []
    freq: str | None = None
    callsign: str | None = None
    interesting = False
    after: date | None = None
    before: date | None = None

    for match in _TOKEN.finditer(q):
        raw = match.group(0)
        key = match.group("key")
        value = match.group("quoted")
        if value is None:
            value = match.group("word")

        if key is not None:
            name = key[:-1].lower()
            if name in _STRUCTURED_KEYS and value:
                if name == "freq":
                    freq = value
                    continue
                if name == "callsign":
                    callsign = value
                    continue
                parsed = _parse_date(value)
                if parsed is not None:
                    if name == "after":
                        after = parsed
                    else:
                        before = parsed
                    continue
            # Unknown key, empty value, or unparseable date: search literally.
            terms.append(raw)
            continue

        if match.group("quoted") is None and value.lower() == _INTERESTING:
            interesting = True
            continue

        terms.append(value)

    return ParsedSearch(
        text_terms=tuple(terms),
        fts_match=_fts_match(terms),
        freq=freq,
        callsign=callsign,
        interesting=interesting,
        after=after,
        before=before,
    )


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
