"""The default wallet is "Main account" (it was "Spending"): new users get the new name,
migration 0069 renames the old one only when that is safe, and nothing finds the wallet by
its name, so a user who renamed it loses nothing. Made-up data only."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexus.application import wallets as wallet_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import list_ledger
from nexus.domain.ledger import Direction, UserId, WalletKind
from nexus.infra.db.engine import make_engine
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent_wallets import run, wallets_of, with_wallets
from tests.integration.test_wallets import downgrade

pytestmark = pytest.mark.integration


async def test_a_new_user_starts_with_a_main_account_and_cash(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await wallet_cases.list_wallets(uow(), alice)
    assert [(w.name, w.kind) for w in wallets] == [
        ("Main account", WalletKind.SPENDING),
        ("Cash", WalletKind.CASH),
    ]


async def test_a_renamed_main_account_still_sends_a_transfer_with_no_source(
    uow: UowFactory, alice: UserId
) -> None:
    """``log_move`` without ``from_wallet`` finds the main account by its kind."""
    before = await with_wallets(uow, alice)
    await wallet_cases.update_wallet(uow(), alice, before["Main account"].id, name="Day to day")
    assert set(await wallets_of(uow, alice)) >= {"Day to day", "Cash", "IBKR"}

    said = await run(uow, alice, "log_move", {"amount": "40", "to_wallet": "IBKR"})
    assert said.startswith("Logged a transfer (not spending or income): ")
    page = await list_ledger(uow(), alice, LedgerQuery())
    (tx,) = [t for t in page.items if t.direction is Direction.MOVE]
    assert (tx.from_wallet_id, tx.to_wallet_id) == (
        before["Main account"].id,
        before["IBKR"].id,
    )

    # The confirmation names the wallet as it is called now.
    listed = await run(uow, alice, "list_wallets", {})
    assert listed.startswith("Day to day (the main account the budget watches)")


# --- migration 0069 ------------------------------------------------------------------------


async def _user(db: AsyncConnection, telegram_id: int) -> UUID:
    user = uuid4()
    await db.execute(
        text(
            "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, home_currency, "
            "role) VALUES (:id, :tg, 'UTC', 'UTC', 'SGD', 'owner')"
        ),
        {"id": user, "tg": telegram_id},
    )
    return user


async def _wallet(db: AsyncConnection, user: UUID, name: str, kind: str) -> None:
    await db.execute(
        text("INSERT INTO wallets (id, user_id, name, kind) VALUES (:id, :u, :n, :k)"),
        {"id": uuid4(), "u": user, "n": name, "k": kind},
    )


async def _names(engine: AsyncEngine, user: UUID) -> dict[str, str]:
    async with engine.connect() as db:
        rows = (
            await db.execute(
                text("SELECT kind, name FROM wallets WHERE user_id = :u ORDER BY name"),
                {"u": user},
            )
        ).all()
    return {f"{r.kind}:{r.name}": r.name for r in rows}


async def test_the_migration_renames_only_a_default_wallet_still_called_spending(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0068")
    engine = make_engine(empty_database_url)
    try:
        async with engine.begin() as db:
            plain = await _user(db, 901)  # the old default: renamed
            await _wallet(db, plain, "Spending", "spending")
            await _wallet(db, plain, "Cash", "cash")
            taken = await _user(db, 902)  # already has a "Main account": left alone
            await _wallet(db, taken, "Spending", "spending")
            await _wallet(db, taken, "main ACCOUNT", "other")  # the name check is by case, too
            renamed = await _user(db, 903)  # the user's own name: left alone
            await _wallet(db, renamed, "Pocket money", "spending")
            decoy = await _user(db, 904)  # a "Spending" that isn't the default wallet
            await _wallet(db, decoy, "Day to day", "spending")
            await _wallet(db, decoy, "Spending", "other")

        await upgrade(empty_database_url, "0069")
        assert set(await _names(engine, plain)) == {"spending:Main account", "cash:Cash"}
        assert set(await _names(engine, taken)) == {"spending:Spending", "other:main ACCOUNT"}
        assert set(await _names(engine, renamed)) == {"spending:Pocket money"}
        assert set(await _names(engine, decoy)) == {"spending:Day to day", "other:Spending"}

        # Down again: the same care, in reverse.
        async with engine.begin() as db:
            blocked = await _user(db, 905)  # has another "Spending" by then: left alone
            await _wallet(db, blocked, "Main account", "spending")
            await _wallet(db, blocked, "spending", "other")
        await downgrade(empty_database_url, "0068")
        assert set(await _names(engine, plain)) == {"spending:Spending", "cash:Cash"}
        assert set(await _names(engine, taken)) == {"spending:Spending", "other:main ACCOUNT"}
        assert set(await _names(engine, renamed)) == {"spending:Pocket money"}
        assert set(await _names(engine, blocked)) == {"spending:Main account", "other:spending"}
    finally:
        await engine.dispose()
