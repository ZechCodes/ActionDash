"""Shared test fixtures for ActionDash E2E tests."""

from collections.abc import AsyncGenerator

import pytest
from litestar import Litestar
from litestar.contrib.jinja import JinjaTemplateEngine
from litestar.middleware.session.client_side import CookieBackendConfig
from litestar.template.config import TemplateConfig
from litestar.testing import AsyncTestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from skrift.db.base import Base
from skrift.db.models.user import User

from actiondash.controllers import DashboardController, HealthController, WebhookController

_session_config = CookieBackendConfig(secret=b"testsecretkey123")


@pytest.fixture()
async def _db(tmp_path):
    """SQLite-backed async engine and session maker."""
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # Clear schema for SQLite compatibility
    saved_schema = Base.metadata.schema
    Base.metadata.schema = None

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine, session_maker

    Base.metadata.schema = saved_schema
    await engine.dispose()


@pytest.fixture()
async def app(_db, tmp_path):
    """Minimal Litestar app with dashboard, health, and webhook controllers."""
    _, session_maker = _db

    # Stub templates so Litestar can register template-returning routes
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir(exist_ok=True)
    (templates_dir / "dashboard").mkdir(exist_ok=True)
    for name in ["index.html", "dashboard/index.html", "dashboard/run_detail.html"]:
        (templates_dir / name).write_text("")

    async def provide_db_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_maker() as session:
            yield session

    return Litestar(
        route_handlers=[DashboardController, HealthController, WebhookController],
        dependencies={"db_session": provide_db_session},
        template_config=TemplateConfig(
            directory=templates_dir,
            engine=JinjaTemplateEngine,
        ),
        middleware=[_session_config.middleware],
    )


@pytest.fixture()
async def client(app):
    """Unauthenticated test client."""
    async with AsyncTestClient(app=app, session_config=_session_config) as c:
        yield c


@pytest.fixture()
async def authed_client(app, _db):
    """Authenticated test client with a real User row in the DB."""
    _, session_maker = _db

    async with session_maker() as session:
        user = User(email="test@example.com", name="Test User")
        session.add(user)
        await session.commit()
        user_id = str(user.id)

    async with AsyncTestClient(app=app, session_config=_session_config) as c:
        await c.set_session_data({"user_id": user_id})
        yield c
