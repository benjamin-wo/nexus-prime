from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nexus.channels.web import health
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import assert_schema_at_head
from nexus.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(resolved.database_url_str)
        try:
            await assert_schema_at_head(engine)
            app.state.engine = engine
            yield
        finally:
            await engine.dispose()

    app = FastAPI(title="Nexus Prime", lifespan=lifespan)
    app.state.settings = resolved
    app.include_router(health.router)
    return app
