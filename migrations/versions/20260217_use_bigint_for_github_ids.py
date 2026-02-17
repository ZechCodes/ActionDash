"""Use BigInteger for GitHub ID columns.

GitHub run_id values now exceed PostgreSQL's 4-byte integer max
(2,147,483,647), causing 500 errors on webhook ingestion.

Revision ID: ad_0003
Revises: ad_0002
Create Date: 2026-02-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad_0003"
down_revision: Union[str, None] = "ad_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "workflow_runs", "run_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "workflow_runs", "workflow_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "workflow_jobs", "job_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "workflow_jobs", "run_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "monitored_repos", "repo_github_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
    )
    op.alter_column(
        "monitored_repos", "webhook_id",
        type_=sa.BigInteger(),
        existing_type=sa.Integer(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "monitored_repos", "webhook_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
        existing_nullable=True,
    )
    op.alter_column(
        "monitored_repos", "repo_github_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
    )
    op.alter_column(
        "workflow_jobs", "run_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
    )
    op.alter_column(
        "workflow_jobs", "job_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
    )
    op.alter_column(
        "workflow_runs", "workflow_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
    )
    op.alter_column(
        "workflow_runs", "run_id",
        type_=sa.Integer(),
        existing_type=sa.BigInteger(),
    )
