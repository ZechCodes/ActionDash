"""Initialize the ActionDash database.

Creates all tables for both Skrift core models and ActionDash models.

Run with:
    uv run python -m actiondash.initdb
"""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from skrift.db.base import Base

# Import all models to register them with Base.metadata
from skrift.db.models.user import User  # noqa: F401
from skrift.db.models.page import Page  # noqa: F401
from skrift.db.models.page_revision import PageRevision  # noqa: F401
from skrift.db.models.role import Role, RolePermission  # noqa: F401
from skrift.db.models.oauth_account import OAuthAccount  # noqa: F401
from skrift.db.models.setting import Setting  # noqa: F401
from actiondash.models import WorkflowRun, WorkflowJob, MonitoredRepo, UserSettings  # noqa: F401


async def init_db() -> None:
    from skrift.config import get_settings

    settings = get_settings()
    engine = create_async_engine(settings.db.url)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Add columns that create_all won't add to existing tables
    async with engine.begin() as conn:
        for column, col_type in [
            ("access_token", "VARCHAR(2048)"),
            ("refresh_token", "VARCHAR(2048)"),
        ]:
            try:
                await conn.execute(text(
                    f"ALTER TABLE oauth_accounts ADD COLUMN {column} {col_type}"
                ))
                print(f"Added column oauth_accounts.{column}")
            except Exception:
                pass  # Column already exists

    await engine.dispose()
    print(f"Database initialized at: {settings.db.url}")


if __name__ == "__main__":
    asyncio.run(init_db())
