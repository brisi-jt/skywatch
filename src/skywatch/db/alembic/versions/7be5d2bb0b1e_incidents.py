"""incidents

Revision ID: 7be5d2bb0b1e
Revises: b34c4e7c0ea9
Create Date: 2026-09-03 15:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7be5d2bb0b1e"
down_revision: str | None = "b34c4e7c0ea9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "incident_clips",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "incident_id", "recording_id", name="uq_incident_clips_incident_recording"
        ),
    )
    with op.batch_alter_table("incident_clips", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_incident_clips_incident_id"), ["incident_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_incident_clips_recording_id"), ["recording_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("incident_clips", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_incident_clips_recording_id"))
        batch_op.drop_index(batch_op.f("ix_incident_clips_incident_id"))
    op.drop_table("incident_clips")
    op.drop_table("incidents")
