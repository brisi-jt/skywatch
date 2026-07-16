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
    "classifications",
    "aircraft_matches",
    "feedback",
    "api_usage",
    "settings",
}


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


def test_migrated_schema_matches_models(tmp_path):
    import skywatch.db.models  # noqa: F401  (register tables on the shared metadata)

    db_path = tmp_path / "migrated.db"
    command.upgrade(_alembic_config(db_path), "head")

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, SQLModel.metadata)
    assert diff == []
