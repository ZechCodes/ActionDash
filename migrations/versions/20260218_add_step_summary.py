"""Add step_summary JSON column to workflow_runs.

Persists the last known step progress so active runs show it immediately
on page reload and failed runs retain visibility of where they broke.

Revision ID: ad_0004
Revises: ad_0003
Create Date: 2026-02-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad_0004"
down_revision: Union[str, None] = "ad_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("step_summary", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "step_summary")
