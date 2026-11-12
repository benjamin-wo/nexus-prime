"""Logging an expense by hand once per client key: the Idempotency-Key header the web app's
offline outbox sends, so an entry that arrives twice is recorded once. Made-up data."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import transactions as tx_cases
from nexus.application.clock import utcnow
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import NewTransaction, log_transaction_once
from nexus.domain.ledger import Direction, UserId
from nexus.domain.money import Money
from nexus.infra.db.engine import make_engine
from nexus.infra.db.tables import metadata
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_wallets import downgrade
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world

KEY = "7f3c9a52-1d4e-4b8a-9c60-2e5d8f1a0b34"
BODY = {"direction": "out", "amount": "4.80", "counterparty": "Kopi Corner"}
WHEN = datetime(2026, 9, 20, 12, tzinfo=UTC)


def key(value: str = KEY) -> dict[str, str]:
    return {"Idempotency-Key": value}


def entry(**extra: object) -> NewTransaction:
    return NewTransaction(
        Direction.OUT,
        Money.of("4.80", "SGD"),
        WHEN,
        counterparty="Kopi Corner",
        **extra,  # type: ignore[arg-type]
    )


async def count(engine: AsyncEngine, client_ref: str | None = KEY) -> int:
    async with engine.connect() as db:
        # Everyone's rows: no user is named on this connection.
        found = await db.execute(
            text("SELECT count(*) FROM transactions WHERE client_ref IS NOT DISTINCT FROM :k"),
            {"k": client_ref},
        )
        return int(found.scalar_one())


async def test_the_same_key_twice_records_one_expense_and_returns_it(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)

    first = await owner.send("POST", "/api/transactions", BODY, **key())
    assert first.status_code == 201
    # The reply was lost; the phone sends it again, even with a different body.
    again = await owner.send("POST", "/api/transactions", {**BODY, "amount": "99"}, **key())
    assert again.status_code == 200
    assert again.json() == first.json()
    assert again.json()["amount"]["amount"] == "4.8000"

    assert await count(world.engine) == 1
    assert (await owner.get("/api/transactions")).json()["total"] == 1


async def test_a_key_is_optional_and_without_one_every_post_is_new(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    for _ in range(2):
        assert (await owner.send("POST", "/api/transactions", BODY)).status_code == 201
    assert (await owner.get("/api/transactions")).json()["total"] == 2
    assert await count(world.engine, None) == 2


async def test_another_users_key_never_matches(world: World) -> None:
    owner, token = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite=token)).status_code == 200

    mine = await owner.send("POST", "/api/transactions", BODY, **key())
    theirs = await member.send("POST", "/api/transactions", BODY, **key())
    assert mine.status_code == theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"]
    assert await count(world.engine) == 2

    # Each still gets their own back, and nobody sees the other's.
    assert (await owner.send("POST", "/api/transactions", BODY, **key())).json() == mine.json()
    assert (await member.send("POST", "/api/transactions", BODY, **key())).json() == theirs.json()
    assert (await member.get("/api/transactions")).json()["total"] == 1


@pytest.mark.parametrize(
    "bad", ["short", "x" * 65, "has space in it", "slash/slash/slash", "semi;colon;key!", ""]
)
async def test_a_malformed_key_is_rejected(world: World, bad: str) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    refused = await owner.send("POST", "/api/transactions", BODY, **key(bad))
    assert refused.status_code == 422
    assert (await owner.get("/api/transactions")).json()["total"] == 0


@pytest.mark.parametrize("good", ["abcdefgh", "A_b-C_d-E", "x" * 64, KEY])
async def test_keys_of_8_to_64_url_safe_characters_are_accepted(world: World, good: str) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    assert (await owner.send("POST", "/api/transactions", BODY, **key(good))).status_code == 201


async def test_a_refused_entry_leaves_nothing_and_the_key_free(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    refused = await owner.send("POST", "/api/transactions", {**BODY, "amount": "0"}, **key())
    assert refused.status_code == 422
    assert await count(world.engine) == 0
    assert (await owner.send("POST", "/api/transactions", BODY, **key())).status_code == 201


async def test_simultaneous_requests_with_one_key_record_one_expense(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    replies = await asyncio.gather(
        *[owner.send("POST", "/api/transactions", BODY, **key()) for _ in range(8)]
    )
    assert sorted(r.status_code for r in replies) == [200] * 7 + [201]
    assert len({r.json()["id"] for r in replies}) == 1
    assert await count(world.engine) == 1


async def test_a_request_that_loses_the_race_returns_the_winners_row(
    uow: UowFactory, alice: UserId
) -> None:
    """One request is mid-commit when another finds the key free: the second insert waits,
    finds the key taken and writes nothing, and answers with the first's transaction."""
    cmd = entry(client_ref=KEY)
    async with uow() as winner:
        made = await tx_cases.create_transaction(winner.ledger, alice, cmd, now=utcnow())
        loser = asyncio.create_task(log_transaction_once(uow(), alice, cmd))
        await asyncio.sleep(0.5)  # it has looked, found nothing, and is waiting on the insert
        assert not loser.done()
        await winner.commit()
    got, created = await asyncio.wait_for(loser, 10)
    assert not created and got.id == made.id

    page = await tx_cases.list_ledger(uow(), alice, LedgerQuery())
    assert page.total == 1


