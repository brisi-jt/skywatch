"""Contract tests for transcript search on GET /recordings."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlmodel import Session

from conftest import FakeCaptureSource, Seeder
from skywatch.api.app import create_app
from skywatch.api.services.capture import CaptureController
from skywatch.db.engine import create_db_engine
from skywatch.settings import Settings

_ALEMBIC_ROOT = Path(__file__).resolve().parent.parent / "src" / "skywatch" / "db" / "alembic"


def _migrate(db_path):
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_ROOT))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


@pytest.fixture()
def search_env(tmp_path, monkeypatch):
    """A migrated (FTS-enabled) station plus a seeder over the same engine."""
    monkeypatch.setenv("SKYWATCH_CONFIG", str(tmp_path / "no-config.yaml"))
    data_root = tmp_path / "data"
    data_root.mkdir()
    db_path = data_root / "station.db"
    _migrate(db_path)
    engine = create_db_engine(db_path)
    settings = Settings(data_root=data_root, _env_file=None)
    content_dir = tmp_path / "content"
    content_dir.mkdir()

    def make_client(*, fts_available: bool | None = None) -> TestClient:
        capture = CaptureController(engine=engine, settings=settings, source=FakeCaptureSource())
        app = create_app(
            settings,
            engine=engine,
            capture=capture,
            content_dir=content_dir,
            static_dir=tmp_path / "no-static",
            ws_poll_interval=0.05,
            fts_available=fts_available,
        )
        return TestClient(app)

    session = Session(engine)
    seed = Seeder(session, data_root=data_root)
    yield seed, make_client
    session.close()


def test_index_is_available_after_migration(search_env):
    _, make_client = search_env
    with make_client() as client:
        assert client.app.state.fts_available is True


class TestFtsSearch:
    def test_ranked_match_best_first(self, search_env):
        seed, make_client = search_env
        freq = seed.frequency()
        strong = seed.recording(freq, started=datetime(2026, 7, 10, 9, 0, tzinfo=UTC))
        seed.transcript(strong, text="Mayday mayday mayday, engine failure.")
        weak = seed.recording(freq, started=datetime(2026, 7, 10, 10, 0, tzinfo=UTC))
        seed.transcript(weak, text="Tower, mayday relay for another aircraft.")
        seed.recording(freq, started=datetime(2026, 7, 10, 11, 0, tzinfo=UTC))  # no transcript

        with make_client() as client:
            body = client.get("/recordings", params={"q": "mayday"}).json()

        assert [item["id"] for item in body["items"]] == [strong.id, weak.id]
        assert body["total"] == 2

    def test_phrase_search(self, search_env):
        seed, make_client = search_env
        freq = seed.frequency()
        hit = seed.recording(freq)
        seed.transcript(hit, text="Speedbird 472, go around, acknowledge.")
        miss = seed.recording(freq)
        seed.transcript(miss, text="Go left heading two seven zero, then around the hold.")

        with make_client() as client:
            body = client.get("/recordings", params={"q": '"go around"'}).json()

        assert [item["id"] for item in body["items"]] == [hit.id]

    def test_no_matches_returns_empty_page(self, search_env):
        seed, make_client = search_env
        freq = seed.frequency()
        rec = seed.recording(freq)
        seed.transcript(rec, text="Routine position report.")

        with make_client() as client:
            body = client.get("/recordings", params={"q": "helicopter"}).json()

        assert body["items"] == []
        assert body["total"] == 0

    def test_grammar_callsign_and_freq_tokens(self, search_env):
        seed, make_client = search_env
        tower = seed.frequency("Stansted Tower", 123.805)
        guard = seed.frequency("Guard", 121.5)
        on_guard = seed.recording(guard)
        seed.transcript(on_guard, text="Aircraft calling on guard identify.")
        seed.match(on_guard, callsign="BAW2761")
        on_tower = seed.recording(tower)
        seed.transcript(on_tower, text="Tower good morning.")

        with make_client() as client:
            by_freq = client.get("/recordings", params={"q": "freq:121.5"}).json()
            by_label = client.get("/recordings", params={"q": "freq:guard"}).json()
            by_callsign = client.get("/recordings", params={"q": "callsign:BAW2761"}).json()

        assert [i["id"] for i in by_freq["items"]] == [on_guard.id]
        assert [i["id"] for i in by_label["items"]] == [on_guard.id]
        assert [i["id"] for i in by_callsign["items"]] == [on_guard.id]

    def test_grammar_interesting_and_dates(self, search_env):
        seed, make_client = search_env
        freq = seed.frequency()
        old_routine = seed.recording(freq, started=datetime(2026, 7, 5, 9, 0, tzinfo=UTC))
        seed.classification(old_routine, is_interesting=False)
        new_interesting = seed.recording(freq, started=datetime(2026, 7, 12, 9, 0, tzinfo=UTC))
        seed.classification(new_interesting, is_interesting=True)

        with make_client() as client:
            interesting = client.get("/recordings", params={"q": "interesting"}).json()
            after = client.get("/recordings", params={"q": "after:2026-07-10"}).json()

        assert [i["id"] for i in interesting["items"]] == [new_interesting.id]
        assert [i["id"] for i in after["items"]] == [new_interesting.id]

    def test_text_search_composes_with_an_explicit_filter(self, search_env):
        seed, make_client = search_env
        tower = seed.frequency("Stansted Tower", 123.805)
        other = seed.frequency("Approach", 120.625)
        wanted = seed.recording(tower)
        seed.transcript(wanted, text="Emergency descent, mayday.")
        distractor = seed.recording(other)
        seed.transcript(distractor, text="Emergency services on standby, mayday.")

        with make_client() as client:
            body = client.get("/recordings", params={"q": "mayday", "freq_id": tower.id}).json()

        assert [i["id"] for i in body["items"]] == [wanted.id]


class TestLikeFallback:
    def test_search_still_works_without_fts(self, search_env):
        seed, make_client = search_env
        freq = seed.frequency()
        hit = seed.recording(freq)
        seed.transcript(hit, text="Mayday mayday, fuel emergency.")
        miss = seed.recording(freq)
        seed.transcript(miss, text="Routine handoff to approach.")

        with make_client(fts_available=False) as client:
            assert client.app.state.fts_available is False
            body = client.get("/recordings", params={"q": "mayday"}).json()

        assert [i["id"] for i in body["items"]] == [hit.id]

    def test_fallback_ands_multiple_terms(self, search_env):
        seed, make_client = search_env
        freq = seed.frequency()
        both = seed.recording(freq)
        seed.transcript(both, text="Speedbird declaring a fuel mayday.")
        one = seed.recording(freq)
        seed.transcript(one, text="Speedbird routine descent.")

        with make_client(fts_available=False) as client:
            body = client.get("/recordings", params={"q": "speedbird mayday"}).json()

        assert [i["id"] for i in body["items"]] == [both.id]
