"""Sign-in identities (migration 0073): the backfill, finding a user by identity, the unique
constraint, and a Telegram sign-up writing its identity. Made-up data only."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from nexus.application.users import RegisterUser, find_telegram_user, register_user
from nexus.domain.errors import Conflict
from nexus.domain.identity import Provider
from nexus.domain.ledger import UserId
from nexus.infra.db.engine import make_engine
from tests.integration.conftest import UowFactory, make_user, upgrade
from tests.integration.test_wallets import downgrade

pytestmark = pytest.mark.integration

INSERT_USER = (
    "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, home_currency, role) "
    "VALUES (:id, :tg, 'UTC', 'UTC', 'SGD', 'member')"
)


async def test_the_migration_gives_every_real_telegram_user_one_identity_and_demos_none(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0071")
    engine = make_engine(empty_database_url)
    real = {uuid4(): 5001, uuid4(): 5002}
    demo = {uuid4(): -77, uuid4(): -78}
    try:
        async with engine.begin() as db:
            for user, tg in {**real, **demo}.items():
                await db.execute(text(INSERT_USER), {"id": user, "tg": tg})

        await upgrade(empty_database_url, "0073")
        async with engine.connect() as db:
            rows = (
                await db.execute(text("SELECT user_id, provider, subject FROM user_identities"))
            ).all()
        assert sorted((r.user_id, r.provider, r.subject) for r in rows) == sorted(
            (user, "telegram", str(tg)) for user, tg in real.items()
        )

        # The Telegram id is optional now (nulls don't collide).
        async with engine.begin() as db:
            await db.execute(text(INSERT_USER), {"id": uuid4(), "tg": None})
            await db.execute(text(INSERT_USER), {"id": uuid4(), "tg": None})

        # Going back is refused while someone has no Telegram id, and works once they are gone.
        with pytest.raises(Exception, match="no Telegram id"):
            await downgrade(empty_database_url, "0071")
        async with engine.begin() as db:
            await db.execute(text("DELETE FROM users WHERE telegram_user_id IS NULL"))
        await downgrade(empty_database_url, "0071")
        async with engine.connect() as db:
            tables: str | None = (
                await db.execute(text("SELECT to_regclass('user_identities')::text"))
            ).scalar_one()
        assert tables is None
        await upgrade(empty_database_url, "head")
    finally:
        await engine.dispose()


async def test_a_telegram_sign_up_also_writes_its_identity(uow: UowFactory) -> None:
    user = await make_user(uow, 4242)
    async with uow() as tx:
        found = await tx.ledger.get_user_by_identity(Provider.TELEGRAM, "4242")
        identities = await tx.ledger.list_identities(user)
    assert found is not None and found.id == user
    assert [(i.provider, i.subject) for i in identities] == [(Provider.TELEGRAM, "4242")]
    # Signing up again changes nothing.
    again = await register_user(uow(), RegisterUser(telegram_user_id=4242, home_currency="SGD"))
    assert not again.created
    async with uow() as tx:
        assert len(await tx.ledger.list_identities(user)) == 1


async def test_a_demo_style_negative_id_gets_no_identity(uow: UowFactory) -> None:
    registration = await register_user(
        uow(), RegisterUser(telegram_user_id=-9, home_currency="SGD")
    )
    async with uow() as tx:
        assert await tx.ledger.list_identities(registration.user.id) == []


async def test_the_telegram_columns_and_identities_agree(uow: UowFactory) -> None:
    ids = [await make_user(uow, n) for n in (3001, 3002, 3003)]
    for user_id, n in zip(ids, (3001, 3002, 3003), strict=True):
        async with uow() as tx:
            by_column = await tx.ledger.get_user_by_telegram_id(n)
            by_identity = await tx.ledger.get_user_by_identity(Provider.TELEGRAM, str(n))
        assert by_column is not None and by_identity is not None
        assert by_column.id == by_identity.id == user_id
    assert await find_telegram_user(uow(), 9999) is None


async def test_an_identity_can_be_added_found_and_belongs_to_one_user(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    async with uow() as tx:
        added = await tx.ledger.add_identity(
            alice, Provider.EMAIL, "a@example.com", "A@Example.com"
        )
        await tx.commit()
    assert added.email == "a@example.com"
    async with uow() as tx:
        found = await tx.ledger.get_user_by_identity(Provider.EMAIL, "a@example.com")
        assert found is not None and found.id == alice
        assert await tx.ledger.get_user_by_identity(Provider.APPLE, "a@example.com") is None
        assert len(await tx.ledger.list_identities(alice)) == 2  # Telegram and email
        with pytest.raises(Conflict):  # taken, by someone else
            await tx.ledger.add_identity(bob, Provider.EMAIL, "a@example.com")
        with pytest.raises(Conflict):  # and by themselves
            await tx.ledger.add_identity(alice, Provider.EMAIL, "a@example.com")
        # The same subject under another provider is a different identity.
        await tx.ledger.add_identity(bob, Provider.APPLE, "a@example.com")
