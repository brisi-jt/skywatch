"""recording starred_at

Revision ID: b34c4e7c0ea9
Revises: d3f8a1c2b4e6
Create Date: 2026-09-03 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b34c4e7c0ea9"
down_revision: str | None = "d3f8a1c2b4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recordings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("starred_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recordings", schema=None) as batch_op:
        batch_op.drop_column("starred_at")
