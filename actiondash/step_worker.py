"""Standalone step-progress worker process.

Polls GitHub for step-level detail on active workflow runs and publishes
updates via HTTP webhook to the main Skrift app for SSE fan-out.

Run with: uv run python -m actiondash.step_worker
"""

import asyncio
import logging
import os
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from skrift.config import get_settings
from skrift.db.base import Base
import skrift.db.models  # noqa: F401 — ensure all Skrift models are registered

from actiondash.github_client import GitHubClient
from actiondash.models import MonitoredRepo, WorkflowRun
from actiondash.services import complete_stale_run
from actiondash.step_poller import poll_loop

logger = logging.getLogger(__name__)

_last_poll_at: float = 0.0

WEBHOOK_URL = os.environ.get(
    "NOTIFICATION_WEBHOOK_URL", "http://localhost:8080/notifications/webhook/"
)
WEBHOOK_SECRET = os.environ.get("NOTIFICATION_WEBHOOK_SECRET", "")


async def _post_notification(
    client: httpx.AsyncClient,
    *,
    user_id: str,
    type: str,
    group: str | None = None,
    **payload,
) -> None:
    """POST a single notification to the Skrift webhook endpoint."""
    body = {
        "target": "user",
        "user_id": user_id,
        "type": type,
        "mode": "timeseries",
        "payload": payload,
    }
    if group is not None:
        body["group"] = group

    resp = await client.post(
        WEBHOOK_URL,
        json=body,
        headers={"Authorization": f"Bearer {WEBHOOK_SECRET}"},
    )
    if resp.status_code not in (200, 202):
        logger.warning(
            "Webhook returned %d for user %s type %s: %s",
            resp.status_code,
            user_id,
            type,
            resp.text,
        )


def _make_publish_fn(client: httpx.AsyncClient):
    """Create a publish callback that POSTs to the notification webhook."""

    async def publish(type: str, *, group: str | None = None, user_ids: list[str] | None = None, **payload) -> None:
        if not user_ids:
            logger.warning("No user_ids for %s notification, skipping", type)
            return
        for uid in user_ids:
            try:
                await _post_notification(client, user_id=uid, type=type, group=group, **payload)
            except Exception:
                logger.warning("Failed to notify user %s for %s", uid, type, exc_info=True)

    return publish


async def _get_all_user_ids(session_maker: async_sessionmaker) -> list[str]:
    """Query all distinct user IDs that have at least one monitored repo."""
    async with session_maker() as session:
        result = await session.execute(
            select(MonitoredRepo.user_id).distinct()
        )
        return [str(uid) for uid in result.scalars().all()]


async def _post_worker_event(
    client: httpx.AsyncClient,
    session_maker: async_sessionmaker,
    *,
    event: str,
    **data,
) -> None:
    """Send a worker_activity notification to all users with monitored repos."""
    user_ids = await _get_all_user_ids(session_maker)
    if not user_ids:
        return

    group = None

    for uid in user_ids:
        try:
            await _post_notification(
                client,
                user_id=uid,
                type="worker_activity",
                group=group,
                event=event,
                **data,
            )
        except Exception:
            logger.warning("Failed to send worker event %s to user %s", event, uid)


def _make_store_fn(session_maker: async_sessionmaker):
    """Create a store callback that persists step_summary to the DB."""

    async def store(run_id: int, summary: dict) -> None:
        async with session_maker() as session:
            result = await session.execute(
                select(WorkflowRun).where(WorkflowRun.run_id == run_id)
            )
            run = result.scalar_one_or_none()
            if run:
                run.step_summary = summary
                await session.commit()

    return store