async def test_the_key_is_kept_through_edits_and_a_repeat_returns_the_edited_row(
    uow: UowFactory, alice: UserId
) -> None:
    cmd = entry(client_ref=KEY)
    tx, created = await log_transaction_once(uow(), alice, cmd)
    assert created and tx.client_ref == KEY
    edited = await tx_cases.edit_transaction(
        uow(), alice, tx.id, tx_cases.TransactionChanges(notes="with cake")
    )
    assert edited.client_ref == KEY
    again, created = await log_transaction_once(uow(), alice, cmd)
    assert not created and again.id == tx.id and again.notes == "with cake"


async def test_a_deleted_entry_is_not_brought_back_by_its_key(
    uow: UowFactory, alice: UserId
) -> None:
    cmd = entry(client_ref=KEY)
    tx, _ = await log_transaction_once(uow(), alice, cmd)
    await tx_cases.delete_transaction(uow(), alice, tx.id)
    again, created = await log_transaction_once(uow(), alice, cmd)
    assert not created and again.id == tx.id and again.is_deleted


def test_the_column_and_unique_index_are_in_the_table_definitions() -> None:
    table = metadata.tables["transactions"]
    assert table.c.client_ref.nullable
    index = next(i for i in table.indexes if i.name == "uq_transactions_user_id_client_ref")
    assert index.unique and [c.name for c in index.columns] == ["user_id", "client_ref"]
    assert str(index.dialect_options["postgresql"]["where"]) == "client_ref IS NOT NULL"


async def test_the_migration_adds_and_removes_the_column_and_index(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0070")
    engine = make_engine(empty_database_url)
    user = uuid4()
    insert = (
        "INSERT INTO transactions (id, user_id, direction, amount, currency, occurred_at, status, "
        "source, created_at, updated_at{extra}) VALUES (gen_random_uuid(), :u, 'out', 5, 'SGD', "
        "now(), 'confirmed', 'manual', now(), now(){value})"
    )

    async def parts() -> tuple[int, int]:
        async with engine.connect() as db:
            columns = await db.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns WHERE "
                    "table_name = 'transactions' AND column_name = 'client_ref'"
                )
            )
            indexes = await db.execute(
                text(
                    "SELECT count(*) FROM pg_indexes WHERE "
                    "indexname = 'uq_transactions_user_id_client_ref'"
                )
            )
            return int(columns.scalar_one()), int(indexes.scalar_one())

    try:
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, "
                    "home_currency, role) VALUES (:id, 990, 'UTC', 'UTC', 'SGD', 'owner')"
                ),
                {"id": user},
            )
            await db.execute(text(insert.format(extra="", value="")), {"u": user})
        assert await parts() == (0, 0)

        await upgrade(empty_database_url, "0071")
        assert await parts() == (1, 1)
        # The row from before has no key, and any number of those are fine; a key is once.
        with_key = insert.format(extra=", client_ref", value=", 'abcdefgh'")
        async with engine.begin() as db:
            await db.execute(text(with_key), {"u": user})
            await db.execute(text(insert.format(extra="", value="")), {"u": user})
        with pytest.raises(Exception, match="uq_transactions_user_id_client_ref"):
            async with engine.begin() as db:
                await db.execute(text(with_key), {"u": user})

        await downgrade(empty_database_url, "0070")
        assert await parts() == (0, 0)
        await upgrade(empty_database_url, "0071")
        assert await parts() == (1, 1)
    finally:
        await engine.dispose()
