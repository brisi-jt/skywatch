"""heartbeats

Revision ID: b644ab50ae6d
Revises: 7be5d2bb0b1e
Create Date: 2026-09-03 18:50:35.753622

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b644ab50ae6d"
down_revision: str | None = "7be5d2bb0b1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "heartbeats",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("capture_running", sa.Boolean(), nullable=False),
        sa.Column("queue_depths", sa.JSON(), nullable=False),
        sa.Column("disk_free_gb", sa.Float(), nullable=False),
        sa.Column("llm_remaining", sa.Integer(), nullable=True),
        sa.Column("opensky_remaining", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("heartbeats")
