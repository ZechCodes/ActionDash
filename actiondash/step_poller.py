"""Background poller for GitHub Actions step progress on active runs.

Polls the GitHub API every 5 seconds for step-level detail on in-progress
runs, then broadcasts changes via a caller-supplied publish callback.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from actiondash.github_client import GitHubClient
from actiondash.models import MonitoredRepo
from actiondash.services import get_active_runs

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds
_HEARTBEAT_EVERY = 12  # log heartbeat every 12 cycles (~60s)

# Type aliases for callbacks
PublishFn = Callable[..., Coroutine[Any, Any, None]]
StoreFn = Callable[[int, dict], Coroutine[Any, Any, None]]
CompletionFn = Callable[[str, int, list[str]], Coroutine[Any, Any, None]]
# (repo_full_name, run_id, user_ids) -> None
WorkerEventFn = Callable[..., Coroutine[Any, Any, None]]
# (event, **data) -> None

_step_cache: dict[int, dict] = {}  # run_id -> last step summary
_completion_fired: dict[int, dict] = {}  # run_id -> summary at time of last fire


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
            "conclusion": job.get("conclusion"),
            "current_step": current_step,
            "total_steps": len(steps),
            "completed_steps": completed,
        }
    return summary


def _all_jobs_completed(summary: dict) -> bool:
    """Return True if every job in the summary has status 'completed'."""
    if not summary:
        return False
    return all(job["status"] == "completed" for job in summary.values())


async def _get_repo_context(
    session: AsyncSession, repo_full_name: str
) -> tuple[str | None, list[str]]:
    """Look up a GitHub token and monitoring user IDs for a repo.

    Returns (token, user_ids) where token comes from the first user with one.
    """
    from actiondash.repo_services import get_user_github_token

    result = await session.execute(
        select(MonitoredRepo.user_id).where(
            MonitoredRepo.repo_full_name == repo_full_name
        )
    )
    all_user_ids = result.scalars().all()
    if not all_user_ids:
        return None, []

    token = None
    for uid in all_user_ids:
        token = await get_user_github_token(session, uid)
        if token:
            break

    return token, [str(uid) for uid in all_user_ids]


async def _poll_once(session_maker: async_sessionmaker, publish_fn: PublishFn, store_fn: StoreFn | None = None, completion_fn: CompletionFn | None = None) -> dict:
    """Execute a single poll cycle. Returns stats dict for heartbeat."""
    stats = {"active": 0, "polled": 0, "broadcast": 0, "skipped_no_token": 0, "errors": 0}
    async with session_maker() as session:
        active_runs = await get_active_runs(session)
        if not active_runs:
            _step_cache.clear()
            return stats

        stats["active"] = len(active_runs)
        logger.debug("Step poller: %d active run(s)", len(active_runs))

        # Group runs by repo for token + user_id lookup
        repo_context: dict[str, tuple[str | None, list[str]]] = {}
        for run in active_runs:
            if run.repo_full_name not in repo_context:
                repo_context[run.repo_full_name] = await _get_repo_context(
                    session, run.repo_full_name
                )

        # Poll each active run
        active_run_ids = set()
        for run in active_runs:
            active_run_ids.add(run.run_id)
            token, user_ids = repo_context.get(run.repo_full_name, (None, []))
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
                if store_fn:
                    try:
                        await store_fn(run.run_id, summary)
                    except Exception:
                        logger.warning(
                            "Step poller: failed to store step_summary for run %d",
                            run.run_id, exc_info=True,
                        )
                try:
                    await publish_fn(
                        "step_progress",
                        group=f"steps-{run.run_id}",
                        run_id=run.run_id,
                        repo_full_name=run.repo_full_name,
                        jobs=summary,
                        user_ids=user_ids,
                    )
                except Exception:
                    logger.warning(
                        "Step poller: failed to publish for run %d",
                        run.run_id, exc_info=True,
                    )
                    stats["errors"] += 1
                    continue
                stats["broadcast"] += 1
                logger.info(
                    "Step poller: broadcast step_progress for run %d (%d job(s))",
                    run.run_id, len(summary),
                )

            # Detect stuck runs where all jobs are completed
            if (
                completion_fn
                and _all_jobs_completed(summary)
                and _completion_fired.get(run.run_id) != summary
            ):
                logger.info(
                    "Step poller: all jobs completed for run %d, triggering recovery",
                    run.run_id,
                )
                _completion_fired[run.run_id] = summary
                try:
                    await completion_fn(run.repo_full_name, run.run_id, user_ids)
                except Exception:
                    logger.warning(
                        "Step poller: recovery callback failed for run %d, will retry",
                        run.run_id, exc_info=True,
                    )
                    del _completion_fired[run.run_id]

        # Prune cache entries for runs no longer active, persisting final snapshot
        stale = set(_step_cache) - active_run_ids
        for run_id in stale:
            if store_fn:
                try:
                    await store_fn(run_id, _step_cache[run_id])
                except Exception:
                    logger.warning(
                        "Step poller: failed to store final snapshot for run %d",
                        run_id, exc_info=True,
                    )
            del _step_cache[run_id]

        # Also clean up completion tracking for stale runs
        stale_completions = set(_completion_fired) - active_run_ids
        for run_id in stale_completions:
            del _completion_fired[run_id]

    return stats


async def poll_loop(
    session_maker: async_sessionmaker,
    publish_fn: PublishFn,
    on_cycle: Callable[[], None] | None = None,
    store_fn: StoreFn | None = None,
    completion_fn: CompletionFn | None = None,
    worker_event_fn: WorkerEventFn | None = None,
) -> None:
    """Infinite polling loop with error recovery."""
    logger.info("Step progress poller started (interval=%ds)", POLL_INTERVAL)
    cycle = 0
    while True:
        try:
            stats = await _poll_once(session_maker, publish_fn, store_fn=store_fn, completion_fn=completion_fn)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Step poller error, will retry", exc_info=True)
            stats = None
            if worker_event_fn:
                try:
                    await worker_event_fn("poll_error", message="Unhandled poll loop error, will retry")
                except Exception:
                    pass

        if on_cycle is not None:
            on_cycle()

        cycle += 1
        if cycle % _HEARTBEAT_EVERY == 0:
            cached = len(_step_cache)
            logger.info(
                "Step poller heartbeat: cycle=%d, cached_runs=%d, last=%s",
                cycle, cached, stats,
            )
            if worker_event_fn:
                try:
                    await worker_event_fn(
                        "poll_heartbeat",
                        cycle=cycle,
                        cached_runs=cached,
                        stats=stats or {},
                    )
                except Exception:
                    pass

        await asyncio.sleep(POLL_INTERVAL)
