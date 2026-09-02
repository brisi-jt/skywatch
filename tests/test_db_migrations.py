from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

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
}

# The revision that shipped before the U3 additive migrations, used to prove
# they apply cleanly on top of a database that already holds rows.
PRE_U3_REVISION = "4f41a40b5f5d"


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
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, SQLModel.metadata)
    assert diff == []
