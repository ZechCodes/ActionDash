"""ActionDash middleware for initialization."""

from litestar.types import ASGIApp, Receive, Scope, Send


class EnsureNeonThemeMiddleware:
    """Middleware that ensures the neon theme is set as active on first request.

    This runs once per server process, setting site_theme="neon" in the database
    if it hasn't been set yet. This ensures all static and template directories
    are properly resolved through the theme system.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._initialized = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only initialize on the first HTTP request
        if not self._initialized and scope["type"] == "http":
            self._initialized = True
            try:
                await self._ensure_theme()
            except Exception:
                # Silently fail if DB isn't ready yet
                pass

        await self.app(scope, receive, send)

    async def _ensure_theme(self) -> None:
        """Set neon as the active theme if not already set."""
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from skrift.config import get_settings

        settings = get_settings()
        engine = create_async_engine(settings.db.url)
        async_session = async_sessionmaker(engine, expire_on_commit=False)

        try:
            async with async_session() as session:
                from skrift.db.services.setting_service import get_setting, set_setting, SITE_THEME_KEY, load_site_settings_cache

                theme = await get_setting(session, SITE_THEME_KEY)
                if not theme:
                    await set_setting(session, SITE_THEME_KEY, "neon")

                # Always reload the cache — the sync preload may have failed
                # (e.g. missing psycopg2, incompatible DSN params)
                await load_site_settings_cache(session)

                # Update Jinja search path now that the theme is cached
                from skrift.app_factory import update_template_directories
                update_template_directories()
        finally:
            await engine.dispose()
