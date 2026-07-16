from pathlib import Path

import yaml
from sqlmodel import Session, select

from skywatch.db.models import Frequency
from skywatch.db.seed import DEFAULT_FREQUENCIES_PATH, seed_frequencies

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN_PATH = REPO_ROOT / "content" / "default_frequencies.yaml"

MAX_WINDOW_MHZ = 2.4  # usable slice of the 2.56 MHz tuner window


def _plan_entries() -> list[dict]:
    return yaml.safe_load(PLAN_PATH.read_text())["frequencies"]


def test_default_plan_path_points_at_content():
    assert Path("content/default_frequencies.yaml") == DEFAULT_FREQUENCIES_PATH
    assert PLAN_PATH.is_file()


def test_default_plan_only_guard_is_verified():
    entries = _plan_entries()
    verified = [e for e in entries if e["verified"]]
    assert len(verified) == 1
    assert verified[0]["mhz"] == 121.5
    assert all(e["verified"] is False for e in entries if e["mhz"] != 121.5)


def test_default_plan_tuner_groups_fit_one_window():
    entries = _plan_entries()
    groups: dict[int, list[float]] = {}
    for e in entries:
        groups.setdefault(e["tuner_group"], []).append(e["mhz"])
    for group, freqs in groups.items():
        span = max(freqs) - min(freqs)
        assert span <= MAX_WINDOW_MHZ, f"tuner_group {group} spans {span:.3f} MHz"


def test_seed_inserts_full_default_plan(engine):
    entries = _plan_entries()
    with Session(engine) as s:
        result = seed_frequencies(s, PLAN_PATH)
        s.commit()

    assert result.inserted == len(entries)
    assert result.updated == 0

    with Session(engine) as s:
        rows = s.exec(select(Frequency)).all()
    assert len(rows) == len(entries)

    guard = next(r for r in rows if r.mhz == 121.5)
    assert guard.verified is True
    assert guard.is_active is True
    assert all(r.verified is False for r in rows if r.mhz != 121.5)


def test_seed_is_idempotent(engine):
    with Session(engine) as s:
        seed_frequencies(s, PLAN_PATH)
        s.commit()
    with Session(engine) as s:
        result = seed_frequencies(s, PLAN_PATH)
        s.commit()

    assert result.inserted == 0
    assert result.updated == 0

    with Session(engine) as s:
        rows = s.exec(select(Frequency)).all()
    assert len(rows) == len(_plan_entries())


def test_seed_never_clobbers_is_active(engine):
    with Session(engine) as s:
        seed_frequencies(s, PLAN_PATH)
        s.commit()

    # Operator flips activation away from the shipped defaults.
    with Session(engine) as s:
        guard = s.exec(select(Frequency).where(Frequency.mhz == 121.5)).one()
        guard.is_active = False
        other = s.exec(select(Frequency).where(Frequency.mhz != 121.5)).first()
        other.is_active = True
        other_id = other.id
        s.add(guard)
        s.add(other)
        s.commit()

    with Session(engine) as s:
        seed_frequencies(s, PLAN_PATH)
        s.commit()

    with Session(engine) as s:
        guard = s.exec(select(Frequency).where(Frequency.mhz == 121.5)).one()
        other = s.get(Frequency, other_id)
        assert guard.is_active is False
        assert other.is_active is True


def test_seed_updates_changed_metadata(engine, tmp_path):
    with Session(engine) as s:
        seed_frequencies(s, PLAN_PATH)
        s.commit()

    plan = yaml.safe_load(PLAN_PATH.read_text())
    target = plan["frequencies"][0]
    target["description"] = "Amended description from a newer plan."
    modified = tmp_path / "frequencies.yaml"
    modified.write_text(yaml.safe_dump(plan))

    with Session(engine) as s:
        result = seed_frequencies(s, modified)
        s.commit()

    assert result.inserted == 0
    assert result.updated == 1

    with Session(engine) as s:
        row = s.exec(
            select(Frequency).where(
                Frequency.label == target["label"], Frequency.mhz == target["mhz"]
            )
        ).one()
    assert row.description == "Amended description from a newer plan."
