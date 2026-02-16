"""Data access layer for repo monitoring and user settings."""

import os
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from actiondash.github_client import GitHubClient
from actiondash.models import MonitoredRepo, UserSettings

# Simple in-memory cache: {user_id: (timestamp, repos_list)}
_repo_cache: dict[UUID, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300  # 5 minutes


async def get_user_github_token(session: AsyncSession, user_id: UUID) -> str | None:
    """Get the GitHub OAuth access token for a user."""
    from skrift.db.models.oauth_account import OAuthAccount

    result = await session.execute(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user_id,
            OAuthAccount.provider == "github",
        )
    )
    account = result.scalar_one_or_none()
    if not account:
        return None
    # access_token will be available once Skrift persists it (issue #33)
    return getattr(account, "access_token", None)


async def get_user_repos(
    access_token: str, user_id: UUID, *, force_refresh: bool = False
) -> list[dict]:
    """Fetch user repos from GitHub API with 5-minute TTL cache."""
    now = time.monotonic()

    if not force_refresh and user_id in _repo_cache:
        cached_at, repos = _repo_cache[user_id]
        if now - cached_at < _CACHE_TTL:
            return repos

    client = GitHubClient(access_token)
    repos = await client.list_repos()
    _repo_cache[user_id] = (now, repos)
    return repos


async def get_monitored_repos(
    session: AsyncSession, user_id: UUID
) -> list[MonitoredRepo]:
    """Get all repos a user has enabled for monitoring."""
    result = await session.execute(
        select(MonitoredRepo)
        .where(MonitoredRepo.user_id == user_id)
        .order_by(MonitoredRepo.repo_full_name)
    )
    return list(result.scalars().all())


async def set_repo_monitored(
    session: AsyncSession,
    user_id: UUID,
    repo_data: dict,
    webhook_id: int | None = None,
) -> MonitoredRepo:
    """Enable monitoring for a repo. Creates or updates the MonitoredRepo record."""
    repo_full_name = repo_data["full_name"]
    result = await session.execute(
        select(MonitoredRepo).where(
            MonitoredRepo.user_id == user_id,
            MonitoredRepo.repo_full_name == repo_full_name,
        )
    )
    monitored = result.scalar_one_or_none()

    if monitored is None:
        monitored = MonitoredRepo(
            user_id=user_id,
            repo_full_name=repo_full_name,
        )
        session.add(monitored)

    monitored.repo_github_id = repo_data["id"]
    monitored.webhook_id = webhook_id
    monitored.is_private = repo_data.get("private", False)
    monitored.description = repo_data.get("description")
    monitored.default_branch = repo_data.get("default_branch")

    await session.flush()
    return monitored


async def remove_repo_monitored(
    session: AsyncSession, user_id: UUID, repo_full_name: str
) -> MonitoredRepo | None:
    """Disable monitoring for a repo. Returns the deleted record or None."""
    result = await session.execute(
        select(MonitoredRepo).where(
            MonitoredRepo.user_id == user_id,
            MonitoredRepo.repo_full_name == repo_full_name,
        )
    )
    monitored = result.scalar_one_or_none()
    if monitored:
        await session.delete(monitored)
        await session.flush()
    return monitored


async def get_user_settings(
    session: AsyncSession, user_id: UUID
) -> UserSettings:
    """Get or create user settings."""
    result = await session.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        await session.flush()
    return settings


async def update_user_settings(
    session: AsyncSession, user_id: UUID, **kwargs
) -> UserSettings:
    """Update user settings."""
    settings = await get_user_settings(session, user_id)
    for key, value in kwargs.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    await session.flush()
    return settings


def get_webhook_url() -> str:
    """Build the webhook callback URL from config."""
    from skrift.config import get_settings

    base_url = get_settings().auth.redirect_base_url.rstrip("/")
    return f"{base_url}/webhooks/github"


def get_webhook_secret() -> str:
    """Get the webhook secret from environment."""
    return os.environ.get("GITHUB_WEBHOOK_SECRET", "")
