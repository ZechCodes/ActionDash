"""Dashboard and webhook controllers for ActionDash."""

import json

from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException, NotFoundException
from litestar.response import Redirect, Response
from litestar.response import Template as TemplateResponse
from sqlalchemy.ext.asyncio import AsyncSession

from skrift.auth.guards import auth_guard
from skrift.lib.notifications import notify_broadcast

from actiondash.models import WorkflowRun, WorkflowJob
from actiondash.services import (
    get_active_runs,
    get_jobs_for_run,
    get_recent_runs,
    get_run_stats,
    upsert_workflow_job,
    upsert_workflow_run,
)
from actiondash.webhook import verify_signature


class DashboardController(Controller):
    """Serves the dashboard UI and API endpoints."""

    path = "/dashboard"
    guards = [auth_guard]

    @get("/")
    async def index(
        self, request: Request, db_session: AsyncSession
    ) -> TemplateResponse:
        """Main dashboard page."""
        stats = await get_run_stats(db_session)
        active_runs = await get_active_runs(db_session)
        recent_runs = await get_recent_runs(db_session, limit=30)

        return TemplateResponse(
            "dashboard/index.html",
            context={
                "stats": stats,
                "active_runs": active_runs,
                "recent_runs": recent_runs,
                "user": await self._get_user(request, db_session),
            },
        )

    @get("/runs/{run_id:int}")
    async def run_detail(
        self, request: Request, db_session: AsyncSession, run_id: int
    ) -> TemplateResponse:
        """Detail view for a specific workflow run."""
        from sqlalchemy import select

        result = await db_session.execute(
            select(WorkflowRun).where(WorkflowRun.run_id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise NotFoundException(f"Run {run_id} not found")

        jobs = await get_jobs_for_run(db_session, run_id)

        return TemplateResponse(
            "dashboard/run_detail.html",
            context={
                "run": run,
                "jobs": jobs,
                "user": await self._get_user(request, db_session),
            },
        )

    @get("/api/runs")
    async def api_runs(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """JSON API: recent workflow runs."""
        recent = await get_recent_runs(db_session, limit=50)
        return Response(
            content={"runs": [r.to_dict() for r in recent]},
            status_code=200,
        )

    @get("/api/active")
    async def api_active(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """JSON API: currently active runs."""
        active = await get_active_runs(db_session)
        return Response(
            content={"runs": [r.to_dict() for r in active]},
            status_code=200,
        )

    @get("/api/stats")
    async def api_stats(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """JSON API: dashboard statistics."""
        stats = await get_run_stats(db_session)
        return Response(content=stats, status_code=200)

    async def _get_user(self, request: Request, db_session: AsyncSession):
        from uuid import UUID
        from sqlalchemy import select
        from skrift.db.models.user import User

        user_id = request.session.get("user_id")
        if not user_id:
            return None
        result = await db_session.execute(
            select(User).where(User.id == UUID(user_id))
        )
        return result.scalar_one_or_none()


class WebhookController(Controller):
    """Receives GitHub webhook events."""

    path = "/webhooks"

    @post("/github")
    async def github_webhook(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """Handle incoming GitHub webhook events.

        Processes workflow_run and workflow_job events to track CI/CD status.
        """
        body = await request.body()
        signature = request.headers.get("x-hub-signature-256")

        if not verify_signature(body, signature):
            return Response(content={"error": "Invalid signature"}, status_code=401)

        event_type = request.headers.get("x-github-event")
        if not event_type:
            return Response(content={"error": "Missing event type"}, status_code=400)

        payload = json.loads(body)
        action = payload.get("action", "")

        if event_type == "workflow_run":
            run = await upsert_workflow_run(db_session, payload)
            await db_session.commit()

            # Broadcast realtime update to all connected dashboard clients
            notify_broadcast(
                "workflow_run",
                group=f"run-{run.run_id}",
                action=action,
                run=run.to_dict(),
            )

            return Response(
                content={"ok": True, "run_id": run.run_id}, status_code=200
            )

        if event_type == "workflow_job":
            job = await upsert_workflow_job(db_session, payload)
            await db_session.commit()

            notify_broadcast(
                "workflow_job",
                group=f"job-{job.job_id}",
                action=action,
                job=job.to_dict(),
            )

            return Response(
                content={"ok": True, "job_id": job.job_id}, status_code=200
            )

        # Ignore other event types
        return Response(content={"ok": True, "ignored": event_type}, status_code=200)
