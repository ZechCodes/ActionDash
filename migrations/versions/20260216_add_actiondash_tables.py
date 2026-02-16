"""Add ActionDash tables: workflow_runs, workflow_jobs, monitored_repos, user_settings.

Revision ID: ad_0001
Revises: None (independent branch)
Create Date: 2026-02-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = ("actiondash",)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("workflow_name", sa.String(255), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("head_branch", sa.String(255), nullable=True),
        sa.Column("head_sha", sa.String(40), nullable=True),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("conclusion", sa.String(50), nullable=True),
        sa.Column("event", sa.String(50), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("run_attempt", sa.Integer(), nullable=False),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("actor_login", sa.String(255), nullable=True),
        sa.Column("actor_avatar_url", sa.Text(), nullable=True),
        sa.Column("run_started_at", sa.DateTime(), nullable=True),
        sa.Column("run_completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
        if_not_exists=True,
    )
    op.create_index("ix_workflow_runs_run_id", "workflow_runs", ["run_id"], if_not_exists=True)
    op.create_index("ix_workflow_runs_repo_full_name", "workflow_runs", ["repo_full_name"], if_not_exists=True)
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"], if_not_exists=True)
    op.create_index("ix_workflow_runs_repo_status", "workflow_runs", ["repo_full_name", "status"], if_not_exists=True)

    op.create_table(
        "workflow_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("workflow_name", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("conclusion", sa.String(50), nullable=True),
        sa.Column("html_url", sa.Text(), nullable=False),
        sa.Column("runner_name", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        if_not_exists=True,
    )
    op.create_index("ix_workflow_jobs_job_id", "workflow_jobs", ["job_id"], if_not_exists=True)
    op.create_index("ix_workflow_jobs_run_id", "workflow_jobs", ["run_id"], if_not_exists=True)
    op.create_index("ix_workflow_jobs_repo_full_name", "workflow_jobs", ["repo_full_name"], if_not_exists=True)
    op.create_index("ix_workflow_jobs_status", "workflow_jobs", ["status"], if_not_exists=True)
    op.create_index("ix_workflow_jobs_run_id_status", "workflow_jobs", ["run_id", "status"], if_not_exists=True)

    op.create_table(
        "monitored_repos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("repo_github_id", sa.Integer(), nullable=False),
        sa.Column("webhook_id", sa.Integer(), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_branch", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "repo_full_name", name="uq_user_repo"),
        if_not_exists=True,
    )

    op.create_table(
        "user_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sa_orm_sentinel", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("auto_monitor_new_repos", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_table("monitored_repos")
    op.drop_table("workflow_jobs")
    op.drop_table("workflow_runs")
