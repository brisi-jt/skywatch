"""aircraft match enrichment columns

Revision ID: cca66a1591b9
Revises: 91972aa3a105
Create Date: 2026-09-02 18:48:21.505972

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cca66a1591b9"
down_revision: str | None = "91972aa3a105"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("aircraft_matches", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("alert_category", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("registration", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("aircraft_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("operator_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("aircraft_matches", schema=None) as batch_op:
        batch_op.drop_column("operator_name")
        batch_op.drop_column("aircraft_type")
        batch_op.drop_column("registration")
        batch_op.drop_column("alert_category")
