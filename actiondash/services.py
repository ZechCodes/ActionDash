"""Data access layer for workflow runs and jobs."""

from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from actiondash.models import WorkflowRun, WorkflowJob


def _parse_gh_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    # GitHub sends ISO 8601 format: "2024-01-15T10:30:00Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def upsert_workflow_run(session: AsyncSession, payload: dict) -> WorkflowRun:
    """Create or update a workflow run from a webhook payload."""
    workflow_run = payload["workflow_run"]
    run_id = workflow_run["id"]

    result = await session.execute(
        select(WorkflowRun).where(WorkflowRun.run_id == run_id)
    )
    run = result.scalar_one_or_none()

    if run is None:
        run = WorkflowRun(run_id=run_id)
        session.add(run)

    run.repo_full_name = payload["repository"]["full_name"]
    run.workflow_name = workflow_run.get("name", "Unknown")
    run.workflow_id = workflow_run.get("workflow_id", 0)
    run.head_branch = workflow_run.get("head_branch")
    run.head_sha = workflow_run.get("head_sha")
    run.status = workflow_run.get("status", "unknown")
    run.conclusion = workflow_run.get("conclusion")
    run.event = workflow_run.get("event", "unknown")
    run.run_number = workflow_run.get("run_number", 0)
    run.run_attempt = workflow_run.get("run_attempt", 1)
    run.html_url = workflow_run.get("html_url", "")

    actor = workflow_run.get("actor") or workflow_run.get("triggering_actor")
    if actor:
        run.actor_login = actor.get("login")
        run.actor_avatar_url = actor.get("avatar_url")

    run.run_started_at = _parse_gh_datetime(workflow_run.get("run_started_at"))

    if workflow_run.get("status") == "completed":
        run.run_completed_at = _parse_gh_datetime(
            workflow_run.get("updated_at")
        )

    await session.flush()
    return run


async def upsert_workflow_job(session: AsyncSession, payload: dict) -> WorkflowJob:
    """Create or update a workflow job from a webhook payload."""
    wf_job = payload["workflow_job"]
    job_id = wf_job["id"]

    result = await session.execute(
        select(WorkflowJob).where(WorkflowJob.job_id == job_id)
    )
    job = result.scalar_one_or_none()

    if job is None:
        job = WorkflowJob(job_id=job_id)
        session.add(job)

    job.run_id = wf_job.get("run_id", 0)
    job.repo_full_name = payload["repository"]["full_name"]
    job.workflow_name = wf_job.get("workflow_name")
    job.name = wf_job.get("name", "Unknown")
    job.status = wf_job.get("status", "unknown")
    job.conclusion = wf_job.get("conclusion")
    job.html_url = wf_job.get("html_url", "")
    job.runner_name = wf_job.get("runner_name")
    job.started_at = _parse_gh_datetime(wf_job.get("started_at"))
    job.completed_at = _parse_gh_datetime(wf_job.get("completed_at"))

    await session.flush()
    return job


async def get_recent_runs(
    session: AsyncSession,
    *,
    limit: int = 50,
    repo_full_name: str | None = None,
) -> list[WorkflowRun]:
    """Get the most recent completed workflow runs, optionally filtered by repo."""
    query = (
        select(WorkflowRun)
        .where(WorkflowRun.status == "completed")
        .order_by(desc(WorkflowRun.updated_at))
        .limit(limit)
    )
    if repo_full_name:
        query = query.where(WorkflowRun.repo_full_name == repo_full_name)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_active_runs(
    session: AsyncSession,
    *,
    repo_full_name: str | None = None,
) -> list[WorkflowRun]:
    """Get currently active (non-completed) workflow runs, optionally filtered by repo."""
    query = (
        select(WorkflowRun)
        .where(WorkflowRun.status.in_(["requested", "in_progress", "queued"]))
        .order_by(desc(WorkflowRun.updated_at))
    )
    if repo_full_name:
        query = query.where(WorkflowRun.repo_full_name == repo_full_name)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_jobs_for_run(
    session: AsyncSession, run_id: int
) -> list[WorkflowJob]:
    """Get all jobs belonging to a workflow run."""
    result = await session.execute(
        select(WorkflowJob)
        .where(WorkflowJob.run_id == run_id)
        .order_by(WorkflowJob.created_at)
    )
    return list(result.scalars().all())


async def get_run_stats(
    session: AsyncSession,
    *,
    repo_full_name: str | None = None,
) -> dict:
    """Get summary statistics for the dashboard, optionally filtered by repo."""
    active = await get_active_runs(session, repo_full_name=repo_full_name)
    recent = await get_recent_runs(session, limit=100, repo_full_name=repo_full_name)

    completed = [r for r in recent if r.status == "completed"]
    succeeded = [r for r in completed if r.conclusion == "success"]
    failed = [r for r in completed if r.conclusion == "failure"]

    return {
        "active_count": len(active),
        "recent_count": len(recent),
        "success_count": len(succeeded),
        "failure_count": len(failed),
        "success_rate": (
            round(len(succeeded) / len(completed) * 100) if completed else 0
        ),
    }
