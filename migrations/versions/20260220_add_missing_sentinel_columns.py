"""Add missing sa_orm_sentinel columns to Skrift tables.

Skrift's stored_notifications and user_roles migrations omit the
sa_orm_sentinel column that the ORM models expect. This backfills it.

Revision ID: ad_0005
Revises: ad_0004
Create Date: 2026-02-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad_0005"
down_revision: Union[str, None] = "ad_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    for table in ("stored_notifications", "user_roles"):
        has_col = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = 'sa_orm_sentinel'"
            ),
            {"t": table},
        ).fetchone()
        if not has_col:
            op.add_column(table, sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_roles", "sa_orm_sentinel")
    op.drop_column("stored_notifications", "sa_orm_sentinel")
