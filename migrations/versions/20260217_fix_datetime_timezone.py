"""Fix datetime columns to use timezone-aware timestamps.

asyncpg rejects mixing offset-naive and offset-aware datetimes,
causing 500s on webhook ingestion.

Revision ID: ad_0002
Revises: ad_0001
Create Date: 2026-02-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad_0002"
down_revision: Union[str, None] = "ad_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "workflow_runs", "run_started_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )
    op.alter_column(
        "workflow_runs", "run_completed_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )
    op.alter_column(
        "workflow_jobs", "started_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )
    op.alter_column(
        "workflow_jobs", "completed_at",
        type_=sa.DateTime(timezone=True),
        existing_type=sa.DateTime(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "workflow_jobs", "completed_at",
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "workflow_jobs", "started_at",
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "workflow_runs", "run_completed_at",
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
    op.alter_column(
        "workflow_runs", "run_started_at",
        type_=sa.DateTime(),
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=True,
    )
