"""Background poller for GitHub Actions step progress on active runs.

Polls the GitHub API every 5 seconds for step-level detail on in-progress
runs, then broadcasts changes via SSE to all connected dashboard clients.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from skrift.config import get_settings
from skrift.lib.notifications import notify_broadcast

from actiondash.github_client import GitHubClient
from actiondash.models import MonitoredRepo
from actiondash.services import get_active_runs

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds
_HEARTBEAT_EVERY = 12  # log heartbeat every 12 cycles (~60s)

_poll_task: asyncio.Task | None = None
_step_cache: dict[int, dict] = {}  # run_id -> last step summary


def get_step_cache() -> dict[int, dict]:
    """Read-only accessor for the step cache (run_id -> job summary dict)."""
    return _step_cache


def _extract_current_step(steps: list[dict]) -> str | None:
    """Return the name of the first in_progress step, or the last completed step."""
    for step in steps:
        if step.get("status") == "in_progress":
            return step.get("name")
    # Fall back to last completed step
    for step in reversed(steps):
        if step.get("status") == "completed":
            return step.get("name")
    return None


def _build_step_summary(jobs: list[dict]) -> dict:
    """Build a per-job step summary dict from the GitHub API response."""
    summary = {}
    for job in jobs:
        steps = job.get("steps") or []
        completed = sum(1 for s in steps if s.get("status") == "completed")
        current_step = _extract_current_step(steps)
        summary[job["id"]] = {
            "name": job.get("name", "Unknown"),
            "status": job.get("status", "unknown"),
            "current_step": current_step,
            "total_steps": len(steps),
            "completed_steps": completed,
        }
    return summary


async def _get_token_for_repo(
    session: AsyncSession, repo_full_name: str
) -> str | None:
    """Look up a GitHub token for a monitored repo via its owner."""
    from actiondash.repo_services import get_user_github_token

    result = await session.execute(
        select(MonitoredRepo.user_id).where(
            MonitoredRepo.repo_full_name == repo_full_name
        ).limit(1)
    )
    user_id = result.scalar_one_or_none()
    if not user_id:
        return None
    return await get_user_github_token(session, user_id)


async def _poll_once(session_maker: async_sessionmaker) -> dict:
    """Execute a single poll cycle. Returns stats dict for heartbeat."""
    stats = {"active": 0, "polled": 0, "broadcast": 0, "skipped_no_token": 0, "errors": 0}
    async with session_maker() as session:
        active_runs = await get_active_runs(session)
        if not active_runs:
            # Prune entire cache when no active runs
            _step_cache.clear()
            return stats

        stats["active"] = len(active_runs)
        logger.debug("Step poller: %d active run(s)", len(active_runs))

        # Group runs by repo for token lookup
        repo_tokens: dict[str, str | None] = {}
        for run in active_runs:
            if run.repo_full_name not in repo_tokens:
                repo_tokens[run.repo_full_name] = await _get_token_for_repo(
                    session, run.repo_full_name
                )

        # Poll each active run
        active_run_ids = set()
        for run in active_runs:
            active_run_ids.add(run.run_id)
            token = repo_tokens.get(run.repo_full_name)
            if not token:
                logger.warning(
                    "Step poller: no token for repo %s, skipping run %d",
                    run.repo_full_name, run.run_id,
                )
                stats["skipped_no_token"] += 1
                continue

            try:
                client = GitHubClient(token)
                jobs = await client.get_run_jobs(run.repo_full_name, run.run_id)
            except Exception:
                logger.warning(
                    "Step poller: failed to fetch jobs for %s run %d",
                    run.repo_full_name, run.run_id,
                    exc_info=True,
                )
                stats["errors"] += 1
                continue

            stats["polled"] += 1
            summary = _build_step_summary(jobs)
            prev = _step_cache.get(run.run_id)

            if summary != prev:
                _step_cache[run.run_id] = summary
                await notify_broadcast(
                    "step_progress",
                    group=f"steps-{run.run_id}",
                    run_id=run.run_id,
                    repo_full_name=run.repo_full_name,
                    jobs=summary,
                )
                stats["broadcast"] += 1
                logger.info(
                    "Step poller: broadcast step_progress for run %d (%d job(s))",
                    run.run_id, len(summary),
                )

        # Prune cache entries for runs no longer active
        stale = set(_step_cache) - active_run_ids
        for run_id in stale:
            del _step_cache[run_id]

    return stats


async def _poll_loop(session_maker: async_sessionmaker) -> None:
    """Infinite polling loop with error recovery."""
    logger.info("Step progress poller started (interval=%ds)", POLL_INTERVAL)
    cycle = 0
    while True:
        try:
            stats = await _poll_once(session_maker)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Step poller error, will retry", exc_info=True)
            stats = None

        cycle += 1
        if cycle % _HEARTBEAT_EVERY == 0:
            cached = len(_step_cache)
            logger.info(
                "Step poller heartbeat: cycle=%d, cached_runs=%d, last=%s",
                cycle, cached, stats,
            )

        await asyncio.sleep(POLL_INTERVAL)


async def start_step_poller(app) -> None:
    """on_startup hook — start the background polling task."""
    global _poll_task

    settings = get_settings()
    engine = create_async_engine(settings.db.url, pool_size=2, max_overflow=0)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    _poll_task = asyncio.create_task(_poll_loop(session_maker))


async def stop_step_poller(app) -> None:
    """on_shutdown hook — cancel the polling task."""
    global _poll_task

    if _poll_task is not None:
        _poll_task.cancel()
        try:
            await _poll_task
        except asyncio.CancelledError:
            pass
        _poll_task = None

    logger.info("Step progress poller stopped")
