from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel

from skywatch.db.engine import create_db_engine

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def engine(tmp_path):
    import skywatch.db.models  # noqa: F401  (register tables on the shared metadata)

    eng = create_db_engine(tmp_path / "station.db")
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s
