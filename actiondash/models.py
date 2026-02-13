"""Database models for GitHub Actions workflow tracking."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import String, Text, DateTime, Integer, Index
from sqlalchemy.orm import Mapped, mapped_column

from skrift.db.base import Base


class WorkflowStatus(StrEnum):
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    QUEUED = "queued"


class WorkflowConclusion(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    STALE = "stale"
    NEUTRAL = "neutral"


class WorkflowRun(Base):
    """Tracks a GitHub Actions workflow run."""

    __tablename__ = "workflow_runs"

    run_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    workflow_name: Mapped[str] = mapped_column(String(255))
    workflow_id: Mapped[int] = mapped_column(Integer)
    head_branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    conclusion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    event: Mapped[str] = mapped_column(String(50))
    run_number: Mapped[int] = mapped_column(Integer)
    run_attempt: Mapped[int] = mapped_column(Integer, default=1)
    html_url: Mapped[str] = mapped_column(Text)
    actor_login: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_workflow_runs_repo_status", "repo_full_name", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "run_id": self.run_id,
            "repo_full_name": self.repo_full_name,
            "repo_name": self.repo_full_name.split("/")[-1] if self.repo_full_name else "",
            "workflow_name": self.workflow_name,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha[:7] if self.head_sha else None,
            "status": self.status,
            "conclusion": self.conclusion,
            "event": self.event,
            "run_number": self.run_number,
            "run_attempt": self.run_attempt,
            "html_url": self.html_url,
            "actor_login": self.actor_login,
            "actor_avatar_url": self.actor_avatar_url,
            "run_started_at": self.run_started_at.isoformat() if self.run_started_at else None,
            "run_completed_at": self.run_completed_at.isoformat() if self.run_completed_at else None,
        }


class WorkflowJob(Base):
    """Tracks individual jobs within a workflow run."""

    __tablename__ = "workflow_jobs"

    job_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    workflow_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), index=True)
    conclusion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    html_url: Mapped[str] = mapped_column(Text)
    runner_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_workflow_jobs_run_id_status", "run_id", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "job_id": self.job_id,
            "run_id": self.run_id,
            "repo_full_name": self.repo_full_name,
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "html_url": self.html_url,
            "runner_name": self.runner_name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
