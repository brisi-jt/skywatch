"""The plane-alert database: curated 'interesting airframe' categories by hex.

A community-maintained CSV lists notable aircraft (military, government,
historic, special liveries, and so on) keyed by their ICAO 24-bit hex. We
use it only to tag a probable-aircraft candidate with its category so the
dashboard can badge it; a missing file simply means no badges. Refresh the
vendored copy with ``scripts/update_plane_alert_db.sh``.
"""

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _normalise_header(name: str) -> str:
    return name.strip().lstrip("$#").strip().lower()


class PlaneAlertDb:
    """ICAO24 hex → curated category (e.g. ``Military``), from the CSV."""

    def __init__(self, by_icao: dict[str, str]) -> None:
        self._by_icao = by_icao

    def __len__(self) -> int:
        return len(self._by_icao)

    @classmethod
    def load(cls, path: Path) -> "PlaneAlertDb":
        """Load the database; an absent file yields an empty (no-op) instance."""
        path = Path(path)
        if not path.is_file():
            logger.info("plane-alert database not present at %s; badges disabled", path)
            return cls({})
        by_icao: dict[str, str] = {}
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.reader(handle)
            try:
                header = [_normalise_header(col) for col in next(reader)]
            except StopIteration:
                return cls({})
            try:
                icao_idx = header.index("icao")
                cat_idx = header.index("category")
            except ValueError:
                logger.warning("plane-alert CSV missing an icao/category column; badges disabled")
                return cls({})
            for row in reader:
                if len(row) <= max(icao_idx, cat_idx):
                    continue
                icao = row[icao_idx].strip().lower()
                category = row[cat_idx].strip()
                if icao and category:
                    by_icao[icao] = category
        return cls(by_icao)

    def lookup(self, icao24: str | None) -> str | None:
        if not icao24:
            return None
        return self._by_icao.get(icao24.strip().lower())
