"""The committed OpenAPI snapshot must match what the app actually serves.

The dashboard generates its TypeScript types from ``web/openapi.json``;
regenerate it with ``uv run python scripts/export_openapi.py`` whenever a
route or schema changes.
"""

import json

from conftest import REPO_ROOT

SNAPSHOT = REPO_ROOT / "web" / "openapi.json"


class TestOpenAPISnapshot:
    def test_snapshot_matches_live_schema(self, station):
        committed = json.loads(SNAPSHOT.read_text())
        live = station.app.openapi()
        assert committed == live, (
            "web/openapi.json is stale; regenerate it with "
            "`uv run python scripts/export_openapi.py` and commit the result"
        )

    def test_no_aircraft_live_route(self, station):
        # live aircraft positions need hardware this station does not have;
        # the contract must not advertise the route
        assert not any("/aircraft" in path for path in station.app.openapi()["paths"])

    def test_descriptions_present_on_every_operation(self, station):
        schema = station.app.openapi()
        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                assert operation.get("description") or operation.get("summary"), (
                    f"{method.upper()} {path} has no description"
                )
