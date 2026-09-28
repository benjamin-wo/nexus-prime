import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from alembic import command
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.users import RegisterUser, register_user
from nexus.domain.ledger import UserId
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.uow import SqlUnitOfWork

type UowFactory = Callable[[], SqlUnitOfWork]


async def upgrade(url: str, revision: str = "head") -> None:
    config = alembic_config(url)
    config.attributes["configure_logger"] = False
    # env.py drives its own event loop, so run it off this one.
    await asyncio.to_thread(command.upgrade, config, revision)


@pytest.fixture
async def engine(empty_database_url: str) -> AsyncIterator[AsyncEngine]:
    await upgrade(empty_database_url)
    engine = make_engine(empty_database_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def uow(engine: AsyncEngine) -> UowFactory:
    return lambda: SqlUnitOfWork(engine)


async def make_user(uow: UowFactory, telegram_user_id: int, currency: str = "SGD") -> UserId:
    registration = await register_user(
        uow(), RegisterUser(telegram_user_id=telegram_user_id, home_currency=currency)
    )
    return registration.user.id


@pytest.fixture
async def alice(uow: UowFactory) -> UserId:
    return await make_user(uow, 1001)


@pytest.fixture
async def bob(uow: UowFactory) -> UserId:
    return await make_user(uow, 2002)
