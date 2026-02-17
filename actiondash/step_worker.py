"""Standalone step-progress worker process.

Polls GitHub for step-level detail on active workflow runs and publishes
updates to Redis for the Skrift notification system to fan out via SSE.

Run with: uv run python -m actiondash.step_worker
"""

import asyncio
import json
import logging
import time
from uuid import uuid4

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from skrift.config import get_settings

from actiondash.step_poller import poll_loop

logger = logging.getLogger(__name__)

_last_poll_at: float = 0.0


async def _make_publish_fn(redis_client: aioredis.Redis, channel: str):
    """Create a publish callback that writes directly to Redis."""

    async def publish(type: str, *, group: str | None = None, **payload) -> None:
        notification = {"type": type, "id": str(uuid4()), **payload}
        if group is not None:
            notification["group"] = group
        message = json.dumps({"a": "b", "n": notification})
        try:
            await redis_client.publish(channel, message)
        except Exception:
            logger.warning("Failed to publish %s to Redis", type, exc_info=True)

    return publish


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

    redis_client = aioredis.Redis.from_url(settings.redis.url)
    channel = settings.redis.make_key("skrift", "notifications")
    logger.info("Publishing to Redis channel: %s", channel)

    publish_fn = await _make_publish_fn(redis_client, channel)

    # Mark as healthy immediately so the first poll cycle doesn't fail the probe
    global _last_poll_at
    _last_poll_at = time.monotonic()

    def _mark_alive():
        global _last_poll_at
        _last_poll_at = time.monotonic()

    health_task = asyncio.create_task(_health_server())

    try:
        await poll_loop(session_maker, publish_fn, on_cycle=_mark_alive)
    finally:
        health_task.cancel()
        await redis_client.aclose()
        await engine.dispose()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
