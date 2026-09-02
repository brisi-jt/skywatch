"""Aircraft identity from the OpenSky aircraft database (icao24 → who/what).

The OpenSky metadata CSV maps a 24-bit ICAO hex to a registration, type
code, and operator. It is large (~70 MB) and effectively unlicensed with a
citation request, so it is never committed — fetch it with
``scripts/fetch_aircraft_db.sh``. A missing file yields an empty lookup, so
enrichment simply leaves the identity columns null.
"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AircraftInfo:
    registration: str | None
    aircraft_type: str | None
    operator_name: str | None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class AircraftDb:
    """ICAO24 hex → registration/type/operator, from the OpenSky metadata CSV."""

    def __init__(self, by_icao: dict[str, AircraftInfo]) -> None:
        self._by_icao = by_icao

    def __len__(self) -> int:
        return len(self._by_icao)

    @classmethod
    def load(cls, path: Path) -> "AircraftDb":
        """Load the database; an absent file yields an empty (no-op) instance."""
        path = Path(path)
        if not path.is_file():
            logger.info("aircraft database not present at %s; identity disabled", path)
            return cls({})
        by_icao: dict[str, AircraftInfo] = {}
        with open(path, encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = {name.strip().lower(): name for name in (reader.fieldnames or [])}
            icao_key = fields.get("icao24")
            if icao_key is None:
                logger.warning("aircraft database CSV has no icao24 column; identity disabled")
                return cls({})
            reg_key = fields.get("registration")
            type_key = fields.get("typecode") or fields.get("model")
            operator_key = fields.get("operator")
            for row in reader:
                icao = (row.get(icao_key) or "").strip().lower()
                if not icao:
                    continue
                info = AircraftInfo(
                    registration=_clean(row.get(reg_key)) if reg_key else None,
                    aircraft_type=_clean(row.get(type_key)) if type_key else None,
                    operator_name=_clean(row.get(operator_key)) if operator_key else None,
                )
                if info.registration or info.aircraft_type or info.operator_name:
                    by_icao[icao] = info
        return cls(by_icao)

    def lookup(self, icao24: str | None) -> AircraftInfo | None:
        if not icao24:
            return None
        return self._by_icao.get(icao24.strip().lower())
