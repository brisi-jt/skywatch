"""SQLite engine and session helpers.

The station database is shared by the capture watcher, the pipeline worker,
and the API server, so every connection runs in WAL mode with foreign keys
enforced and a busy timeout to ride out concurrent writers.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, event
from sqlalchemy.pool import ConnectionPoolEntry
from sqlmodel import Session, create_engine

DB_FILENAME = "station.db"


def default_db_path(data_root: Path) -> Path:
    return data_root / DB_FILENAME


def sqlite_url(db_path: Path | str) -> str:
    return f"sqlite:///{db_path}"


def create_db_engine(db_path: Path | str, *, echo: bool = False) -> Engine:
    """Engine for the station database, creating the parent directory if needed."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(sqlite_url(path), echo=echo)

    @event.listens_for(engine, "connect")
    def _configure_connection(dbapi_connection, _record: ConnectionPoolEntry) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Session that commits on success and rolls back on any exception."""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
