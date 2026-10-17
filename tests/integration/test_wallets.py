"""Wallets (named places money sits) and moves between them. Made-up names and amounts."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.categories import list_categories
from nexus.application.splits import split_bill
from nexus.application.transactions import (
    NewTransaction,
    TransactionChanges,
    delete_transaction,
    edit_transaction,
    get_transaction,
    log_transaction,
    undo_last,
)
from nexus.application.wallets import (
    add_wallet,
    delete_wallet,
    list_wallets,
    log_move,
    mark_as_move,
    rename_wallet,
    update_wallet,
)
from nexus.domain.errors import Conflict, InvalidInput, NotFound, NothingToUndo
from nexus.domain.ledger import (
    Direction,
    RevisionKind,
    ShareRequest,
    Source,
    UserId,
    Wallet,
    WalletKind,
    apply_snapshot,
    snapshot,
)
from nexus.domain.money import Money
from nexus.infra.db.engine import make_engine
from nexus.infra.db.migrations import alembic_config
from tests.integration.conftest import UowFactory, upgrade

pytestmark = pytest.mark.integration

T0 = datetime(2026, 9, 1, 9, tzinfo=UTC)


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def spending(uow: UowFactory, user: UserId) -> Wallet:
    return (await list_wallets(uow(), user))[0]


async def names(uow: UowFactory, user: UserId) -> list[str]:
    return [w.name for w in await list_wallets(uow(), user)]


async def downgrade(url: str, revision: str) -> None:
    config = alembic_config(url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, revision)


async def raw_insert(engine: AsyncEngine, user: UserId, **values: object) -> None:
    row: dict[str, object] = {
        "id": uuid4(),
        "user_id": user,
        "direction": "out",
        "amount": 5,
        "currency": "SGD",
        "occurred_at": T0,
        "status": "confirmed",
        "source": "manual",
        "created_at": T0,
        "updated_at": T0,
    } | values
    columns = ", ".join(row)
    params = ", ".join(f":{k}" for k in row)
    async with engine.begin() as db:
        await db.execute(text(f"INSERT INTO transactions ({columns}) VALUES ({params})"), row)  # noqa: S608


# --- migration ----------------------------------------------------------------


async def test_the_migration_gives_every_user_one_spending_wallet(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0041")
    engine = make_engine(empty_database_url)
    ann, ben, spent = uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as db:
            for n, user in enumerate((ann, ben)):
                await db.execute(
                    text(
                        "INSERT INTO users (id, telegram_user_id, timezone, home_currency, role) "
                        "VALUES (:id, :tg, 'Asia/Singapore', 'SGD', 'owner')"
                    ),
                    {"id": user, "tg": 500 + n},
                )
            await db.execute(
                text(
                    "INSERT INTO transactions (id, user_id, direction, amount, currency, "
                    "occurred_at, status, source, created_at, updated_at) "
                    "VALUES (:id, :u, 'out', 12.5, 'SGD', :at, 'confirmed', 'text', :at, :at)"
                ),
                {"id": spent, "u": ann, "at": T0},
            )
        await upgrade(empty_database_url, "0042")
        async with engine.connect() as db:
            wallets = (await db.execute(text("SELECT user_id, name, kind FROM wallets"))).all()
            tx = (
                await db.execute(
                    text(
                        "SELECT direction, amount, from_wallet_id, to_wallet_id, "
                        "received_amount, received_currency FROM transactions WHERE id = :id"
                    ),
                    {"id": spent},
                )
            ).one()
        assert sorted((w.user_id, w.name, w.kind) for w in wallets) == sorted(
            (u, "Spending", "spending") for u in (ann, ben)
        )
        assert (tx.direction, float(tx.amount)) == ("out", 12.5)
        assert (tx.from_wallet_id, tx.to_wallet_id) == (None, None)
        assert (tx.received_amount, tx.received_currency) == (None, None)

        # Down again: a move goes (with its history), everything else stays.
        async with engine.begin() as db:
            home: UUID = (
                await db.execute(text("SELECT id FROM wallets WHERE user_id = :u"), {"u": ann})
            ).scalar_one()
            other = uuid4()
            await db.execute(
                text(
                    "INSERT INTO wallets (id, user_id, name, kind) "
                    "VALUES (:id, :u, 'Invest', 'investment')"
                ),
                {"id": other, "u": ann},
            )
            move = uuid4()
            await db.execute(
                text(
                    "INSERT INTO transactions (id, user_id, direction, amount, currency, "
                    "occurred_at, status, source, created_at, updated_at, from_wallet_id, "
                    "to_wallet_id) VALUES (:id, :u, 'move', 50, 'SGD', :at, 'confirmed', "
                    "'manual', :at, :at, :a, :b)"
                ),
                {"id": move, "u": ann, "at": T0, "a": home, "b": other},
            )
            await db.execute(
                text(
                    "INSERT INTO transaction_revisions (user_id, transaction_id, kind, created_at) "
                    "VALUES (:u, :t, 'create', :at)"
                ),
                {"u": ann, "t": move, "at": T0},
            )
        await downgrade(empty_database_url, "0041")
        async with engine.connect() as db:
            left = [r.id for r in await db.execute(text("SELECT id FROM transactions"))]
            tables: str | None = (
                await db.execute(text("SELECT to_regclass('public.wallets')"))
            ).scalar_one()
            columns: int = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'transactions' AND column_name LIKE '%wallet%'"
                    )
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert left == [spent]
    assert tables is None and columns == 0


# --- wallets ------------------------------------------------------------------


async def test_a_new_user_has_a_spending_wallet(uow: UowFactory, alice: UserId) -> None:
    wallets = await list_wallets(uow(), alice)
    assert [(w.name, w.kind, w.match_words) for w in wallets] == [
        ("Spending", WalletKind.SPENDING, ())
    ]
    assert wallets[0].user_id == alice


async def test_add_rename_update_and_list_wallets(uow: UowFactory, alice: UserId) -> None:
    broker = await add_wallet(
        uow(), alice, "  Brokerage ", "investment", ["ACME Securities", " acme securities ", ""]
    )
    await add_wallet(uow(), alice, "Rainy Day", WalletKind.SAVINGS)
    await add_wallet(uow(), alice, "apple card", WalletKind.CARD)
    assert broker.name == "Brokerage"
    assert broker.match_words == ("ACME Securities",)  # tidied, no repeats
    # Spending first, then by name regardless of case.
    assert await names(uow, alice) == ["Spending", "apple card", "Brokerage", "Rainy Day"]

    renamed = await rename_wallet(uow(), alice, broker.id, "Stocks")
    assert renamed.name == "Stocks" and renamed.kind is WalletKind.INVESTMENT
    changed = await update_wallet(
        uow(), alice, broker.id, kind="other", match_words=["acme", "ACME"]
    )
    assert (changed.kind, changed.match_words) == (WalletKind.OTHER, ("acme",))
    again = next(w for w in await list_wallets(uow(), alice) if w.id == broker.id)
    assert again == changed


async def test_wallet_refusals(uow: UowFactory, alice: UserId) -> None:
    home = await spending(uow, alice)
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    with pytest.raises(InvalidInput, match="Spending"):
        await add_wallet(uow(), alice, "Second", "spending")
    with pytest.raises(InvalidInput, match="kind"):
        await add_wallet(uow(), alice, "Odd", "pension")
    with pytest.raises(InvalidInput, match="empty"):
        await add_wallet(uow(), alice, "   ", "other")
    with pytest.raises(InvalidInput, match="characters"):
        await add_wallet(uow(), alice, "x" * 101, "other")
    with pytest.raises(Conflict, match="already exists"):
        await add_wallet(uow(), alice, "RAINY day", "other")
    with pytest.raises(Conflict, match="already exists"):
        await add_wallet(uow(), alice, "spending", "other")
    with pytest.raises(Conflict, match="already exists"):
        await rename_wallet(uow(), alice, saver.id, "SPENDING")
    with pytest.raises(InvalidInput, match="can't change kind"):
        await update_wallet(uow(), alice, home.id, kind="savings")
    with pytest.raises(InvalidInput, match="can't change kind"):
        await update_wallet(uow(), alice, saver.id, kind="spending")
    with pytest.raises(NotFound):
        await rename_wallet(uow(), alice, uuid4(), "Ghost")
    assert await names(uow, alice) == ["Spending", "Rainy Day"]


async def test_wallets_are_private_to_their_owner(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    mine = await add_wallet(uow(), alice, "Rainy Day", "savings")
    await add_wallet(uow(), bob, "rainy day", "savings")  # same name is fine for Bob
    assert len(await list_wallets(uow(), bob)) == 2
    with pytest.raises(NotFound):
        await rename_wallet(uow(), bob, mine.id, "Mine now")
    with pytest.raises(NotFound):
        await delete_wallet(uow(), bob, mine.id)
    assert (await spending(uow, alice)).id != (await spending(uow, bob)).id


async def test_delete_wallet(uow: UowFactory, alice: UserId) -> None:
    home = await spending(uow, alice)
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    with pytest.raises(InvalidInput, match="can't be deleted"):
        await delete_wallet(uow(), alice, home.id, saver.id)
    with pytest.raises(NotFound):
        await delete_wallet(uow(), alice, uuid4())

    # Nothing recorded against it: it just goes.
    result = await delete_wallet(uow(), alice, saver.id)
    assert (result.wallet, result.moved, result.removed) == (saver, 0, 0)
    assert await names(uow, alice) == ["Spending", "Brokerage"]

    # With moves, it needs another wallet to hand them to.
    await log_move(uow(), alice, amount=sgd("100"), to_wallet_id=broker.id, occurred_at=T0)
    with pytest.raises(InvalidInput, match="pick another wallet"):
        await delete_wallet(uow(), alice, broker.id)
    with pytest.raises(InvalidInput, match="different wallet"):
        await delete_wallet(uow(), alice, broker.id, broker.id)
    with pytest.raises(NotFound):
        await delete_wallet(uow(), alice, broker.id, uuid4())
    assert await names(uow, alice) == ["Spending", "Brokerage"]


async def test_deleting_a_wallet_repoints_its_moves_and_drops_the_ones_that_collapse(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    home = await spending(uow, alice)
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    into = await log_move(uow(), alice, amount=sgd("100"), to_wallet_id=broker.id, occurred_at=T0)
    out = await log_move(
        uow(), alice, amount=sgd("30"), from_wallet_id=broker.id, to_wallet_id=saver.id,
        occurred_at=T0,
    )  # fmt: skip
    gone = await log_move(
        uow(), alice, amount=sgd("5"), from_wallet_id=saver.id, to_wallet_id=broker.id,
        occurred_at=T0,
    )  # fmt: skip
    old = await log_move(uow(), alice, amount=sgd("9"), to_wallet_id=broker.id, occurred_at=T0)
    await delete_transaction(uow(), alice, old.id)  # deleted rows still name the wallet

    result = await delete_wallet(uow(), alice, broker.id, saver.id)
    assert (result.into, result.moved, result.removed) == (saver, 2, 2)
    assert await names(uow, alice) == ["Spending", "Rainy Day"]

    # Spending -> Brokerage is now Spending -> Rainy Day, deleted one included; the two moves
    # between Brokerage and Rainy Day would have been Rainy Day -> Rainy Day, so they're gone.
    moved = await get_transaction(uow(), alice, into.id)
    assert (moved.from_wallet_id, moved.to_wallet_id) == (home.id, saver.id)
    assert moved.updated_at > into.updated_at
    assert (await get_transaction(uow(), alice, old.id)).to_wallet_id == saver.id
    for tx_id in (out.id, gone.id):
        with pytest.raises(NotFound):
            await get_transaction(uow(), alice, tx_id)
    # Their history went with them, so undo walks back to what still exists.
    assert (await undo_last(uow(), alice)).transaction.id == old.id
    # Bob is untouched by any of it.
    assert len(await list_wallets(uow(), bob)) == 1


# --- moves --------------------------------------------------------------------


async def test_log_move_defaults_to_the_spending_wallet(uow: UowFactory, alice: UserId) -> None:
    home = await spending(uow, alice)
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    tx = await log_move(
        uow(), alice, amount=sgd("250"), to_wallet_id=broker.id, occurred_at=T0,
        notes="  monthly  ", counterparty="ACME Securities", source=Source.TEXT,
    )  # fmt: skip
    assert tx.direction is Direction.MOVE and tx.is_move
    assert (tx.from_wallet_id, tx.to_wallet_id) == (home.id, broker.id)
    assert (tx.category_id, tx.category_rule_id, tx.received_amount) == (None, None, None)
    assert (tx.notes, tx.counterparty, tx.source) == ("monthly", "ACME Securities", Source.TEXT)
    assert await get_transaction(uow(), alice, tx.id) == tx


async def test_a_move_can_say_what_arrived(uow: UowFactory, alice: UserId) -> None:
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    tx = await log_move(
        uow(), alice, amount=sgd("135"), to_wallet_id=broker.id, occurred_at=T0,
        received_amount=Money.of("100", "USD"),
    )  # fmt: skip
    stored = await get_transaction(uow(), alice, tx.id)
    assert stored.received_amount == Money.of("100", "USD")
    assert stored.amount == sgd("135")
    with pytest.raises(InvalidInput, match="greater than zero"):
        await log_move(
            uow(), alice, amount=sgd("5"), to_wallet_id=broker.id, occurred_at=T0,
            received_amount=Money.of("0", "USD"),
        )  # fmt: skip


async def test_moves_between_other_wallets_and_the_card_bill(
    uow: UowFactory, alice: UserId
) -> None:
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    card = await add_wallet(uow(), alice, "Visa", "card")
    tx = await log_move(
        uow(), alice, amount=sgd("40"), from_wallet_id=saver.id, to_wallet_id=broker.id,
        occurred_at=T0,
    )  # fmt: skip
    assert (tx.from_wallet_id, tx.to_wallet_id) == (saver.id, broker.id)
    bill = await log_move(uow(), alice, amount=sgd("300"), to_wallet_id=card.id, occurred_at=T0)
    assert bill.to_wallet_id == card.id


async def test_log_move_refusals(uow: UowFactory, alice: UserId, bob: UserId) -> None:
    home = await spending(uow, alice)
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    theirs = await add_wallet(uow(), bob, "Brokerage", "investment")
    with pytest.raises(InvalidInput, match="two different wallets"):
        await log_move(uow(), alice, amount=sgd("5"), to_wallet_id=home.id, occurred_at=T0)
    with pytest.raises(InvalidInput, match="two different wallets"):
        await log_move(
            uow(), alice, amount=sgd("5"), from_wallet_id=broker.id, to_wallet_id=broker.id,
            occurred_at=T0,
        )  # fmt: skip
    with pytest.raises(InvalidInput, match="greater than zero"):
        await log_move(uow(), alice, amount=sgd("0"), to_wallet_id=broker.id, occurred_at=T0)
    with pytest.raises(InvalidInput, match="timezone"):
        await log_move(
            uow(), alice, amount=sgd("5"), to_wallet_id=broker.id, occurred_at=datetime(2026, 9, 1)
        )
    # Another user's wallet looks like no wallet at all, on either side.
    with pytest.raises(NotFound):
        await log_move(uow(), alice, amount=sgd("5"), to_wallet_id=theirs.id, occurred_at=T0)
    with pytest.raises(NotFound):
        await log_move(
            uow(), alice, amount=sgd("5"), from_wallet_id=theirs.id, to_wallet_id=broker.id,
            occurred_at=T0,
        )  # fmt: skip
    with pytest.raises(NotFound):
        await log_move(uow(), alice, amount=sgd("5"), to_wallet_id=uuid4(), occurred_at=T0)
    # Nothing was written, for anyone.
    with pytest.raises(NothingToUndo):
        await undo_last(uow(), alice)
    with pytest.raises(NothingToUndo):
        await undo_last(uow(), bob)


async def test_undoing_a_move_deletes_it(uow: UowFactory, alice: UserId) -> None:
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    tx = await log_move(uow(), alice, amount=sgd("75"), to_wallet_id=broker.id, occurred_at=T0)
    undone = await undo_last(uow(), alice)
    assert undone.undone is RevisionKind.CREATE
    assert undone.transaction.id == tx.id and undone.transaction.is_deleted
    assert (await get_transaction(uow(), alice, tx.id)).is_deleted


async def test_a_deleted_move_comes_back_with_its_wallets(uow: UowFactory, alice: UserId) -> None:
    home = await spending(uow, alice)
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    tx = await log_move(uow(), alice, amount=sgd("75"), to_wallet_id=broker.id, occurred_at=T0)
    await delete_transaction(uow(), alice, tx.id)
    # The wallet it named is deleted before the delete is undone: the move follows its moves.
    await delete_wallet(uow(), alice, broker.id, saver.id)
    restored = (await undo_last(uow(), alice)).transaction
    assert not restored.is_deleted
    assert (restored.from_wallet_id, restored.to_wallet_id) == (home.id, saver.id)


async def test_a_move_cannot_be_edited_into_spending_or_given_a_category(
    uow: UowFactory, alice: UserId
) -> None:
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    tx = await log_move(uow(), alice, amount=sgd("75"), to_wallet_id=broker.id, occurred_at=T0)
    category = (await list_categories(uow(), alice))[0]
    with pytest.raises(InvalidInput, match="can't be changed"):
        await edit_transaction(uow(), alice, tx.id, TransactionChanges(direction=Direction.OUT))
    with pytest.raises(InvalidInput, match="no category"):
        await edit_transaction(uow(), alice, tx.id, TransactionChanges(category_id=category.id))
    edited = await edit_transaction(uow(), alice, tx.id, TransactionChanges(amount=sgd("80")))
    assert edited.amount == sgd("80") and edited.is_move
    # And the other way: money out isn't edited into a move, nor logged as one.
    spent = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, sgd("4"), T0, counterparty="Kopi")
    )
    with pytest.raises(InvalidInput, match="can't be changed"):
        await edit_transaction(uow(), alice, spent.id, TransactionChanges(direction=Direction.MOVE))
    with pytest.raises(InvalidInput, match="log_move"):
        await log_transaction(uow(), alice, NewTransaction(Direction.MOVE, sgd("4"), T0))


# --- marking an existing transaction as a move --------------------------------


async def test_mark_money_out_as_a_move_and_undo_it(uow: UowFactory, alice: UserId) -> None:
    home = await spending(uow, alice)
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    categories = {c.id: c.name for c in await list_categories(uow(), alice)}
    other = next(i for i, n in categories.items() if n == "Shopping")
    spent = await log_transaction(
        uow(),
        alice,
        NewTransaction(
            Direction.OUT, sgd("500"), T0, counterparty="ACME Securities", category_id=other
        ),
    )
    moved = await mark_as_move(uow(), alice, spent.id, broker.id)
    assert moved.direction is Direction.MOVE
    assert (moved.from_wallet_id, moved.to_wallet_id) == (home.id, broker.id)
    assert (moved.category_id, moved.category_rule_id) == (None, None)
    assert (moved.amount, moved.counterparty) == (sgd("500"), "ACME Securities")
    assert await get_transaction(uow(), alice, spent.id) == moved
    with pytest.raises(InvalidInput, match="already a move"):
        await mark_as_move(uow(), alice, spent.id, broker.id)

    undone = await undo_last(uow(), alice)
    assert undone.undone is RevisionKind.EDIT
    back = await get_transaction(uow(), alice, spent.id)
    assert back.direction is Direction.OUT
    assert back.category_id == other and categories[other] == "Shopping"
    assert (back.from_wallet_id, back.to_wallet_id) == (None, None)
    assert back.amount == sgd("500")


async def test_mark_money_in_as_a_move_from_that_wallet(uow: UowFactory, alice: UserId) -> None:
    home = await spending(uow, alice)
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    income = await log_transaction(
        uow(), alice, NewTransaction(Direction.IN, sgd("200"), T0, counterparty="Rainy Day")
    )
    assert income.category_id is not None
    moved = await mark_as_move(uow(), alice, income.id, saver.id)
    assert (moved.from_wallet_id, moved.to_wallet_id) == (saver.id, home.id)
    assert moved.category_id is None
    await undo_last(uow(), alice)
    back = await get_transaction(uow(), alice, income.id)
    assert (back.direction, back.category_id) == (Direction.IN, income.category_id)


async def test_undoing_mark_as_move_after_the_category_was_deleted(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.application.categories import create_category, delete_category

    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    hobby = await create_category(uow(), alice, "Old Hobby")
    spent = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, sgd("20"), T0, category_id=hobby.id)
    )
    await mark_as_move(uow(), alice, spent.id, broker.id)
    await delete_category(uow(), alice, hobby.id, None, now=T0)
    back = (await undo_last(uow(), alice)).transaction
    other = next(c.id for c in await list_categories(uow(), alice) if c.name == "Other")
    assert (back.direction, back.category_id) == (Direction.OUT, other)  # never uncategorised


async def test_mark_as_move_refusals(uow: UowFactory, alice: UserId, bob: UserId) -> None:
    home = await spending(uow, alice)
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    theirs = await add_wallet(uow(), bob, "Brokerage", "investment")
    spent = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, sgd("60"), T0, counterparty="Cafe")
    )
    await split_bill(uow(), alice, spent.id, [ShareRequest("Ann")])
    with pytest.raises(Conflict, match="split"):
        await mark_as_move(uow(), alice, spent.id, broker.id)

    plain = await log_transaction(uow(), alice, NewTransaction(Direction.OUT, sgd("6"), T0))
    with pytest.raises(InvalidInput, match="other than Spending"):
        await mark_as_move(uow(), alice, plain.id, home.id)
    with pytest.raises(NotFound):
        await mark_as_move(uow(), alice, plain.id, theirs.id)
    with pytest.raises(NotFound):
        await mark_as_move(uow(), alice, plain.id, uuid4())
    with pytest.raises(NotFound):
        await mark_as_move(uow(), alice, uuid4(), broker.id)
    with pytest.raises(NotFound):
        await mark_as_move(uow(), bob, plain.id, theirs.id)
    await delete_transaction(uow(), alice, plain.id)
    with pytest.raises(InvalidInput, match="deleted"):
        await mark_as_move(uow(), alice, plain.id, broker.id)
    assert (await get_transaction(uow(), alice, spent.id)).direction is Direction.OUT


async def test_money_in_that_paid_back_a_friend_cannot_become_a_move(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.application.splits import settle_iou

    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    bill = await log_transaction(uow(), alice, NewTransaction(Direction.OUT, sgd("20"), T0))
    await split_bill(uow(), alice, bill.id, [ShareRequest("Ann")])
    repaid = await settle_iou(uow(), alice, "Ann", sgd("10"), T0)
    with pytest.raises(Conflict, match="paid back"):
        await mark_as_move(uow(), alice, repaid.transaction.id, broker.id)


# --- snapshots ------------------------------------------------------------------


async def test_snapshots_carry_wallets_and_old_ones_still_apply(
    uow: UowFactory, alice: UserId
) -> None:
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    tx = await log_move(
        uow(), alice, amount=sgd("10"), to_wallet_id=broker.id, occurred_at=T0,
        received_amount=Money.of("7", "USD"),
    )  # fmt: skip
    data = snapshot(tx)
    assert data["to_wallet_id"] == str(broker.id) and data["received_currency"] == "USD"
    assert apply_snapshot(tx, data, now=tx.updated_at) == tx
    # A snapshot from before wallets existed has none of those keys.
    old = {k: v for k, v in data.items() if "wallet" not in k and "received" not in k}
    plain = apply_snapshot(tx, old | {"direction": "out", "category_id": None}, now=T0)
    assert (plain.from_wallet_id, plain.to_wallet_id, plain.received_amount) == (None, None, None)


# --- the database itself ----------------------------------------------------------


async def test_the_database_refuses_inconsistent_moves(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    home = await spending(uow, alice)
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    theirs = await spending(uow, bob)
    category = (await list_categories(uow(), alice))[0].id

    async def refused(**values: object) -> None:
        with pytest.raises(IntegrityError):
            await raw_insert(engine, alice, **values)

    wallets: dict[str, object] = {"from_wallet_id": home.id, "to_wallet_id": broker.id}
    await refused(direction="move")  # a move without wallets
    await refused(direction="move", from_wallet_id=home.id)  # or with one
    await refused(direction="move", from_wallet_id=home.id, to_wallet_id=home.id)
    await refused(direction="out", **wallets)  # money out with wallets
    await refused(direction="in", from_wallet_id=home.id)
    await refused(direction="move", category_id=category, **wallets)  # a move has no category
    await refused(direction="move", received_amount=5, **wallets)  # an amount without currency
    await refused(direction="move", received_currency="USD", **wallets)  # and the reverse
    await refused(direction="move", received_amount=0, received_currency="USD", **wallets)
    await refused(direction="sideways")
    # Another user's wallet can't be named, even by raw SQL.
    await refused(direction="move", from_wallet_id=theirs.id, to_wallet_id=broker.id)

    await raw_insert(engine, alice, direction="move", **wallets)
    await raw_insert(
        engine, alice, direction="move", received_amount=7, received_currency="USD", **wallets
    )
    await raw_insert(engine, alice, direction="out", category_id=category)


async def test_the_database_allows_one_spending_wallet_and_unique_names(
    engine: AsyncEngine, alice: UserId
) -> None:
    async def add(name: str, kind: str) -> None:
        async with engine.begin() as db:
            await db.execute(
                text("INSERT INTO wallets (id, user_id, name, kind) VALUES (:id, :u, :n, :k)"),
                {"id": uuid4(), "u": alice, "n": name, "k": kind},
            )

    with pytest.raises(IntegrityError):
        await add("Another", "spending")
    with pytest.raises(IntegrityError):
        await add("SPENDING", "other")
    with pytest.raises(IntegrityError):
        await add("Odd", "pension")
    await add("Fine", "other")
