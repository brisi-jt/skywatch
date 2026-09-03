"""Full-text search over transcripts, built on SQLite's FTS5 extension.

The station keeps an external-content FTS5 index over ``transcripts.text``
so the clip library can be searched by what was said. FTS5 is optional: the
migration only builds the index when the running SQLite has the extension
compiled in, and search falls back to a plain ``LIKE`` scan when it does not.

The index name and everything derived from it share the ``transcripts_fts``
prefix (FTS5 creates several shadow tables alongside the virtual table). That
prefix is what :func:`is_fts_table` matches, so the schema-drift check can
ignore these deliberately-not-in-the-ORM objects.
"""

from sqlalchemy import Connection
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

FTS_TABLE = "transcripts_fts"

_CREATE_TABLE = (
    f"CREATE VIRTUAL TABLE {FTS_TABLE} USING fts5(text, content='transcripts', content_rowid='id')"
)

# Keep the index in step with the transcripts table. External-content tables
# are told about deletes/updates with the special 'delete' command carrying
# the old row so the index does not keep stale terms.
_CREATE_TRIGGERS = (
    f"CREATE TRIGGER {FTS_TABLE}_ai AFTER INSERT ON transcripts BEGIN "
    f"INSERT INTO {FTS_TABLE}(rowid, text) VALUES (new.id, new.text); END",
    f"CREATE TRIGGER {FTS_TABLE}_ad AFTER DELETE ON transcripts BEGIN "
    f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, text) "
    "VALUES ('delete', old.id, old.text); END",
    f"CREATE TRIGGER {FTS_TABLE}_au AFTER UPDATE ON transcripts BEGIN "
    f"INSERT INTO {FTS_TABLE}({FTS_TABLE}, rowid, text) "
    "VALUES ('delete', old.id, old.text); "
    f"INSERT INTO {FTS_TABLE}(rowid, text) VALUES (new.id, new.text); END",
)

_BACKFILL = f"INSERT INTO {FTS_TABLE}(rowid, text) SELECT id, text FROM transcripts"

_DROP_TRIGGERS = (
    f"DROP TRIGGER IF EXISTS {FTS_TABLE}_au",
    f"DROP TRIGGER IF EXISTS {FTS_TABLE}_ad",
    f"DROP TRIGGER IF EXISTS {FTS_TABLE}_ai",
)


def is_fts_table(name: str | None) -> bool:
    """Whether a table name belongs to the FTS index (or one of its shadows)."""
    return name is not None and name.startswith(FTS_TABLE)


def include_name(name: str | None, type_: str, parent_names: dict) -> bool:
    """Alembic autogenerate filter: keep the hand-built FTS index out of the diff."""
    if type_ == "table":
        return not is_fts_table(name)
    return True


def fts5_available(connection: Connection) -> bool:
    """Whether the connected SQLite has the FTS5 extension compiled in."""
    try:
        connection.exec_driver_sql("CREATE VIRTUAL TABLE temp.__skywatch_fts5_probe USING fts5(x)")
    except OperationalError:
        return False
    connection.exec_driver_sql("DROP TABLE temp.__skywatch_fts5_probe")
    return True


def create_index(connection: Connection) -> None:
    """Create the virtual table, its sync triggers, and backfill from existing rows."""
    connection.exec_driver_sql(_CREATE_TABLE)
    for statement in _CREATE_TRIGGERS:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(_BACKFILL)


def drop_index(connection: Connection) -> None:
    """Remove the sync triggers and the virtual table."""
    for statement in _DROP_TRIGGERS:
        connection.exec_driver_sql(statement)
    connection.exec_driver_sql(f"DROP TABLE IF EXISTS {FTS_TABLE}")


def search_available(engine: Engine) -> bool:
    """Whether transcript search can use FTS5 on this database.

    True only when the extension is present *and* the index table exists (the
    migration skips building it on a SQLite without FTS5). Any other case
    means the ``LIKE`` fallback is in force.
    """
    with engine.connect() as connection:
        if not fts5_available(connection):
            return False
        row = connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (FTS_TABLE,),
        ).first()
        return row is not None
