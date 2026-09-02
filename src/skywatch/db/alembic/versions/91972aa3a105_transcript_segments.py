"""transcript segments

Revision ID: 91972aa3a105
Revises: 4f41a40b5f5d
Create Date: 2026-09-02 18:31:32.209204

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "91972aa3a105"
down_revision: str | None = "4f41a40b5f5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transcript_segments",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transcript_id", sa.Integer(), nullable=False),
        sa.Column("start_s", sa.Float(), nullable=False),
        sa.Column("end_s", sa.Float(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("avg_word_prob", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("transcript_segments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_transcript_segments_transcript_id"), ["transcript_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("transcript_segments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_transcript_segments_transcript_id"))

    op.drop_table("transcript_segments")
