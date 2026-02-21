"""Worker admin dashboard controller."""

import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from litestar import Controller, Request, get
from litestar.response import Response
from litestar.response import Template as TemplateResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from skrift.auth.guards import auth_guard
from skrift.db.models.notification import StoredNotification

logger = logging.getLogger(__name__)


class WorkerAdminController(Controller):
    """Admin dashboard for monitoring the step worker process."""

    path = "/admin/worker"
    guards = [auth_guard]

    @get("/")
    async def worker_page(
        self, request: Request, db_session: AsyncSession
    ) -> TemplateResponse:
        user = await self._get_user(request, db_session)
        has_github = await self._has_github_token(db_session, user) if user else False

        return TemplateResponse(
            "admin/worker.html",
            context={
                "user": user,
                "has_github": has_github,
            },
        )

    @get("/uptime")
    async def worker_uptime(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """Return 24h uptime data in 5-minute buckets."""
        user_id = request.session.get("user_id")
        if not user_id:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        bucket_minutes = 5
        num_buckets = 24 * 60 // bucket_minutes

        result = await db_session.execute(
            select(
                StoredNotification.notified_at,
                StoredNotification.payload_json,
            )
            .where(
                StoredNotification.scope == "user",
                StoredNotification.scope_id == user_id,
                StoredNotification.type == "worker_activity",
                StoredNotification.delivery_mode == "timeseries",
                StoredNotification.notified_at > cutoff,
            )
        )
        rows = result.all()

        buckets = ["unknown"] * num_buckets
        for notified_at, payload_json in rows:
            try:
                payload = json.loads(payload_json)
            except (json.JSONDecodeError, TypeError):
                continue

            event = payload.get("event", "unknown")
            elapsed = (notified_at - cutoff).total_seconds()
            idx = int(elapsed / (bucket_minutes * 60))
            if idx < 0 or idx >= num_buckets:
                continue

            if event == "poll_heartbeat":
                buckets[idx] = "up"
            elif event == "poll_error" and buckets[idx] != "up":
                buckets[idx] = "error"

        # Any bucket between the first heartbeat and now with no data is "down"
        now_idx = min(
            int((now - cutoff).total_seconds() / (bucket_minutes * 60)),
            num_buckets - 1,
        )
        first_up = next((i for i, b in enumerate(buckets) if b == "up"), None)
        if first_up is not None:
            for i in range(first_up, now_idx + 1):
                if buckets[i] == "unknown":
                    buckets[i] = "down"

        known = [b for b in buckets if b not in ("unknown",)]
        up_count = sum(1 for b in known if b == "up")
        uptime_pct = round(up_count / len(known) * 100, 1) if known else None

        return Response(
            content={
                "buckets": buckets,
                "bucket_minutes": bucket_minutes,
                "start": cutoff.isoformat(),
                "uptime_pct": uptime_pct,
            },
            status_code=200,
        )

    @get("/events")
    async def worker_events(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        user_id = request.session.get("user_id")
        if not user_id:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        result = await db_session.execute(
            select(StoredNotification)
            .where(
                StoredNotification.scope == "user",
                StoredNotification.scope_id == user_id,
                StoredNotification.type == "worker_activity",
                StoredNotification.delivery_mode == "timeseries",
                StoredNotification.notified_at > cutoff,
            )
            .order_by(StoredNotification.notified_at.desc())
            .limit(5000)
        )
        rows = result.scalars().all()

        # Collapse consecutive heartbeats into single entries
        events: list[dict] = []
        for row in rows:
            try:
                payload = json.loads(row.payload_json)
            except (json.JSONDecodeError, TypeError):
                payload = {}

            event_type = payload.get("event", "unknown")

            if (
                event_type == "poll_heartbeat"
                and events
                and events[-1]["event"] == "poll_heartbeat"
            ):
                events[-1]["hb_count"] += 1
                continue

            entry = {
                "id": str(row.id),
                "event": event_type,
                "payload": payload,
                "group": row.group_key,
                "at": row.notified_at.isoformat(),
            }
            if event_type == "poll_heartbeat":
                entry["hb_count"] = 1
            events.append(entry)

        return Response(content={"events": events}, status_code=200)

    async def _get_user(self, request: Request, db_session: AsyncSession):
        from skrift.db.models.user import User

        user_id = request.session.get("user_id")
        if not user_id:
            return None
        result = await db_session.execute(
            select(User).where(User.id == UUID(user_id))
        )
        return result.scalar_one_or_none()

    async def _has_github_token(self, db_session: AsyncSession, user) -> bool:
        from actiondash.repo_services import get_user_github_token

        if not user:
            return False
        token = await get_user_github_token(db_session, user.id)
        return token is not None
