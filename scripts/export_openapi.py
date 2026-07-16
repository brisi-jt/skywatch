"""Regenerate the committed OpenAPI snapshot at web/openapi.json.

The dashboard generates its TypeScript types from this file, and a test
fails when it drifts from the live schema. Run after any route or schema
change:

    uv run python scripts/export_openapi.py
"""

import json
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = REPO_ROOT / "web" / "openapi.json"


def main() -> None:
    import os

    from skywatch.api.app import create_app
    from skywatch.settings import Settings

    with tempfile.TemporaryDirectory() as tmp:
        # isolate from any local station config so the schema is deterministic
        os.environ["SKYWATCH_CONFIG"] = str(Path(tmp) / "no-config.yaml")
        settings = Settings(data_root=Path(tmp) / "data", _env_file=None)
        schema = create_app(settings).openapi()
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {SNAPSHOT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
