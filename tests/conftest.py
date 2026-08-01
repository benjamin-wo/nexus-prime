import asyncio
import pytest
import pytest_asyncio
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import os
import core.db as db_mod
import core.models  # noqa: F401 - ensure models are registered with SQLModel.metadata

TEST_DB_PATH = "./test_testdb.sqlite"

@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Initialize database schema before each test and drop after."""
    async with db_mod.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield
    async with db_mod.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
