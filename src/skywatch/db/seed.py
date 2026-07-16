"""Idempotent seeding of the frequency plan from a YAML file.

Rows are matched on (label, mhz). New rows are inserted with the YAML's
``is_active`` value; existing rows have their descriptive fields refreshed
but ``is_active`` is never touched — activation belongs to the operator.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlmodel import Session, select

from skywatch.db.enums import FrequencyCategory, FrequencyMode
from skywatch.db.models import Frequency

DEFAULT_FREQUENCIES_PATH = Path("content/default_frequencies.yaml")

_REFRESHED_FIELDS = ("mode", "facility", "category", "description", "tuner_group", "verified")


@dataclass(frozen=True)
class SeedResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0


def load_frequency_plan(yaml_path: Path) -> list[Frequency]:
    entries = yaml.safe_load(yaml_path.read_text())["frequencies"]
    return [
        Frequency(
            label=entry["label"],
            mhz=float(entry["mhz"]),
            mode=FrequencyMode(entry["mode"]),
            facility=entry["facility"],
            category=FrequencyCategory(entry["category"]),
            description=entry["description"],
            is_active=entry["is_active"],
            tuner_group=entry["tuner_group"],
            verified=entry["verified"],
        )
        for entry in entries
    ]


def seed_frequencies(session: Session, yaml_path: Path) -> SeedResult:
    """Upsert the frequency plan into the session; caller commits."""
    inserted = updated = unchanged = 0
    for planned in load_frequency_plan(yaml_path):
        existing = session.exec(
            select(Frequency).where(Frequency.label == planned.label, Frequency.mhz == planned.mhz)
        ).one_or_none()

        if existing is None:
            session.add(planned)
            inserted += 1
            continue

        changed = False
        for field in _REFRESHED_FIELDS:
            new_value = getattr(planned, field)
            if getattr(existing, field) != new_value:
                setattr(existing, field, new_value)
                changed = True
        if changed:
            session.add(existing)
            updated += 1
        else:
            unchanged += 1

    return SeedResult(inserted=inserted, updated=updated, unchanged=unchanged)


def main() -> None:
    from skywatch.db.engine import create_db_engine, default_db_path, session_scope
    from skywatch.settings import Settings

    settings = Settings()
    engine = create_db_engine(default_db_path(settings.data_root))
    with session_scope(engine) as session:
        result = seed_frequencies(session, DEFAULT_FREQUENCIES_PATH)
    print(
        f"frequency plan seeded: {result.inserted} inserted, "
        f"{result.updated} updated, {result.unchanged} unchanged"
    )


if __name__ == "__main__":
    main()
