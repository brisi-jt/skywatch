"""Grow the eval set from clips where listeners overruled the classifier.

Reads the station database, finds clips whose listener votes disagree with
the classifier's verdict, and appends them to ``content/eval_set.yaml`` with
the listener verdict as the expected label — turning real corrections into
regression fixtures. Skips clips already in the manifest. Run on the dev box:

    uv run python scripts/append_eval_disagreements.py           # append
    uv run python scripts/append_eval_disagreements.py --dry-run # preview
"""

import argparse
import os
from pathlib import Path

import yaml
from sqlmodel import Session

from skywatch.api.services.eval_feedback import collect_verdicts
from skywatch.db.engine import create_db_engine, default_db_path
from skywatch.db.models import Frequency
from skywatch.settings import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_SET = REPO_ROOT / "content" / "eval_set.yaml"


def _entry(session: Session, verdict, data_root: Path) -> dict:
    frequency = session.get(Frequency, verdict.recording.freq_id)
    audio_path = (data_root / verdict.recording.file_path).resolve()
    try:
        file_ref = os.path.relpath(audio_path, REPO_ROOT)
    except ValueError:
        file_ref = str(audio_path)
    if verdict.human_interesting:
        category = (
            verdict.classification.category.value
            if verdict.classification.is_interesting
            else "other"
        )
    else:
        category = "routine"
    return {
        "file": file_ref,
        "frequency_label": frequency.label if frequency else "unknown",
        "frequency_category": frequency.category.value if frequency else "tower",
        "duration_s": round(verdict.recording.duration_s, 1),
        "expected_interesting": verdict.human_interesting,
        "expected_category": category,
        "notes": (
            f"listener disagreement: classifier said "
            f"{'interesting' if verdict.classification.is_interesting else 'routine'}, "
            f"votes {verdict.up} up / {verdict.down} down"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Append feedback disagreements to the eval set")
    parser.add_argument("--dry-run", action="store_true", help="print entries without writing")
    args = parser.parse_args()

    settings = Settings()
    engine = create_db_engine(default_db_path(settings.data_root))
    existing = yaml.safe_load(EVAL_SET.read_text()) or {"clips": []}
    known_files = {clip["file"] for clip in existing.get("clips", [])}

    new_entries: list[dict] = []
    with Session(engine) as session:
        for verdict in collect_verdicts(session):
            if verdict.classification.is_interesting == verdict.human_interesting:
                continue
            entry = _entry(session, verdict, settings.data_root)
            if entry["file"] not in known_files:
                new_entries.append(entry)
                known_files.add(entry["file"])

    if not new_entries:
        print("No new disagreements to append.")
        return

    block = yaml.safe_dump(
        new_entries, default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    indented = "\n".join(f"  {line}" if line.strip() else line for line in block.splitlines())
    if args.dry_run:
        print(f"Would append {len(new_entries)} entrie(s):\n{indented}")
        return

    with open(EVAL_SET, "a", encoding="utf-8") as handle:
        handle.write("\n" + indented + "\n")
    print(f"Appended {len(new_entries)} entrie(s) to {EVAL_SET}")


if __name__ == "__main__":
    main()
