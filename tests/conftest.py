import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
import pytest
from sqlalchemy.engine import make_url


@asynccontextmanager
async def throwaway_database() -> AsyncIterator[str]:
    """A freshly created, empty database (asyncpg URL), dropped afterwards.

    TEST_DATABASE_URL points at a server where the user may CREATE DATABASE.
    """
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not admin_url:
        pytest.skip("TEST_DATABASE_URL is not set")
    admin = make_url(admin_url).set(drivername="postgresql")
    name = f"nexus_test_{uuid.uuid4().hex[:12]}"
    dsn = admin.render_as_string(hide_password=False)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()
    try:
        yield admin.set(drivername="postgresql+asyncpg", database=name).render_as_string(
            hide_password=False
        )
    finally:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            await conn.close()


@pytest.fixture
async def empty_database_url() -> AsyncIterator[str]:
    async with throwaway_database() as url:
        yield url
