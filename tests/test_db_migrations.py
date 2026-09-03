from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

from skywatch.db import fts
from skywatch.db.fts import include_name

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "frequencies",
    "recordings",
    "transcripts",
    "transcript_segments",
    "classifications",
    "aircraft_matches",
    "feedback",
    "api_usage",
    "settings",
    "incidents",
    "incident_clips",
}

# The revision that shipped before the U3 additive migrations, used to prove
# they apply cleanly on top of a database that already holds rows.
PRE_U3_REVISION = "4f41a40b5f5d"

# The revision that shipped before the U6a additive migrations (stars,
# incidents), used to prove they apply cleanly on top of a populated database.
PRE_U6A_REVISION = "d3f8a1c2b4e6"


def _alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(REPO_ROOT / "src" / "skywatch" / "db" / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return cfg


def test_migrations_apply_from_empty_database(tmp_path):
    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path), "head")

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    tables = set(inspector.get_table_names())
    assert tables >= EXPECTED_TABLES
    assert "alembic_version" in tables


def test_migrations_create_missing_data_directory(tmp_path):
    db_path = tmp_path / "data" / "nested" / "station.db"
    assert not db_path.parent.exists()

    command.upgrade(_alembic_config(db_path), "head")

    inspector = inspect(create_engine(f"sqlite:///{db_path}"))
    assert set(inspector.get_table_names()) >= EXPECTED_TABLES


def test_migrations_apply_on_populated_pre_u3_database(tmp_path):
    """Additive U3 migrations must apply on a DB that already holds rows."""
    db_path = tmp_path / "populated.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, PRE_U3_REVISION)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO frequencies "
            "(created_at, updated_at, label, mhz, mode, facility, category, "
            " description, is_active, tuner_group, verified) "
            "VALUES ('2026-01-01', '2026-01-01', 'Tower', 123.8, 'am', 'X', "
            "'tower', '', 1, 1, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO recordings "
            "(created_at, updated_at, freq_id, started_at_utc, ended_at_utc, "
            " duration_s, file_path, sample_rate, stage) "
            "VALUES ('2026-01-01', '2026-01-01', 1, '2026-01-01', '2026-01-01', "
            "6.0, 'a.mp3', 8000, 'classified')"
        )

    command.upgrade(cfg, "head")

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) >= EXPECTED_TABLES
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM recordings").scalar() == 1


def test_migrated_schema_matches_models(tmp_path):
    import skywatch.db.models  # noqa: F401  (register tables on the shared metadata)

    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        # The FTS index is deliberately not an ORM table, so it is excluded
        # from the drift check the same way env.py excludes it.
        ctx = MigrationContext.configure(conn, opts={"include_name": include_name})
        diff = compare_metadata(ctx, SQLModel.metadata)
    assert diff == []


def test_fts_index_built_from_empty_database(tmp_path):
    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        available = fts.fts5_available(conn)
    if not available:  # pragma: no cover - CI SQLite has FTS5
        return
    assert fts.search_available(engine)


def test_fts_index_backfills_and_syncs_on_populated_database(tmp_path):
    """The index backfills existing transcripts and its triggers keep it current."""
    db_path = tmp_path / "populated.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, PRE_U3_REVISION)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        if not fts.fts5_available(conn):  # pragma: no cover - CI SQLite has FTS5
            return
        conn.exec_driver_sql(
            "INSERT INTO frequencies "
            "(created_at, updated_at, label, mhz, mode, facility, category, "
            " description, is_active, tuner_group, verified) "
            "VALUES ('2026-01-01', '2026-01-01', 'Tower', 123.8, 'am', 'X', "
            "'tower', '', 1, 1, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO recordings "
            "(created_at, updated_at, freq_id, started_at_utc, ended_at_utc, "
            " duration_s, file_path, sample_rate, stage) "
            "VALUES ('2026-01-01', '2026-01-01', 1, '2026-01-01', '2026-01-01', "
            "6.0, 'a.mp3', 8000, 'classified')"
        )
        conn.exec_driver_sql(
            "INSERT INTO transcripts "
            "(created_at, updated_at, recording_id, engine, model, text) "
            "VALUES ('2026-01-01', '2026-01-01', 1, 'faster_whisper', 'base.en', "
            "'Mayday Speedbird declaring emergency')"
        )

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        # Backfill picked up the transcript that existed before the index.
        hit = conn.exec_driver_sql(
            "SELECT rowid FROM transcripts_fts WHERE transcripts_fts MATCH 'mayday'"
        ).fetchall()
        assert [row[0] for row in hit] == [1]

    # An insert after the migration is indexed by the AFTER INSERT trigger.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO transcripts "
            "(created_at, updated_at, recording_id, engine, model, text) "
            "VALUES ('2026-01-02', '2026-01-02', 1, 'faster_whisper', 'base.en', "
            "'Stansted Tower good morning')"
        )
    with engine.connect() as conn:
        hit = conn.exec_driver_sql(
            "SELECT rowid FROM transcripts_fts WHERE transcripts_fts MATCH 'stansted'"
        ).fetchall()
        assert [row[0] for row in hit] == [2]


def test_u6a_migrations_apply_on_populated_database(tmp_path):
    """The starred_at column and incident tables apply on top of existing rows."""
    db_path = tmp_path / "populated.db"
    cfg = _alembic_config(db_path)
    command.upgrade(cfg, PRE_U6A_REVISION)

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO frequencies "
            "(created_at, updated_at, label, mhz, mode, facility, category, "
            " description, is_active, tuner_group, verified) "
            "VALUES ('2026-01-01', '2026-01-01', 'Tower', 123.8, 'am', 'X', "
            "'tower', '', 1, 1, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO recordings "
            "(created_at, updated_at, freq_id, started_at_utc, ended_at_utc, "
            " duration_s, file_path, sample_rate, stage) "
            "VALUES ('2026-01-01', '2026-01-01', 1, '2026-01-01', '2026-01-01', "
            "6.0, 'a.mp3', 8000, 'classified')"
        )

    command.upgrade(cfg, "head")

    inspector = inspect(engine)
    assert set(inspector.get_table_names()) >= EXPECTED_TABLES
    with engine.connect() as conn:
        # The existing row survives, and the new column defaults to null.
        row = conn.exec_driver_sql("SELECT starred_at FROM recordings WHERE id = 1").fetchone()
        assert row[0] is None

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO incidents (created_at, updated_at, title) "
            "VALUES ('2026-01-02', '2026-01-02', 'Go-around sequence')"
        )
        conn.exec_driver_sql(
            "INSERT INTO incident_clips "
            "(created_at, updated_at, incident_id, recording_id, position) "
            "VALUES ('2026-01-02', '2026-01-02', 1, 1, 0)"
        )
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM incident_clips").scalar() == 1
