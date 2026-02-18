"""Standalone step-progress worker process.

Polls GitHub for step-level detail on active workflow runs and publishes
updates to Redis for the Skrift notification system to fan out via SSE.

Run with: uv run python -m actiondash.step_worker
"""

import asyncio
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from skrift.config import get_settings
from skrift.lib.notification_backends import RedisBackend
from skrift.lib.notifications import NotificationMode, notify_user
from skrift.lib.notifications import notifications

from actiondash.models import WorkflowRun
from actiondash.step_poller import poll_loop

logger = logging.getLogger(__name__)

_last_poll_at: float = 0.0


def _make_publish_fn():
    """Create a publish callback that uses Skrift's notify_user API."""

    async def publish(type: str, *, group: str | None = None, user_ids: list[str] | None = None, **payload) -> None:
        if not user_ids:
            logger.warning("No user_ids for %s notification, skipping", type)
            return
        for uid in user_ids:
            try:
                await notify_user(
                    uid,
                    type,
                    group=group,
                    mode=NotificationMode.TIMESERIES,
                    **payload,
                )
            except Exception:
                logger.warning("Failed to notify user %s for %s", uid, type, exc_info=True)

    return publish


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

    engine = create_async_engine(settings.db.url, pool_size=2, max_overflow=0)
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    backend = RedisBackend(settings=settings, session_maker=session_maker)
    notifications.set_backend(backend)
    await backend.start()
    logger.info("Skrift RedisBackend started for step worker")

    publish_fn = _make_publish_fn()
    store_fn = _make_store_fn(session_maker)

    # Mark as healthy immediately so the first poll cycle doesn't fail the probe
    global _last_poll_at
    _last_poll_at = time.monotonic()

    def _mark_alive():
        global _last_poll_at
        _last_poll_at = time.monotonic()

    health_task = asyncio.create_task(_health_server())

    try:
        await poll_loop(session_maker, publish_fn, on_cycle=_mark_alive, store_fn=store_fn)
    finally:
        health_task.cancel()
        await backend.stop()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
