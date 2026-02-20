"""Dashboard and webhook controllers for ActionDash."""

import json
import logging
from uuid import UUID

import actiondash.worker_monitor  # noqa: F401 — register NOTIFICATION_SENT hook

from litestar import Controller, Request, get, post, delete
from litestar.exceptions import NotFoundException
from litestar.response import Response
from litestar.response import Template as TemplateResponse
from sqlalchemy.ext.asyncio import AsyncSession

from skrift.auth.guards import auth_guard
from skrift.lib.notifications import notify_user, NotificationMode

from actiondash.models import WorkflowRun
from actiondash.services import (
    get_active_runs,
    get_daily_run_counts,
    get_jobs_for_run,
    get_monitoring_user_ids,
    get_recent_runs,
    get_run_stats,
    upsert_workflow_job,
    upsert_workflow_run,
)
from actiondash.step_poller import _build_step_summary
from actiondash.webhook import verify_signature

log = logging.getLogger(__name__)


class DashboardController(Controller):
    """Serves the dashboard UI and API endpoints."""

    path = "/"

    @get("/")
    async def index(
        self, request: Request, db_session: AsyncSession
    ) -> TemplateResponse:
        """Main dashboard page."""
        user_id = request.session.get("user_id")
        if not user_id:
            return TemplateResponse("index.html", context={"user": None})

        repo = request.query_params.get("repo")
        stats = await get_run_stats(db_session, repo_full_name=repo)
        active_runs = await get_active_runs(db_session, repo_full_name=repo)
        recent_runs = await get_recent_runs(
            db_session, limit=30, repo_full_name=repo
        )
        user = await self._get_user(request, db_session)
        has_github = await self._has_github_token(db_session, user) if user else False

        return TemplateResponse(
            "dashboard/index.html",
            context={
                "stats": stats,
                "active_runs": active_runs,
                "recent_runs": recent_runs,
                "user": user,
                "current_repo": repo,
                "has_github": has_github,
            },
        )

    @get("/runs/{run_id:int}", guards=[auth_guard])
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
        user = await self._get_user(request, db_session)
        has_github = await self._has_github_token(db_session, user) if user else False

        return TemplateResponse(
            "dashboard/run_detail.html",
            context={
                "run": run,
                "jobs": jobs,
                "user": user,
                "has_github": has_github,
            },
        )

    @get("/api/runs", guards=[auth_guard])
    async def api_runs(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """JSON API: recent workflow runs."""
        repo = request.query_params.get("repo")
        recent = await get_recent_runs(
            db_session, limit=50, repo_full_name=repo
        )
        return Response(
            content={"runs": [r.to_dict() for r in recent]},
            status_code=200,
        )

    @get("/api/active", guards=[auth_guard])
    async def api_active(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """JSON API: currently active runs."""
        repo = request.query_params.get("repo")
        active = await get_active_runs(db_session, repo_full_name=repo)
        return Response(
            content={"runs": [r.to_dict() for r in active]},
            status_code=200,
        )

    @get("/api/stats", guards=[auth_guard])
    async def api_stats(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """JSON API: dashboard statistics."""
        repo = request.query_params.get("repo")
        stats = await get_run_stats(db_session, repo_full_name=repo)
        return Response(content=stats, status_code=200)

    @get("/api/daily-runs", guards=[auth_guard])
    async def api_daily_runs(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """JSON API: daily run counts for 60-day bar chart."""
        repo = request.query_params.get("repo")
        daily = await get_daily_run_counts(db_session, repo_full_name=repo)
        return Response(content={"days": daily}, status_code=200)

    async def _get_user(self, request: Request, db_session: AsyncSession):
        from sqlalchemy import select
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


class RepoController(Controller):
    """API endpoints for repo management and monitoring."""

    path = "/api/repos"
    guards = [auth_guard]

    @get("/")
    async def list_repos(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """List user's GitHub repos."""
        from actiondash.repo_services import get_user_github_token, get_user_repos

        user = await self._get_user(request, db_session)
        if not user:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        token = await get_user_github_token(db_session, user.id)
        if not token:
            return Response(content={"repos": [], "no_token": True}, status_code=200)

        try:
            force = request.query_params.get("refresh") == "1"
            repos = await get_user_repos(token, user.id, force_refresh=force)
            return Response(
                content={
                    "repos": [
                        {
                            "full_name": r["full_name"],
                            "id": r["id"],
                            "private": r.get("private", False),
                            "description": r.get("description"),
                            "default_branch": r.get("default_branch"),
                        }
                        for r in repos
                    ]
                },
                status_code=200,
            )
        except Exception:
            log.exception("Failed to fetch repos from GitHub")
            return Response(
                content={"error": "Failed to fetch repos"}, status_code=502
            )

    @get("/monitored")
    async def list_monitored(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """List user's monitored repos."""
        from actiondash.repo_services import get_monitored_repos

        user = await self._get_user(request, db_session)
        if not user:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        monitored = await get_monitored_repos(db_session, user.id)
        return Response(
            content={"repos": [m.to_dict() for m in monitored]},
            status_code=200,
        )

    @post("/{owner:str}/{repo:str}/monitor")
    async def enable_monitoring(
        self, request: Request, db_session: AsyncSession, owner: str, repo: str
    ) -> Response:
        """Enable monitoring for a repo (creates a webhook)."""
        from actiondash.github_client import GitHubClient
        from actiondash.repo_services import (
            get_user_github_token,
            get_user_repos,
            get_webhook_secret,
            get_webhook_url,
            set_repo_monitored,
        )

        repo_full_name = f"{owner}/{repo}"

        user = await self._get_user(request, db_session)
        if not user:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        token = await get_user_github_token(db_session, user.id)
        if not token:
            return Response(content={"error": "No GitHub token"}, status_code=400)

        # Find repo data from cache or API
        repos = await get_user_repos(token, user.id)
        repo_data = next(
            (r for r in repos if r["full_name"] == repo_full_name), None
        )
        if not repo_data:
            return Response(content={"error": "Repo not found"}, status_code=404)

        # Create webhook on GitHub
        secret = get_webhook_secret()
        if not secret:
            log.error("GITHUB_WEBHOOK_SECRET not configured")
            return Response(
                content={"error": "Webhook secret not configured"},
                status_code=500,
            )
        try:
            client = GitHubClient(token)
            hook = await client.create_webhook(
                repo_full_name, get_webhook_url(), secret
            )
            webhook_id = hook["id"]
        except Exception:
            log.exception("Failed to create webhook for %s", repo_full_name)
            return Response(
                content={"error": "Failed to create webhook"},
                status_code=502,
            )

        monitored = await set_repo_monitored(
            db_session, user.id, repo_data, webhook_id
        )
        await db_session.commit()

        return Response(
            content={"ok": True, "repo": monitored.to_dict()}, status_code=200
        )

    @delete("/{owner:str}/{repo:str}/monitor", status_code=200)
    async def disable_monitoring(
        self, request: Request, db_session: AsyncSession, owner: str, repo: str
    ) -> Response:
        """Disable monitoring for a repo (deletes the webhook)."""
        from actiondash.github_client import GitHubClient
        from actiondash.repo_services import (
            get_user_github_token,
            remove_repo_monitored,
        )

        repo_full_name = f"{owner}/{repo}"

        user = await self._get_user(request, db_session)
        if not user:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        token = await get_user_github_token(db_session, user.id)

        # Remove from DB (returns the record with webhook_id)
        monitored = await remove_repo_monitored(db_session, user.id, repo_full_name)
        if not monitored:
            return Response(content={"error": "Repo not monitored"}, status_code=404)

        # Delete webhook on GitHub if we have a token and webhook_id
        if token and monitored.webhook_id:
            try:
                client = GitHubClient(token)
                await client.delete_webhook(repo_full_name, monitored.webhook_id)
            except Exception:
                log.warning(
                    "Failed to delete webhook %d for %s",
                    monitored.webhook_id,
                    repo_full_name,
                )

        await db_session.commit()
        return Response(content={"ok": True}, status_code=200)

    @post("/monitor-all")
    async def monitor_all(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """Enable monitoring for all user repos."""
        from actiondash.github_client import GitHubClient
        from actiondash.repo_services import (
            get_monitored_repos,
            get_user_github_token,
            get_user_repos,
            get_webhook_secret,
            get_webhook_url,
            set_repo_monitored,
        )

        user = await self._get_user(request, db_session)
        if not user:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        token = await get_user_github_token(db_session, user.id)
        if not token:
            return Response(content={"error": "No GitHub token"}, status_code=400)

        repos = await get_user_repos(token, user.id)
        already_monitored = {
            m.repo_full_name
            for m in await get_monitored_repos(db_session, user.id)
        }

        secret = get_webhook_secret()
        webhook_url = get_webhook_url()
        client = GitHubClient(token)

        results = {"enabled": 0, "skipped": 0, "failed": 0}
        for repo_data in repos:
            if repo_data["full_name"] in already_monitored:
                results["skipped"] += 1
                continue

            webhook_id = None
            if secret:
                try:
                    hook = await client.create_webhook(
                        repo_data["full_name"], webhook_url, secret
                    )
                    webhook_id = hook["id"]
                except Exception:
                    log.warning(
                        "Failed to create webhook for %s",
                        repo_data["full_name"],
                    )
                    results["failed"] += 1
                    continue

            await set_repo_monitored(db_session, user.id, repo_data, webhook_id)
            results["enabled"] += 1

        await db_session.commit()
        return Response(content={"ok": True, **results}, status_code=200)

    async def _get_user(self, request: Request, db_session: AsyncSession):
        from sqlalchemy import select
        from skrift.db.models.user import User

        user_id = request.session.get("user_id")
        if not user_id:
            return None
        result = await db_session.execute(
            select(User).where(User.id == UUID(user_id))
        )
        return result.scalar_one_or_none()


class SettingsController(Controller):
    """Settings page and API."""

    path = "/settings"
    guards = [auth_guard]

    @get("/")
    async def settings_page(
        self, request: Request, db_session: AsyncSession
    ) -> TemplateResponse:
        """Render the settings page."""
        from actiondash.repo_services import get_user_github_token, get_user_settings

        user = await self._get_user(request, db_session)
        if not user:
            return TemplateResponse("dashboard/settings.html", context={"user": None})

        has_github = await self._has_github_token(db_session, user)
        settings = await get_user_settings(db_session, user.id)

        return TemplateResponse(
            "dashboard/settings.html",
            context={
                "user": user,
                "has_github": has_github,
                "settings": settings,
            },
        )

    @post("/auto-monitor")
    async def toggle_auto_monitor(
        self, request: Request, db_session: AsyncSession
    ) -> Response:
        """Toggle auto-monitor preference (stub for future GitHub App)."""
        from actiondash.repo_services import update_user_settings

        user = await self._get_user(request, db_session)
        if not user:
            return Response(content={"error": "Not authenticated"}, status_code=401)

        body = await request.json()
        enabled = bool(body.get("enabled", False))
        await update_user_settings(
            db_session, user.id, auto_monitor_new_repos=enabled
        )
        await db_session.commit()
        return Response(content={"ok": True, "enabled": enabled}, status_code=200)

    async def _get_user(self, request: Request, db_session: AsyncSession):
        from sqlalchemy import select
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


class HealthController(Controller):
    """Unauthenticated health check for k8s probes."""

    path = "/healthz"

    @get("/")
    async def health(self) -> Response:
        return Response(content={"ok": True}, status_code=200)


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

            repo_name = payload["repository"]["full_name"]
            user_ids = await get_monitoring_user_ids(db_session, repo_name)
            for uid in user_ids:
                try:
                    await notify_user(
                        uid,
                        "workflow_run",
                        group=f"run-{run.run_id}",
                        mode=NotificationMode.TIMESERIES,
                        action=action,
                        run=run.to_dict(),
                    )
                except Exception:
                    log.warning("Failed to notify user %s for run %d", uid, run.run_id)

            return Response(
                content={"ok": True, "run_id": run.run_id}, status_code=200
            )

        if event_type == "workflow_job":
            job = await upsert_workflow_job(db_session, payload)
            await db_session.commit()

            repo_name = payload["repository"]["full_name"]
            run_id = payload["workflow_job"].get("run_id")

            # Prepopulate step_summary on the WorkflowRun
            if run_id and action in ("in_progress", "completed"):
                await self._update_step_summary(
                    db_session, payload, action, repo_name, run_id
                )

            user_ids = await get_monitoring_user_ids(db_session, repo_name)
            for uid in user_ids:
                try:
                    await notify_user(
                        uid,
                        "workflow_job",
                        group=f"job-{job.job_id}",
                        mode=NotificationMode.TIMESERIES,
                        action=action,
                        job=job.to_dict(),
                    )
                except Exception:
                    log.warning("Failed to notify user %s for job %d", uid, job.job_id)

            return Response(
                content={"ok": True, "job_id": job.job_id}, status_code=200
            )

        # Ignore other event types
        return Response(content={"ok": True, "ignored": event_type}, status_code=200)

    async def _update_step_summary(
        self,
        db_session: AsyncSession,
        payload: dict,
        action: str,
        repo_name: str,
        run_id: int,
    ) -> None:
        """Persist step progress on the WorkflowRun when a job starts or completes."""
        from sqlalchemy import select
        from actiondash.github_client import GitHubClient
        from actiondash.repo_services import get_user_github_token
        from actiondash.models import MonitoredRepo

        try:
            if action == "in_progress":
                # Fetch steps from API — the in_progress webhook doesn't include them
                result = await db_session.execute(
                    select(MonitoredRepo.user_id).where(
                        MonitoredRepo.repo_full_name == repo_name
                    )
                )
                user_ids = result.scalars().all()
                token = None
                for uid in user_ids:
                    token = await get_user_github_token(db_session, uid)
                    if token:
                        break
                if not token:
                    return

                client = GitHubClient(token)
                jobs = await client.get_run_jobs(repo_name, run_id)
                summary = _build_step_summary(jobs)

            else:
                # action == "completed" — extract steps from webhook payload
                wf_job = payload["workflow_job"]
                summary = _build_step_summary([wf_job])

            # Merge into existing step_summary on the run
            result = await db_session.execute(
                select(WorkflowRun).where(WorkflowRun.run_id == run_id)
            )
            run = result.scalar_one_or_none()
            if run:
                existing = run.step_summary or {}
                existing.update(summary)
                run.step_summary = existing
                await db_session.commit()

        except Exception:
            log.warning(
                "Failed to update step_summary for run %d (%s)",
                run_id, action, exc_info=True,
            )
