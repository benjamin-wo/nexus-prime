import asyncio

import pytest
from alembic import command
from httpx import ASGITransport, AsyncClient

from nexus.infra.db.migrations import PendingMigrationsError, alembic_config
from nexus.main import create_app
from nexus.settings import Settings

pytestmark = pytest.mark.integration


def _settings(url: str) -> Settings:
    return Settings(_env_file=None, database_url=url)


async def _upgrade(url: str, revision: str = "head") -> None:
    config = alembic_config(url)
    config.attributes["configure_logger"] = False
    # env.py drives its own event loop, so run it off this one.
    await asyncio.to_thread(command.upgrade, config, revision)


async def test_startup_refuses_unmigrated_database(empty_database_url: str) -> None:
    app = create_app(_settings(empty_database_url))
    with pytest.raises(PendingMigrationsError, match="no revision"):
        async with app.router.lifespan_context(app):
            pass


async def test_healthz_ok_once_migrated(empty_database_url: str) -> None:
    await _upgrade(empty_database_url)
    app = create_app(_settings(empty_database_url))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_migrations_round_trip(empty_database_url: str) -> None:
    await _upgrade(empty_database_url)
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "base")
    await _upgrade(empty_database_url)
