"""transcript full-text search index

Revision ID: d3f8a1c2b4e6
Revises: cca66a1591b9
Create Date: 2026-09-03 09:10:00.000000

"""

from collections.abc import Sequence

from alembic import op

from skywatch.db import fts

# revision identifiers, used by Alembic.
revision: str = "d3f8a1c2b4e6"
down_revision: str | None = "cca66a1591b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if not fts.fts5_available(connection):
        # This SQLite build has no FTS5; transcript search runs the LIKE
        # fallback and never touches an index. The upgrade is a no-op so the
        # station still migrates cleanly.
        return
    fts.create_index(connection)


def downgrade() -> None:
    connection = op.get_bind()
    fts.drop_index(connection)
