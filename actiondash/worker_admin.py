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

    @get("/events")
    async def worker_events(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        user_id = request.session.get("user_id")
        if not user_id:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

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
            .limit(500)
        )
        rows = result.scalars().all()

        events = []
        for row in rows:
            try:
                payload = json.loads(row.payload_json)
            except (json.JSONDecodeError, TypeError):
                payload = {}
            events.append({
                "id": str(row.id),
                "event": payload.get("event", "unknown"),
                "payload": payload,
                "group": row.group_key,
                "at": row.notified_at.isoformat(),
            })

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
