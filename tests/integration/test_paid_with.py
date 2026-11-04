"""Which card paid for an expense: card details on wallets, the Cash wallet, "paid with" on
expenses, the usual card, the per-card spend, matching from emails and imports, and the chat
tools. Names, digits and amounts are all made up."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.tools import ToolContext, build_tools, run_tool
from nexus.application import email as email_cases
from nexus.application import statements as statement_cases
from nexus.application import wallets as wallet_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import (
    NewTransaction,
    TransactionChanges,
    edit_transaction,
    get_transaction,
    list_ledger,
    log_transaction,
    undo_last,
)
from nexus.application.users import get_user, set_track_cards
from nexus.application.wallets import add_wallet, list_wallets, update_wallet
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, UserId, Wallet, WalletKind
from nexus.domain.money import Money
from nexus.infra.db.engine import make_engine
from tests.fakes import NOW, FakeMailbox, call, fake_email, say, scripted
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, tool_results
from tests.integration.test_email import connect, person, sweep
from tests.integration.test_wallets import downgrade
from tests.integration.test_web_api import OWNER, Browser, World

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

DAY = "2026-09-20"


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


async def wallets_by_name(uow: UowFactory, user: UserId) -> dict[str, Wallet]:
    return {w.name: w for w in await list_wallets(uow(), user)}


async def cards(uow: UowFactory, user: UserId, *, track: bool = True) -> dict[str, Wallet]:
    """Two made-up cards, and the wallets everyone has. The user tracks which card paid
    (``track``), unless a test is about simple mode."""
    if track:
        await set_track_cards(uow(), user, True)
    await add_wallet(
        uow(), user, "Citi PremierMiles", "card",
        issuer="Citi", product="PremierMiles", network="visa", last4="4321",
    )  # fmt: skip
    await add_wallet(
        uow(), user, "DBS Altitude", "card",
        issuer="DBS", product="Altitude", network="mastercard", last4="8765",
    )  # fmt: skip
    return await wallets_by_name(uow, user)


async def expense(uow: UowFactory, user: UserId, amount: str = "12.50", **extra: Any) -> Any:
    cmd = NewTransaction(
        Direction.OUT, sgd(amount), NOW, counterparty=extra.pop("counterparty", "Kopi Corner"),
        **extra,
    )  # fmt: skip
    return await log_transaction(uow(), user, cmd)


async def run(uow: UowFactory, user: UserId, tool: str, args: dict[str, Any]) -> str:
    ctx = ToolContext(await get_user(uow(), user), uow, NOW)
    return (await run_tool(build_tools(lambda _: "")[tool], ctx, args)).text


# --- card details ----------------------------------------------------------------------


async def test_a_card_keeps_its_details_and_only_its_last_four_digits(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    citi = found["Citi PremierMiles"]
    assert (citi.issuer, citi.product, citi.network.value, citi.last4) == (  # type: ignore[union-attr]
        "Citi", "PremierMiles", "visa", "4321",
    )  # fmt: skip

    # A whole card number is cut to its last four before anything is stored.
    long = await add_wallet(uow(), alice, "Old card", "card", last4="1357 2468 1357 1234")
    assert long.last4 == "1234"
    async with uow() as tx:
        stored = await tx.ledger.get_wallet(alice, long.id)
    assert stored is not None and stored.last4 == "1234"

    for bad in ("12ab", "xxxx-1234", "123", "1234 abcd", "4111.1111"):
        with pytest.raises(InvalidInput):
            await add_wallet(uow(), alice, f"Bad {bad}", "card", last4=bad)
    with pytest.raises(InvalidInput, match="network"):
        await add_wallet(uow(), alice, "Odd", "card", network="diners")
    with pytest.raises(InvalidInput, match="issuer"):
        await add_wallet(uow(), alice, "Long", "card", issuer="x" * 41)
    with pytest.raises(InvalidInput, match="product"):
        await add_wallet(uow(), alice, "Long", "card", product="x" * 61)
    with pytest.raises(InvalidInput, match="for cards"):
        await add_wallet(uow(), alice, "Rainy Day", "savings", last4="1234")


async def test_card_details_can_be_changed_and_cleared_and_go_when_it_stops_being_a_card(
    uow: UowFactory, alice: UserId
) -> None:
    citi = (await cards(uow, alice))["Citi PremierMiles"]
    changed = await update_wallet(uow(), alice, citi.id, product="Prestige", last4="9999")
    assert (changed.issuer, changed.product, changed.last4) == ("Citi", "Prestige", "9999")
    cleared = await update_wallet(uow(), alice, citi.id, network=None, last4=None)
    assert (cleared.network, cleared.last4, cleared.issuer) == (None, None, "Citi")
    same = await update_wallet(uow(), alice, citi.id, name="My Citi")  # untouched fields stay
    assert (same.issuer, same.product) == ("Citi", "Prestige")

    other = await update_wallet(uow(), alice, citi.id, kind="other")
    assert (other.issuer, other.product, other.network, other.last4) == (None,) * 4
    with pytest.raises(InvalidInput, match="for cards"):
        await update_wallet(uow(), alice, citi.id, last4="1234")


# --- Cash --------------------------------------------------------------------------------


async def test_everyone_has_a_cash_wallet_that_can_be_renamed_but_not_deleted_or_doubled(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    for user in (alice, bob):
        found = await wallets_by_name(uow, user)
        assert found["Cash"].kind is WalletKind.CASH
    cash = (await wallets_by_name(uow, alice))["Cash"]
    assert cash.id != (await wallets_by_name(uow, bob))["Cash"].id

    with pytest.raises(InvalidInput, match="Cash wallet can't be deleted"):
        await wallet_cases.delete_wallet(uow(), alice, cash.id)
    with pytest.raises(InvalidInput, match="Cash wallet can't be deleted"):
        await wallet_cases.preview_delete_wallet(uow(), alice, cash.id)
    with pytest.raises(InvalidInput, match="Cash wallet already"):
        await add_wallet(uow(), alice, "Pocket money", "cash")
    with pytest.raises(InvalidInput, match="can't change kind"):
        await update_wallet(uow(), alice, cash.id, kind="other")
    renamed = await wallet_cases.rename_wallet(uow(), alice, cash.id, "Wallet cash")
    assert renamed.kind is WalletKind.CASH and renamed.name == "Wallet cash"


async def test_the_migration_gives_existing_users_a_cash_wallet(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0064")
    engine = make_engine(empty_database_url)
    ann, ben, cy = uuid4(), uuid4(), uuid4()
    try:
        async with engine.begin() as db:
            for n, user in enumerate((ann, ben, cy)):
                await db.execute(
                    text(
                        "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, "
                        "home_currency, role) VALUES (:id, :tg, 'UTC', 'UTC', 'SGD', 'owner')"
                    ),
                    {"id": user, "tg": 900 + n},
                )
                await db.execute(
                    text(
                        "INSERT INTO wallets (id, user_id, name, kind) "
                        "VALUES (gen_random_uuid(), :u, 'Spending', 'spending')"
                    ),
                    {"u": user},
                )
            # Ben already has a wallet called cash (left as "other"); Cy has a savings one.
            await db.execute(
                text(
                    "INSERT INTO wallets (id, user_id, name, kind) VALUES "
                    "(gen_random_uuid(), :b, 'cash', 'other'), "
                    "(gen_random_uuid(), :c, 'Cash', 'savings')"
                ),
                {"b": ben, "c": cy},
            )
        await upgrade(empty_database_url, "0065")
        async with engine.connect() as db:
            rows = (
                await db.execute(
                    text("SELECT user_id, name, kind FROM wallets WHERE kind = 'cash'")
                )
            ).all()
        assert sorted((r.user_id, r.name) for r in rows) == sorted(
            [(ann, "Cash"), (ben, "cash"), (cy, "Cash wallet")]
        )

        # Down again: Cash wallets become plain "other" ones (their moves stay), the new columns
        # go; and up once more gives the same.
        await downgrade(empty_database_url, "0064")
        async with engine.connect() as db:
            kinds = (await db.execute(text("SELECT name, kind FROM wallets"))).all()
            columns: int = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE "
                        "column_name IN ('last4', 'paid_with_wallet_id', 'usual_card_wallet_id')"
                    )
                )
            ).scalar_one()
        assert columns == 0 and "cash" not in {k.kind for k in kinds}
        await upgrade(empty_database_url, "0065")
        async with engine.connect() as db:
            again = (
                await db.execute(text("SELECT user_id, name FROM wallets WHERE kind = 'cash'"))
            ).all()
        assert sorted((r.user_id, r.name) for r in again) == sorted(
            (r.user_id, r.name) for r in rows
        )
    finally:
        await engine.dispose()


# --- paid with: creating, editing, clearing ----------------------------------------------


async def test_an_expense_can_be_paid_with_a_wallet_and_it_can_change_or_clear(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    citi, dbs = found["Citi PremierMiles"], found["DBS Altitude"]
    tx = await expense(uow, alice, paid_with_wallet_id=citi.id)
    assert tx.paid_with_wallet_id == citi.id
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == citi.id

    moved = await edit_transaction(
        uow(), alice, tx.id, TransactionChanges(paid_with_wallet_id=dbs.id)
    )
    assert moved.paid_with_wallet_id == dbs.id
    kept = await edit_transaction(uow(), alice, tx.id, TransactionChanges(notes="with Ann"))
    assert kept.paid_with_wallet_id == dbs.id  # left out: unchanged
    cleared = await edit_transaction(
        uow(), alice, tx.id, TransactionChanges(paid_with_wallet_id=None)
    )
    assert cleared.paid_with_wallet_id is None

    # Undo walks back through the edits.
    await undo_last(uow(), alice)  # the clear
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == dbs.id


async def test_any_wallet_that_can_pay_is_accepted_and_others_are_not(
    uow: UowFactory, alice: UserId
) -> None:
    found = await wallets_by_name(uow, alice)
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    broker = await add_wallet(uow(), alice, "Brokerage", "investment")
    misc = await add_wallet(uow(), alice, "Gift card", "other")
    for ok in (found["Spending"], found["Cash"], misc):
        tx = await expense(uow, alice, paid_with_wallet_id=ok.id)
        assert tx.paid_with_wallet_id == ok.id
    for bad in (saver, broker):
        with pytest.raises(InvalidInput, match="can't pay"):
            await expense(uow, alice, paid_with_wallet_id=bad.id)
    with pytest.raises(NotFound):
        await expense(uow, alice, paid_with_wallet_id=uuid4())


async def test_a_wallet_of_another_user_is_refused(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    theirs = (await cards(uow, bob))["Citi PremierMiles"]
    with pytest.raises(NotFound):
        await expense(uow, alice, paid_with_wallet_id=theirs.id)
    mine = await expense(uow, alice)
    with pytest.raises(NotFound):
        await edit_transaction(
            uow(), alice, mine.id, TransactionChanges(paid_with_wallet_id=theirs.id)
        )
    with pytest.raises(InvalidInput, match="isn't one of your wallets"):
        await wallet_cases.set_usual_card(uow(), alice, theirs.id)


async def test_only_money_out_is_paid_with_something(uow: UowFactory, alice: UserId) -> None:
    citi = (await cards(uow, alice))["Citi PremierMiles"]
    with pytest.raises(InvalidInput, match="only money out"):
        await log_transaction(
            uow(), alice, NewTransaction(Direction.IN, sgd("5"), NOW, paid_with_wallet_id=citi.id)
        )
    tx = await expense(uow, alice, paid_with_wallet_id=citi.id)
    with pytest.raises(InvalidInput, match="only money out"):
        await edit_transaction(
            uow(),
            alice,
            tx.id,
            TransactionChanges(direction=Direction.IN, paid_with_wallet_id=citi.id),
        )
    # Turning money out into money in drops it.
    turned = await edit_transaction(uow(), alice, tx.id, TransactionChanges(direction=Direction.IN))
    assert turned.paid_with_wallet_id is None
    await undo_last(uow(), alice)
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == citi.id

    # Marking it as a move drops it too, and undo brings it back.
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    as_move = await wallet_cases.mark_as_move(uow(), alice, tx.id, saver.id)
    assert as_move.paid_with_wallet_id is None
    await undo_last(uow(), alice)
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == citi.id


async def test_the_database_refuses_a_card_on_money_in_or_a_move(
    engine: AsyncEngine, uow: UowFactory, alice: UserId
) -> None:
    citi = (await cards(uow, alice))["Citi PremierMiles"]
    spending = (await wallets_by_name(uow, alice))["Spending"]
    row = {
        "user": alice, "amount": 5, "at": NOW, "paid": citi.id, "spending": spending.id,
    }  # fmt: skip

    async def insert(direction: str, extra_cols: str = "", extra_vals: str = "") -> None:
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO transactions (id, user_id, direction, amount, currency, "  # noqa: S608
                    "occurred_at, status, source, created_at, updated_at, "
                    f"paid_with_wallet_id{extra_cols}) "
                    f"VALUES (gen_random_uuid(), :user, '{direction}', :amount, 'SGD', :at, "
                    f"'confirmed', 'manual', :at, :at, :paid{extra_vals})"
                ),
                row,
            )

    await insert("out")  # money out is fine
    with pytest.raises(IntegrityError, match="paid_with_out"):
        await insert("in")
    with pytest.raises(IntegrityError, match="paid_with_out"):
        await insert("move", ", from_wallet_id, to_wallet_id", ", :spending, :paid")


async def test_deleting_a_card_clears_it_from_expenses_and_as_the_usual_card(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    citi, dbs = found["Citi PremierMiles"], found["DBS Altitude"]
    tx = await expense(uow, alice, paid_with_wallet_id=citi.id)
    await wallet_cases.set_usual_card(uow(), alice, citi.id)

    await wallet_cases.delete_wallet(uow(), alice, citi.id)
    after = await get_transaction(uow(), alice, tx.id)
    assert after.paid_with_wallet_id is None and after.user_id == alice  # only that column
    assert after.amount == tx.amount
    assert (await get_user(uow(), alice)).usual_card_wallet_id is None

    # An edit being undone doesn't bring back a card that is gone.
    await edit_transaction(uow(), alice, tx.id, TransactionChanges(paid_with_wallet_id=dbs.id))
    await edit_transaction(uow(), alice, tx.id, TransactionChanges(notes="x"))
    await wallet_cases.delete_wallet(uow(), alice, dbs.id)
    await undo_last(uow(), alice)
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id is None


# --- the usual card ------------------------------------------------------------------------


async def test_the_usual_card_is_used_only_where_the_user_enters_the_expense_themselves(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    citi, dbs = found["Citi PremierMiles"], found["DBS Altitude"]
    assert (await expense(uow, alice, use_usual_card=True)).paid_with_wallet_id is None  # none set

    await wallet_cases.set_usual_card(uow(), alice, citi.id)
    assert (await get_user(uow(), alice)).usual_card_wallet_id == citi.id
    used = await expense(uow, alice, use_usual_card=True)
    assert used.paid_with_wallet_id == citi.id
    said = await expense(uow, alice, use_usual_card=True, paid_with_wallet_id=dbs.id)
    assert said.paid_with_wallet_id == dbs.id  # what was said wins
    assert (await expense(uow, alice)).paid_with_wallet_id is None  # not asked: an import, say
    income = await log_transaction(
        uow(), alice, NewTransaction(Direction.IN, sgd("9"), NOW, use_usual_card=True)
    )
    assert income.paid_with_wallet_id is None

    await wallet_cases.set_usual_card(uow(), alice, None)
    assert (await expense(uow, alice, use_usual_card=True)).paid_with_wallet_id is None


async def test_only_a_wallet_that_can_pay_can_be_the_usual_card(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    for bad in (saver.id, uuid4()):
        with pytest.raises(InvalidInput):
            await wallet_cases.set_usual_card(uow(), alice, bad)
    await wallet_cases.set_usual_card(uow(), alice, found["Cash"].id)
    assert (await get_user(uow(), alice)).usual_card_wallet_id == found["Cash"].id

    # A card that becomes a savings wallet is no longer the usual one.
    other = await add_wallet(uow(), alice, "Spare", "card")
    await wallet_cases.set_usual_card(uow(), alice, other.id)
    await update_wallet(uow(), alice, other.id, kind="savings")
    assert (await get_user(uow(), alice)).usual_card_wallet_id is None


# --- the ledger filter ---------------------------------------------------------------------


async def test_the_ledger_lists_by_what_paid(uow: UowFactory, alice: UserId) -> None:
    found = await cards(uow, alice)
    citi, dbs = found["Citi PremierMiles"], found["DBS Altitude"]
    a = await expense(uow, alice, "1", paid_with_wallet_id=citi.id)
    b = await expense(uow, alice, "2", paid_with_wallet_id=dbs.id)
    c = await expense(uow, alice, "3")
    await log_transaction(uow(), alice, NewTransaction(Direction.IN, sgd("4"), NOW))

    async def ids(**query: Any) -> set[UUID]:
        page = await list_ledger(uow(), alice, LedgerQuery(**query))
        return {t.id for t in page.items}

    assert await ids(paid_with_wallet_id=citi.id) == {a.id}
    assert await ids(paid_with_wallet_id=dbs.id) == {b.id}
    assert await ids(without_paid_with=True) == {c.id}  # expenses only, not the income


# --- the API ------------------------------------------------------------------------------


async def add_card(browser: Browser, name: str, **extra: Any) -> dict[str, Any]:
    made = await browser.send("POST", "/api/wallets", {"name": name, "kind": "card", **extra})
    assert made.status_code == 201, made.text
    created: dict[str, Any] = made.json()
    return created


async def put_on(
    browser: Browser, amount: str, day: str = DAY, currency: str | None = None, **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {"direction": "out", "amount": amount, "date": day, **extra}
    if currency:
        body["currency"] = currency
    made = await browser.send("POST", "/api/transactions", body)
    assert made.status_code == 201, made.text
    created: dict[str, Any] = made.json()
    return created


async def test_wallets_carry_card_details_and_say_when_digits_were_dropped(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    citi = await add_card(
        owner, "Citi PremierMiles", issuer="Citi", product="PremierMiles", network="visa",
        last4="4321",
    )  # fmt: skip
    assert (citi["issuer"], citi["product"], citi["network"], citi["last4"]) == (
        "Citi", "PremierMiles", "visa", "4321",
    )  # fmt: skip
    assert citi["usual"] is False and "note" not in citi  # nothing was dropped

    long = await add_card(owner, "Old card", last4="1357 2468 1357 9876")
    assert long["last4"] == "9876" and long["note"] == "Only the last 4 digits are kept."
    assert "1357" not in str(long)

    bad = await owner.send("POST", "/api/wallets", {"name": "Odd", "kind": "card", "last4": "12x4"})
    assert bad.status_code == 422
    plain = await owner.send(
        "POST", "/api/wallets", {"name": "Rainy", "kind": "savings", "issuer": "Citi"}
    )
    assert plain.status_code == 422

    patched = await owner.send(
        "PATCH", f"/api/wallets/{citi['id']}", {"product": "Prestige", "last4": "5555 6666"}
    )
    assert patched.status_code == 200
    assert (patched.json()["product"], patched.json()["last4"]) == ("Prestige", "6666")
    assert patched.json()["note"] == "Only the last 4 digits are kept."
    cleared = await owner.send("PATCH", f"/api/wallets/{citi['id']}", {"network": None})
    assert cleared.json()["network"] is None and cleared.json()["product"] == "Prestige"
    assert "note" not in cleared.json()

    listed = {w["name"]: w for w in (await owner.get("/api/wallets")).json()}
    assert listed["Cash"]["kind"] == "cash" and listed["Cash"]["last4"] is None
    assert listed["Old card"]["last4"] == "9876"


async def test_cash_cannot_be_deleted_over_the_api(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    cash = next(w for w in (await owner.get("/api/wallets")).json() if w["kind"] == "cash")
    assert (await owner.send("DELETE", f"/api/wallets/{cash['id']}")).status_code == 422
    renamed = await owner.send("PATCH", f"/api/wallets/{cash['id']}", {"name": "Coins"})
    assert renamed.status_code == 200 and renamed.json()["kind"] == "cash"


async def test_a_transaction_can_be_paid_with_a_card_set_changed_and_cleared(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    citi = await add_card(owner, "Citi PremierMiles", last4="4321")
    dbs = await add_card(owner, "DBS Altitude", last4="8765")

    made = await put_on(owner, "12.50", paid_with_wallet_id=citi["id"])
    assert made["paid_with"] == {
        "id": citi["id"], "name": "Citi PremierMiles", "kind": "card", "last4": "4321",
    }  # fmt: skip
    plain = await put_on(owner, "3")
    assert plain["paid_with"] is None

    url = f"/api/transactions/{made['id']}"
    moved = await owner.send("PATCH", url, {"paid_with_wallet_id": dbs["id"]})
    assert moved.status_code == 200 and moved.json()["paid_with"]["name"] == "DBS Altitude"
    kept = await owner.send("PATCH", url, {"notes": "lunch"})
    assert kept.json()["paid_with"]["id"] == dbs["id"]  # left out: unchanged
    cleared = await owner.send("PATCH", url, {"paid_with_wallet_id": None})
    assert cleared.json()["paid_with"] is None
    assert (await owner.get(url)).json()["paid_with"] is None

    got = await owner.send("PATCH", url, {"paid_with_wallet_id": citi["id"]})
    assert (await owner.get(url)).json()["paid_with"]["id"] == got.json()["paid_with"]["id"]
    listing = (await owner.get("/api/transactions")).json()["items"]
    assert {t["id"]: (t["paid_with"] or {}).get("name") for t in listing} == {
        made["id"]: "Citi PremierMiles",
        plain["id"]: None,
    }

    income = await owner.send(
        "POST",
        "/api/transactions",
        {"direction": "in", "amount": "9", "date": DAY, "paid_with_wallet_id": citi["id"]},
    )
    assert income.status_code == 422
    missing = await owner.send(
        "POST",
        "/api/transactions",
        {"direction": "out", "amount": "9", "paid_with_wallet_id": str(uuid4())},
    )
    assert missing.status_code == 404


async def track_cards(browser: Browser, on: bool = True) -> None:
    done = await browser.send("PUT", "/api/settings/preferences", {"track_cards": on})
    assert done.status_code == 200 and done.json() == {"track_cards": on}


async def test_the_usual_card_is_used_for_a_new_expense_unless_one_is_said(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await track_cards(owner)
    citi = await add_card(owner, "Citi PremierMiles")
    dbs = await add_card(owner, "DBS Altitude")
    saver = (
        await owner.send("POST", "/api/wallets", {"name": "Rainy Day", "kind": "savings"})
    ).json()

    assert (
        await owner.send("PUT", "/api/wallets/usual-card", {"wallet_id": citi["id"]})
    ).status_code == 204
    listed = {w["name"]: w["usual"] for w in (await owner.get("/api/wallets")).json()}
    assert listed["Citi PremierMiles"] is True and listed["DBS Altitude"] is False

    assert (await put_on(owner, "5"))["paid_with"]["name"] == "Citi PremierMiles"  # not said
    assert (await put_on(owner, "5", paid_with_wallet_id=dbs["id"]))["paid_with"]["name"] == (
        "DBS Altitude"
    )
    assert (await put_on(owner, "5", paid_with_wallet_id=None))["paid_with"] is None  # said: none
    income = await owner.send(
        "POST", "/api/transactions", {"direction": "in", "amount": "50", "date": DAY}
    )
    assert income.status_code == 201 and income.json()["paid_with"] is None

    # Refused: a savings wallet, a wallet that isn't theirs.
    for bad in (saver["id"], str(uuid4())):
        refused = await owner.send("PUT", "/api/wallets/usual-card", {"wallet_id": bad})
        assert refused.status_code == 422, refused.text

    assert (
        await owner.send("PUT", "/api/wallets/usual-card", {"wallet_id": None})
    ).status_code == 204
    assert (await put_on(owner, "5"))["paid_with"] is None
    assert all(not w["usual"] for w in (await owner.get("/api/wallets")).json())


async def test_the_ledger_filters_by_what_paid_over_the_api(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    citi = await add_card(owner, "Citi PremierMiles", last4="4321")
    a = await put_on(owner, "1", paid_with_wallet_id=citi["id"])
    b = await put_on(owner, "2")
    income = await owner.send(
        "POST", "/api/transactions", {"direction": "in", "amount": "3", "date": DAY}
    )

    async def ids(paid_with: str) -> set[str]:
        found = await owner.get("/api/transactions", params={"paid_with": paid_with})
        assert found.status_code == 200, found.text
        return {t["id"] for t in found.json()["items"]}

    assert await ids(citi["id"]) == {a["id"]}
    assert await ids("none") == {b["id"]}  # expenses with nothing; not the income
    assert income.json()["id"] not in await ids("none")
    assert (await owner.get("/api/transactions", params={"paid_with": "soon"})).status_code == 422
    csv = await owner.get("/api/export.csv", params={"paid_with": citi["id"]})
    assert csv.status_code == 200
    header, row = csv.text.strip().split("\r\n")  # only the one paid with it
    assert header.endswith(",to_wallet,paid_with") and row.endswith(",Citi PremierMiles ··4321")
    nothing = await owner.get("/api/export.csv", params={"paid_with": "none"})
    [_, plain] = nothing.text.strip().split("\r\n")
    assert plain.endswith(",,") and "Citi" not in plain  # blank wallets and paid_with
    assert (await owner.get("/api/export.csv", params={"paid_with": "x"})).status_code == 422


async def test_a_wallets_spend_for_a_month_is_in_the_home_currency(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    citi = await add_card(owner, "Citi PremierMiles")
    dbs = await add_card(owner, "DBS Altitude")
    me = {"paid_with_wallet_id": citi["id"]}
    await put_on(owner, "10", "2026-09-27", **me)
    await put_on(owner, "20", "2026-09-25", "USD", **me)  # 20 x 1.2905 = 25.81
    await put_on(owner, "5000", "2026-09-25", "JPY", **me)  # no rate: left out, not guessed
    await put_on(owner, "7", "2026-08-31", **me)
    await put_on(owner, "99", "2026-09-26", paid_with_wallet_id=dbs["id"])  # another card
    await put_on(owner, "98", "2026-09-26")  # no card
    pending = await put_on(owner, "40", "2026-09-26", **me)
    await owner.send("PATCH", f"/api/transactions/{pending['id']}", {"status": "pending"})
    gone = await put_on(owner, "41", "2026-09-26", **me)
    await owner.send("DELETE", f"/api/transactions/{gone['id']}")

    this = await owner.get(f"/api/wallets/{citi['id']}/spend")  # this month by default
    assert this.status_code == 200, this.text
    assert this.json() == {
        "month": "2026-09", "total": {"amount": "35.8100", "currency": "SGD"}, "count": 2,
    }  # fmt: skip
    august = await owner.get(f"/api/wallets/{citi['id']}/spend", params={"month": "2026-08"})
    assert august.json() == {
        "month": "2026-08", "total": {"amount": "7.0000", "currency": "SGD"}, "count": 1,
    }  # fmt: skip
    none = await owner.get(f"/api/wallets/{dbs['id']}/spend", params={"month": "2026-07"})
    assert none.json()["total"]["amount"] == "0.0000" and none.json()["count"] == 0

    for bad in ("2026-10", "2027-01", "2026-13", "september", "2026-9", "2026-09-01"):
        refused = await owner.get(f"/api/wallets/{citi['id']}/spend", params={"month": bad})
        assert refused.status_code == 422, bad
    assert (await owner.get(f"/api/wallets/{uuid4()}/spend")).status_code == 404


async def test_another_users_wallet_is_not_theirs_over_the_api(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    invite = (await owner.send("POST", "/api/invites")).json()["url"].rsplit("/", 1)[-1]
    member = world.browser()
    await member.login(test_web_api.MEMBER, invite=invite)
    mine = await add_card(member, "Member card")
    theirs = await add_card(owner, "Owner card")

    refused = await member.send(
        "POST",
        "/api/transactions",
        {"direction": "out", "amount": "5", "date": DAY, "paid_with_wallet_id": theirs["id"]},
    )
    assert refused.status_code == 404
    assert (await member.get(f"/api/wallets/{theirs['id']}/spend")).status_code == 404
    assert (
        await member.send("PUT", "/api/wallets/usual-card", {"wallet_id": theirs["id"]})
    ).status_code == 422
    ok = await member.send(
        "POST",
        "/api/transactions",
        {"direction": "out", "amount": "5", "date": DAY, "paid_with_wallet_id": mine["id"]},
    )
    assert ok.status_code == 201
    # The owner sees none of it.
    assert (await owner.get("/api/transactions", params={"paid_with": mine["id"]})).json()[
        "total"
    ] == 0


# --- a statement import ---------------------------------------------------------------------

STATEMENT = """Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1
28 Sep 2026,POS,4.20,,KOPITIAM
27 Sep 2026,POS,42.10,,GRAB
25 Sep 2026,ICT,,"5,000.00",ACME PTE LTD
"""


async def test_every_expense_of_an_import_gets_the_chosen_card_and_nothing_else_does(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    citi, dbs = found["Citi PremierMiles"], found["DBS Altitude"]
    await wallet_cases.set_usual_card(uow(), alice, citi.id)  # an import ignores the usual card
    user = await get_user(uow(), alice)
    shown = await statement_cases.preview(uow, user, STATEMENT)
    assert shown.mapping is not None
    rows = {p.row.index for p in shown.rows}

    plain = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {0}, file_name="a.csv", now=NOW
    )
    [first] = plain.record.transaction_ids
    assert (await get_transaction(uow(), alice, first)).paid_with_wallet_id is None

    done = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, rows, file_name="b.csv", paid_with=dbs.id, now=NOW
    )
    page = await list_ledger(uow(), alice, LedgerQuery(limit=50))
    by_id = {t.id: t for t in page.items}
    paid = [by_id[i] for i in done.record.transaction_ids]
    assert len(paid) == 2  # row 0 was imported already
    for tx in paid:
        expected = dbs.id if tx.direction is Direction.OUT else None
        assert tx.paid_with_wallet_id == expected

    saver = await add_wallet(uow(), alice, "Rainy Day", "savings")
    with pytest.raises(InvalidInput, match="can't pay"):
        await statement_cases.confirm(
            uow,
            user,
            STATEMENT,
            shown.mapping,
            rows,
            file_name="c.csv",
            paid_with=saver.id,
            now=NOW,
        )
    with pytest.raises(NotFound):
        await statement_cases.confirm(
            uow, user, STATEMENT, shown.mapping, rows, file_name="c.csv", paid_with=uuid4(), now=NOW
        )


async def test_the_import_api_takes_the_card(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await track_cards(owner)
    citi = await add_card(owner, "Citi PremierMiles")
    layout = {"date": 0, "description": [1, 4], "debit": 2, "credit": 3}
    body = {
        "csv": STATEMENT,
        "layout": layout,
        "include": [0, 1, 2],
        "file_name": "sept.csv",
        "paid_with_wallet_id": citi["id"],
    }
    sent = await owner.send("POST", "/api/imports", body)
    assert sent.status_code == 201, sent.text
    found = (await owner.get("/api/transactions", params={"paid_with": citi["id"]})).json()
    assert found["total"] == 2 and {t["direction"] for t in found["items"]} == {"out"}


# --- emails ------------------------------------------------------------------------------


async def test_an_email_that_names_a_card_is_logged_as_paid_with_it(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    found = await cards(uow, user.id)
    citi = found["Citi PremierMiles"]
    await add_wallet(uow(), user.id, "Citi Rewards", "card", last4="4321")  # the same digits twice
    grab = "Merchant: Grab\nTotal: 18.50\nCurrency: SGD\nDate: 2026-09-27"
    mailbox = FakeMailbox(
        {
            "m1": fake_email("m1", "Grab receipt", f"{grab}\nPaid with card ending 8765"),
            "m2": fake_email("m2", "Grab receipt", f"{grab}\nTotal paid with xxxx-1111\nExtra: 1"),
            "m3": fake_email("m3", "Grab receipt", f"{grab}\nCard: **** 4321"),
            "m4": fake_email("m4", "Grab receipt", grab),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    inbox = {
        e.provider_message_id: e
        for e in (await email_cases.overview(uow(), user.id, now=NOW)).emails
    }
    assert inbox["m1"].draft is not None and inbox["m1"].draft["card_last4"] == "8765"
    assert "card_last4" not in (inbox["m4"].draft or {})

    async def paid(message: str) -> UUID | None:
        tx = await email_cases.log_email(uow, user, inbox[message].id, now=NOW)
        return tx.paid_with_wallet_id

    assert await paid("m1") == found["DBS Altitude"].id
    assert await paid("m2") is None  # no such card
    assert await paid("m3") is None  # two cards end 4321: not guessed
    assert await paid("m4") is None
    assert citi.id != found["DBS Altitude"].id


async def test_the_usual_card_is_not_applied_to_an_email(uow: UowFactory) -> None:
    user = await person(uow)
    citi = (await cards(uow, user.id))["Citi PremierMiles"]
    await wallet_cases.set_usual_card(uow(), user.id, citi.id)
    mailbox = FakeMailbox(
        {"m1": fake_email("m1", "Grab receipt", "Merchant: Grab\nTotal: 18.50\nCurrency: SGD")}
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    [email] = (await email_cases.overview(uow(), user.id, now=NOW)).emails
    assert (await email_cases.log_email(uow, user, email.id, now=NOW)).paid_with_wallet_id is None


async def test_money_received_by_email_is_never_paid_with_a_card(uow: UowFactory) -> None:
    user = await person(uow)
    await cards(uow, user.id)
    text_ = "From: Ann\nTotal: 50.00\nCurrency: SGD\nCard ending 4321"
    mailbox = FakeMailbox({"m1": fake_email("m1", "Transfer received", text_)})
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    [email] = (await email_cases.overview(uow(), user.id, now=NOW)).emails
    tx = await email_cases.log_email(uow, user, email.id, now=NOW)
    assert tx.direction is Direction.IN and tx.paid_with_wallet_id is None


# --- picking the wallet someone means --------------------------------------------------------


# --- the chat tools ----------------------------------------------------------------------------


async def test_log_expense_takes_the_card_the_user_names(uow: UowFactory, alice: UserId) -> None:
    found = await cards(uow, alice)
    result = await run(
        uow, alice, "log_expense",
        {"amount": "12.50", "merchant": "Kopi Corner", "paid_with": "my citi card"},
    )  # fmt: skip
    assert "paid with Citi PremierMiles" in result and "usual card" not in result
    page = await list_ledger(uow(), alice, LedgerQuery())
    assert [t.paid_with_wallet_id for t in page.items] == [found["Citi PremierMiles"].id]

    cash = await run(uow, alice, "log_expense", {"amount": "3", "paid_with": "cash"})
    assert "paid with Cash" in cash
    by_digits = await run(uow, alice, "log_expense", {"amount": "4", "paid_with": "ending 8765"})
    assert "paid with DBS Altitude" in by_digits


async def test_an_unknown_or_ambiguous_card_is_asked_about_and_nothing_is_logged(
    uow: UowFactory, alice: UserId
) -> None:
    await cards(uow, alice)
    await add_wallet(uow(), alice, "Citi Rewards", "card", issuer="Citi")
    model = scripted(
        call("log_expense", amount="30", merchant="Grab", paid_with="Amex"),
        say("I don't have an Amex card. Want me to add it as a card?"),
    )
    reply = await build(uow, model).handle_text(alice, "paid 30 for grab with amex", "tg:1:1")
    assert reply[0].text.endswith("add it as a card?")
    [result] = tool_results(model)
    assert result.startswith("Error: No card called 'Amex'. Add it as a card?")
    assert "Citi PremierMiles" in result and "don't log the expense or add a card" in result
    assert (await list_ledger(uow(), alice, LedgerQuery())).total == 0
    assert set(await wallets_by_name(uow, alice)) == {
        "Spending", "Cash", "Citi PremierMiles", "DBS Altitude", "Citi Rewards",
    }  # fmt: skip

    ambiguous = await run(uow, alice, "log_expense", {"amount": "30", "paid_with": "citi"})
    assert ambiguous.startswith("Error: 'citi' could be ")
    assert "Citi PremierMiles" in ambiguous and "Citi Rewards" in ambiguous
    assert (await list_ledger(uow(), alice, LedgerQuery())).total == 0


async def test_log_expense_uses_the_usual_card_and_says_so(uow: UowFactory, alice: UserId) -> None:
    found = await cards(uow, alice)
    set_it = await run(uow, alice, "set_usual_card", {"wallet": "citi"})
    assert set_it.startswith("Citi PremierMiles is now the usual card")
    assert (await get_user(uow(), alice)).usual_card_wallet_id == found["Citi PremierMiles"].id

    result = await run(uow, alice, "log_expense", {"amount": "6", "merchant": "Toast Box"})
    assert "paid with Citi PremierMiles" in result and "usual card" in result
    said = await run(uow, alice, "log_expense", {"amount": "7", "paid_with": "dbs"})
    assert "paid with DBS Altitude" in said and "usual card" not in said

    assert "No usual card" in await run(uow, alice, "set_usual_card", {"wallet": "none"})
    assert (await get_user(uow(), alice)).usual_card_wallet_id is None
    plain = await run(uow, alice, "log_expense", {"amount": "8"})
    assert "paid with" not in plain

    unknown = await run(uow, alice, "set_usual_card", {"wallet": "amex"})
    assert unknown.startswith("Error: No card called 'amex'")
    await run(uow, alice, "set_usual_card", {"wallet": "dbs"})
    listed = await run(uow, alice, "list_wallets", {})
    assert "DBS Altitude (card; DBS Altitude, mastercard, ending 8765; the usual card)" in listed


async def test_a_photo_receipt_uses_the_usual_card(uow: UowFactory, alice: UserId) -> None:
    found = await cards(uow, alice)
    first = await run(
        uow, alice, "log_receipt_expense",
        {"amount": "8.40", "merchant": "Ya Kun", "external_id": "photo-1"},
    )  # fmt: skip
    assert "paid with" not in first
    await wallet_cases.set_usual_card(uow(), alice, found["DBS Altitude"].id)
    second = await run(
        uow, alice, "log_receipt_expense",
        {"amount": "9.40", "merchant": "Ya Kun", "external_id": "photo-2"},
    )  # fmt: skip
    assert "paid with DBS Altitude" in second


async def test_edit_transaction_changes_and_clears_the_card(uow: UowFactory, alice: UserId) -> None:
    found = await cards(uow, alice)
    tx = await expense(uow, alice, paid_with_wallet_id=found["Citi PremierMiles"].id)

    on_dbs = await run(
        uow, alice, "edit_transaction", {"transaction_id": str(tx.id), "paid_with": "my DBS card"}
    )
    assert on_dbs.startswith("Updated: ") and "paid with DBS Altitude" in on_dbs
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == found[
        "DBS Altitude"
    ].id

    unknown = await run(
        uow, alice, "edit_transaction", {"transaction_id": str(tx.id), "paid_with": "amex"}
    )
    assert unknown.startswith("Error: No card called 'amex'")
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == found[
        "DBS Altitude"
    ].id

    none = await run(
        uow, alice, "edit_transaction", {"transaction_id": str(tx.id), "paid_with": "none"}
    )
    assert "paid with" not in none
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id is None

    income = await log_transaction(uow(), alice, NewTransaction(Direction.IN, sgd("5"), NOW))
    refused = await run(
        uow, alice, "edit_transaction", {"transaction_id": str(income.id), "paid_with": "cash"}
    )
    assert refused.startswith("Error: only money out")


async def test_edit_transaction_asks_to_confirm_and_names_the_card(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    tx = await expense(uow, alice)
    model = scripted(
        call("edit_transaction", transaction_id=str(tx.id), paid_with="dbs"), say("Done.")
    )
    agent = build(uow, model)
    [ask] = await agent.handle_text(alice, "that last one was on my DBS card", "tg:1:1")
    assert "paid with → dbs" in ask.text
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == found[
        "DBS Altitude"
    ].id


async def test_the_wallet_tools_add_and_change_a_card_and_never_keep_more_than_four_digits(
    uow: UowFactory, alice: UserId
) -> None:
    added = await run(
        uow, alice, "add_wallet",
        {"name": "Citi PremierMiles", "kind": "card", "issuer": "Citi", "product": "PremierMiles",
         "network": "visa", "last4": "1234"},
    )  # fmt: skip
    assert added == (
        "Added the wallet Citi PremierMiles (card; Citi PremierMiles, visa, ending 1234)."
    )

    long = await run(
        uow, alice, "add_wallet", {"name": "Old card", "kind": "card", "last4": "1357246813579876"}
    )
    assert "ending 9876" in long and "Only the last 4 digits are kept." in long
    assert "1357" not in long
    found = await wallets_by_name(uow, alice)
    assert found["Old card"].last4 == "9876"

    bad = await run(uow, alice, "add_wallet", {"name": "Odd", "kind": "card", "last4": "12ab"})
    assert bad.startswith("Error:") and "numbers only" in bad
    assert "Odd" not in await wallets_by_name(uow, alice)

    updated = await run(
        uow, alice, "update_wallet", {"wallet": "Old card", "issuer": "DBS", "last4": "5678"}
    )
    assert "card; DBS, ending 5678" in updated
    listed = await run(uow, alice, "list_wallets", {})
    assert "Citi PremierMiles (card; Citi PremierMiles, visa, ending 1234)" in listed
    assert "Cash (cash)" in listed


async def test_nothing_but_four_digits_is_in_the_database(
    engine: AsyncEngine, uow: UowFactory, alice: UserId
) -> None:
    await add_wallet(uow(), alice, "Old card", "card", last4="1357 2468 1357 9876")
    async with engine.connect() as db:
        stored = (await db.execute(text("SELECT last4 FROM wallets WHERE last4 IS NOT NULL"))).all()
    assert [r.last4 for r in stored] == ["9876"]
    with pytest.raises(IntegrityError, match="last4"):
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE wallets SET last4 = '1357246813579876' WHERE name = 'Old card'")
            )


async def test_money_totals_ignore_what_paid(uow: UowFactory, alice: UserId) -> None:
    from nexus.application.transactions import summarize

    citi = (await cards(uow, alice))["Citi PremierMiles"]
    await expense(uow, alice, "10", paid_with_wallet_id=citi.id)
    await expense(uow, alice, "5")
    now = datetime(2026, 9, 1, tzinfo=NOW.tzinfo)
    summary = await summarize(uow(), alice, now, NOW + timedelta(days=1))
    [out] = [t for t in summary.totals if t.direction is Direction.OUT]
    assert (out.total.amount, out.count) == (Decimal("15"), 2)