def _make_completion_fn(
    session_maker: async_sessionmaker,
    client: httpx.AsyncClient,
    worker_event_fn=None,
):
    """Create a callback that recovers stuck runs detected by the poller."""

    async def complete(repo_full_name: str, run_id: int, user_ids: list[str]) -> None:
        from uuid import UUID
        from actiondash.repo_services import get_user_github_token

        async with session_maker() as session:
            # Find a token for this repo
            token = None
            for uid_str in user_ids:
                token = await get_user_github_token(session, UUID(uid_str))
                if token:
                    break

            if not token:
                logger.warning("Recovery: no token for repo %s, skipping run %d", repo_full_name, run_id)
                return

            # Confirm the run is actually completed on GitHub
            gh = GitHubClient(token)
            run_data = await gh.get_run(repo_full_name, run_id)

            if run_data.get("status") != "completed":
                logger.info("Recovery: run %d not yet completed on GitHub (status=%s)", run_id, run_data.get("status"))
                return

            # Finalize in DB
            run = await complete_stale_run(session, run_data)
            if run is None:
                logger.info("Recovery: run %d not in DB or already completed", run_id)
                return

            await session.commit()
            logger.info("Recovery: finalized run %d (conclusion=%s)", run_id, run.conclusion)

            # Notify frontend — same shape as the webhook handler
            for uid in user_ids:
                try:
                    await _post_notification(
                        client,
                        user_id=uid,
                        type="workflow_run",
                        group=f"run-{run.run_id}",
                        action="completed",
                        run=run.to_dict(),
                    )
                except Exception:
                    logger.warning("Recovery: failed to notify user %s for run %d", uid, run.run_id)

            # Emit worker admin event
            if worker_event_fn:
                try:
                    await worker_event_fn(
                        "recovery_completed",
                        run_id=run_id,
                        repo=repo_full_name,
                        conclusion=run.conclusion,
                    )
                except Exception:
                    pass

    return complete


async def _health_server() -> None:
    """Minimal HTTP health check on port 8081."""

    async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        except (asyncio.TimeoutError, ConnectionError):
            writer.close()
            return

        path = request_line.decode().split(" ")[1] if b" " in request_line else "/"

        if path == "/healthz":
            elapsed = time.monotonic() - _last_poll_at if _last_poll_at else float("inf")
            if elapsed <= 30.0:
                body = b'{"ok":true}'
                status = "200 OK"
            else:
                body = b'{"ok":false,"reason":"poll_stale"}'
                status = "503 Service Unavailable"
        else:
            body = b'{"error":"not_found"}'
            status = "404 Not Found"

        response = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body

        writer.write(response)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle_connection, "0.0.0.0", 8081)
    logger.info("Health check server listening on :8081")
    await server.serve_forever()


async def _run() -> None:
    settings = get_settings()

    engine_kwargs: dict = {"pool_size": 2, "max_overflow": 0}
    if settings.db.db_schema:
        Base.metadata.schema = settings.db.db_schema
        engine_kwargs["execution_options"] = {
            "schema_translate_map": {None: settings.db.db_schema},
        }

    engine = create_async_engine(settings.db.url, **engine_kwargs)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with httpx.AsyncClient(timeout=10.0) as client:
        logger.info("Step worker using notification webhook at %s", WEBHOOK_URL)

        async def worker_event_fn(event: str, **data) -> None:
            await _post_worker_event(client, session_maker, event=event, **data)

        publish_fn = _make_publish_fn(client)
        store_fn = _make_store_fn(session_maker)
        completion_fn = _make_completion_fn(session_maker, client, worker_event_fn=worker_event_fn)

        # Emit startup event
        try:
            await worker_event_fn("worker_started", webhook_url=WEBHOOK_URL)
        except Exception:
            logger.warning("Failed to emit worker_started event")

        # Mark as healthy immediately so the first poll cycle doesn't fail the probe
        global _last_poll_at
        _last_poll_at = time.monotonic()

        def _mark_alive():
            global _last_poll_at
            _last_poll_at = time.monotonic()

        health_task = asyncio.create_task(_health_server())

        try:
            await poll_loop(
                session_maker,
                publish_fn,
                on_cycle=_mark_alive,
                store_fn=store_fn,
                completion_fn=completion_fn,
                worker_event_fn=worker_event_fn,
            )
        finally:
            health_task.cancel()
            await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
