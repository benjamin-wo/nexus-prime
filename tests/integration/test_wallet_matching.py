"""Recognising moves by a wallet's match words: statement imports propose them, emails ask
about them, past entries are listed as likely ones, and the chat can list those. Nothing is
ever turned into a move without the user. Every name and figure here is made up."""

from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import email as email_cases
from nexus.application import statements as statement_cases
from nexus.application import wallets as wallet_cases
from nexus.application.notifications import set_frequency
from nexus.application.ports import LedgerQuery
from nexus.application.statements import Verdict
from nexus.application.transactions import (
    NewTransaction,
    delete_transaction,
    get_transaction,
    list_ledger,
    log_transaction,
)
from nexus.application.users import get_user
from nexus.application.wallets import add_wallet, list_wallets, log_move
from nexus.domain.email import external_id
from nexus.domain.errors import Conflict, DuplicateSource, InvalidInput, NotFound
from nexus.domain.ledger import Direction, Source, Transaction, User, UserId, Wallet
from nexus.domain.money import Money
from nexus.domain.notifications import Frequency
from nexus.domain.statements import Mapping
from tests.fakes import NOW, FakeMailbox, call, fake_email, say, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only, tool_results
from tests.integration.test_email import connect, messages, person, sweep

pytestmark = pytest.mark.integration

STATEMENT = """Transaction Date,Description,Debit Amount,Credit Amount
28 Sep 2026,KOPITIAM,4.20,
27 Sep 2026,IBKR TOPUP,800.00,
26 Sep 2026,Interactive Brokers WITHDRAWAL,,300.00
25 Sep 2026,FIBKRO SHOP,60.00,
24 Sep 2026,Card Payment 5678,1240.00,
"""


def sgd(amount: str) -> Money:
    return Money.of(amount, "SGD")


def noon(day: str) -> datetime:
    return datetime.combine(datetime.fromisoformat(day).date(), time(12), tzinfo=NOW.tzinfo)


async def wallets_of(uow: UowFactory, user: UserId) -> dict[str, Wallet]:
    return {w.name: w for w in await list_wallets(uow(), user)}


async def with_wallets(uow: UowFactory, user: UserId) -> dict[str, Wallet]:
    await add_wallet(uow(), user, "IBKR", "investment", ["ibkr", "interactive brokers"])
    await add_wallet(uow(), user, "Card", "card", ["card payment"])
    await add_wallet(uow(), user, "Savings", "savings")
    return await wallets_of(uow, user)


async def all_entries(uow: UowFactory, user: UserId) -> list[Transaction]:
    page = await list_ledger(uow(), user, LedgerQuery(limit=100))
    return sorted(page.items, key=lambda t: (t.occurred_at, t.amount.amount))


async def user_of(uow: UowFactory, actor: UserId) -> User:
    return await get_user(uow(), actor)


async def preview_of(uow: UowFactory, user: User) -> statement_cases.Preview:
    shown = await statement_cases.preview(uow, user, STATEMENT)
    assert shown.mapping is not None
    return shown


def proposed(shown: statement_cases.Preview) -> dict[int, UUID]:
    """What the preview proposes, as the web page would send it back."""
    return {p.row.index: p.wallet.id for p in shown.rows if p.wallet is not None}


# --- statement imports -----------------------------------------------------------------


async def test_a_preview_proposes_moves_for_rows_that_name_a_wallet(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    shown = await preview_of(uow, await user_of(uow, alice))
    rows = [(p.row.description, p.verdict, p.category) for p in shown.rows]
    assert rows == [
        ("KOPITIAM", Verdict.NEW, "Other"),
        ("IBKR TOPUP", Verdict.NEW, None),  # a move: no category
        ("Interactive Brokers WITHDRAWAL", Verdict.NEW, None),
        ("FIBKRO SHOP", Verdict.NEW, "Other"),  # whole words only
        ("Card Payment 5678", Verdict.NEW, None),
    ]
    out, money_in, shop, card = (shown.rows[i] for i in (1, 2, 3, 4))
    assert (out.move_to, out.move_from) == (wallets["IBKR"], None)  # Spending to IBKR
    assert (money_in.move_to, money_in.move_from) == (None, wallets["IBKR"])  # IBKR to Spending
    assert (shop.move_to, shop.move_from) == (None, None)
    assert card.move_to == wallets["Card"]
    assert (shown.rows[0].move_to, shown.rows[0].move_from) == (None, None)
    assert await all_entries(uow, alice) == []  # a preview saves nothing


async def test_without_wallets_a_preview_is_as_before(uow: UowFactory, alice: UserId) -> None:
    shown = await preview_of(uow, await user_of(uow, alice))
    assert all(p.wallet is None and p.category for p in shown.rows)


async def test_confirm_adds_proposed_rows_as_moves_with_the_import_linkage(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    user = await user_of(uow, alice)
    shown = await preview_of(uow, user)
    assert shown.mapping is not None
    moves = proposed(shown)
    assert moves == {1: wallets["IBKR"].id, 2: wallets["IBKR"].id, 4: wallets["Card"].id}

    done = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {0, 1, 2, 3, 4}, file_name="sept.csv",
        moves=moves, now=NOW,
    )  # fmt: skip
    assert len(done.record.transaction_ids) == 5 and done.skipped == 0
    spending = wallets["Spending"].id
    by_text = {t.counterparty: t for t in await all_entries(uow, alice)}

    topup = by_text["IBKR TOPUP"]
    assert (topup.direction, topup.source, topup.category_id) == (
        Direction.MOVE,
        Source.IMPORT,
        None,
    )
    assert (topup.from_wallet_id, topup.to_wallet_id) == (spending, wallets["IBKR"].id)
    assert topup.amount == sgd("800") and topup.occurred_at == noon("2026-09-27")
    withdrawal = by_text["Interactive Brokers WITHDRAWAL"]
    assert withdrawal.direction is Direction.MOVE
    assert (withdrawal.from_wallet_id, withdrawal.to_wallet_id) == (wallets["IBKR"].id, spending)
    card = by_text["Card Payment 5678"]
    assert (card.from_wallet_id, card.to_wallet_id) == (spending, wallets["Card"].id)
    # The rest are ordinary entries, filed as usual.
    assert by_text["KOPITIAM"].direction is Direction.OUT and by_text["KOPITIAM"].category_id
    assert by_text["FIBKRO SHOP"].direction is Direction.OUT
    assert {t.id for t in by_text.values()} == set(done.record.transaction_ids)

    # The file can't be imported twice, and the moves are claimed like any other row.
    again = await statement_cases.preview(uow, user, STATEMENT)
    assert {p.verdict for p in again.rows} == {Verdict.IMPORTED}
    repeat = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {0, 1, 2, 3, 4}, file_name="sept.csv",
        moves=moves, now=NOW,
    )  # fmt: skip
    assert repeat.record.transaction_ids == [] and repeat.skipped == 5
    assert len(await all_entries(uow, alice)) == 5

    # Undoing the import removes the moves too, and they stay claimed (tombstones).
    [record] = await statement_cases.list_imports(uow(), alice)
    assert await statement_cases.undo_import(uow(), alice, record.id, now=NOW) == 5
    assert await all_entries(uow, alice) == []
    later = await statement_cases.preview(uow, user, STATEMENT)
    assert {p.verdict for p in later.rows} == {Verdict.IMPORTED}
    redo = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {1}, file_name="sept.csv", moves=moves, now=NOW
    )
    assert redo.record.transaction_ids == [] and redo.skipped == 1


async def test_a_row_switched_back_is_an_ordinary_entry_and_any_row_can_be_a_move(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    user = await user_of(uow, alice)
    shown = await preview_of(uow, user)
    assert shown.mapping is not None
    moves = proposed(shown)
    del moves[1]  # the user switched the IBKR top-up back
    moves[0] = wallets["Savings"].id  # and made the kopitiam row a move

    await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {0, 1, 2}, file_name="sept.csv",
        moves={**moves, 3: wallets["Card"].id}, now=NOW,
    )  # fmt: skip
    by_text = {t.counterparty: t for t in await all_entries(uow, alice)}
    assert set(by_text) == {
        "KOPITIAM",
        "IBKR TOPUP",
        "Interactive Brokers WITHDRAWAL",
    }  # row 3: unticked
    topup = by_text["IBKR TOPUP"]
    assert topup.direction is Direction.OUT and topup.category_id is not None
    assert topup.from_wallet_id is None and topup.to_wallet_id is None
    kopitiam = by_text["KOPITIAM"]
    assert kopitiam.direction is Direction.MOVE and kopitiam.to_wallet_id == wallets["Savings"].id
    assert by_text["Interactive Brokers WITHDRAWAL"].direction is Direction.MOVE

    # The money is spending only where it was left as spending.
    assert sum(t.amount.amount for t in by_text.values() if t.direction is Direction.OUT) == 800


async def test_a_bad_wallet_for_a_row_is_refused_before_anything_is_added(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    theirs = await add_wallet(uow(), bob, "IBKR", "investment")
    user = await user_of(uow, alice)
    shown = await preview_of(uow, user)
    assert shown.mapping is not None

    async def confirm(moves: dict[int, UUID]) -> None:
        await statement_cases.confirm(
            uow, user, STATEMENT, shown.mapping or Mapping(0, (1,), 2),
            {0, 1}, file_name="x.csv", moves=moves, now=NOW,
        )  # fmt: skip

    with pytest.raises(InvalidInput):
        await confirm({1: wallets["Spending"].id})
    with pytest.raises(NotFound):
        await confirm({1: theirs.id})  # another user's wallet
    assert await all_entries(uow, alice) == []
    await confirm({7: theirs.id})  # a row that isn't ticked is ignored
    assert len(await all_entries(uow, alice)) == 2


async def test_a_row_matching_an_existing_move_is_flagged_as_a_duplicate(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    user = await user_of(uow, alice)
    spending = wallets["Spending"].id
    sent = await log_move(  # logged in chat a day before the bank shows it
        uow(), alice, amount=sgd("800"), to_wallet_id=wallets["IBKR"].id,
        occurred_at=noon("2026-09-26"),
    )  # fmt: skip
    came_back = await log_move(
        uow(), alice, amount=sgd("300"), from_wallet_id=wallets["IBKR"].id,
        to_wallet_id=spending, occurred_at=noon("2026-09-26"),
    )  # fmt: skip
    # Same amount and day as the card payment, but to another wallet: not the same thing.
    await log_move(
        uow(), alice, amount=sgd("1240"), to_wallet_id=wallets["Savings"].id,
        occurred_at=noon("2026-09-24"),
    )  # fmt: skip
    shown = await preview_of(uow, user)
    verdicts = {p.row.index: (p.verdict, p.matches) for p in shown.rows}
    assert verdicts[1][0] is Verdict.DUPLICATE and verdicts[1][1] == sent
    assert verdicts[2][0] is Verdict.DUPLICATE and verdicts[2][1] == came_back
    assert verdicts[4] == (Verdict.NEW, None)
    # A duplicate still shows what it would have been.
    assert shown.rows[1].move_to == wallets["IBKR"]


async def test_a_row_matching_an_expense_logged_by_hand_is_a_duplicate_too(
    uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    user = await user_of(uow, alice)
    hand = await log_transaction(
        uow(), alice, NewTransaction(Direction.OUT, sgd("800"), noon("2026-09-27"))
    )
    shown = await preview_of(uow, user)
    assert (shown.rows[1].verdict, shown.rows[1].matches) == (Verdict.DUPLICATE, hand)


async def test_wallets_of_another_user_never_match(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await with_wallets(uow, bob)
    shown = await preview_of(uow, await user_of(uow, alice))
    assert all(p.wallet is None for p in shown.rows)


# --- emails ------------------------------------------------------------------------------

IBKR_RECEIPT = "Merchant: IBKR\nTotal: 800.00\nCurrency: SGD\nDate: 2026-09-27"
IBKR_BACK = "From: Interactive Brokers\nTotal: 300.00\nCurrency: SGD\nDate: 2026-09-27"
GRAB = "Merchant: Grab\nTotal: 18.50\nCurrency: SGD\nDate: 2026-09-27"


async def waiting_emails(uow: UowFactory, user: User) -> dict[str, UUID]:
    found = await email_cases.overview(uow(), user.id, now=NOW)
    return {e.provider_message_id: e.id for e in found.emails}


async def test_an_email_naming_a_wallet_asks_instead_of_offering_to_log_it(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await with_wallets(uow, user.id)
    await set_frequency(uow(), user.id, Frequency.INSTANT, now=NOW)
    mailbox = FakeMailbox()
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)  # the first look-back finds nothing
    later = NOW + timedelta(minutes=10)
    mailbox.emails.update(
        {
            "out": fake_email("out", "Receipt for your top-up", IBKR_RECEIPT, at=later),
            "in": fake_email("in", "Funds received", IBKR_BACK, at=later),
            "grab": fake_email("grab", "Grab receipt", GRAB, at=later),
        }
    )
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=30))
    asked = {m["text"]: [b for row in m["buttons"] for b in row] for m in await messages(engine)}
    ids = await waiting_emails(uow, user)

    money_out = "📧 From your email: 800.00 SGD at IBKR on 27 Sep. Was this a move to IBKR?"
    assert [(b["label"], b["data"]) for b in asked[money_out]] == [
        ("Move", f"email:move:{ids['out']}"),
        ("Expense", f"email:log:{ids['out']}"),
        ("Skip", f"email:skip:{ids['out']}"),
    ]
    money_in = (
        "📧 From your email: 300.00 SGD came in from Interactive Brokers on 27 Sep. "
        "Was this a move from IBKR?"
    )
    assert [(b["label"], b["data"]) for b in asked[money_in]] == [
        ("Move", f"email:move:{ids['in']}"),
        ("Income", f"email:income:{ids['in']}"),
        ("Skip", f"email:skip:{ids['in']}"),
    ]
    # An email that names no wallet is asked about exactly as before.
    plain = asked["📧 From your email: 18.50 SGD at Grab on 27 Sep. Log it?"]
    assert [b["label"] for b in plain] == ["Log it", "Skip"]
    # Nothing is logged by asking.
    assert await all_entries(uow, user.id) == []


async def test_move_logs_a_move_and_marks_the_email_handled(uow: UowFactory) -> None:
    user = await person(uow)
    wallets = await with_wallets(uow, user.id)
    mailbox = FakeMailbox(
        {
            "out": fake_email("out", "Receipt for your top-up", IBKR_RECEIPT),
            "in": fake_email("in", "Funds received", IBKR_BACK),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    ids = await waiting_emails(uow, user)
    bot = build(uow, scripted())

    done = only(await bot.press(user.id, f"email:move:{ids['out']}"))
    assert done.text == (
        "Logged a move of 800.00 SGD to IBKR. It isn't counted as spending or income."
    )
    assert [b.label for row in done.buttons for b in row] == ["Undo"]
    back = only(await bot.press(user.id, f"email:move:{ids['in']}"))
    assert back.text == (
        "Logged a move of 300.00 SGD from IBKR. It isn't counted as spending or income."
    )
    by_amount = {t.amount.amount: t for t in await all_entries(uow, user.id)}
    sent, got = by_amount[Decimal("800")], by_amount[Decimal("300")]
    assert (sent.direction, sent.source, sent.category_id) == (Direction.MOVE, Source.EMAIL, None)
    assert (sent.from_wallet_id, sent.to_wallet_id) == (wallets["Spending"].id, wallets["IBKR"].id)
    assert (got.from_wallet_id, got.to_wallet_id) == (wallets["IBKR"].id, wallets["Spending"].id)
    assert sent.counterparty == "IBKR" and sent.notes == "Receipt for your top-up"
    assert sent.occurred_at.date().isoformat() == "2026-09-27"

    found = {
        e.provider_message_id: e
        for e in (await email_cases.overview(uow(), user.id, now=NOW)).emails
    }
    assert (found["out"].status.value, found["out"].transaction_id) == ("logged", sent.id)
    assert (found["in"].status.value, found["in"].transaction_id) == ("logged", got.id)
    # Answering twice logs nothing more.
    again = only(await bot.press(user.id, f"email:move:{ids['out']}"))
    assert again.text == "That email is already logged."
    assert len(await all_entries(uow, user.id)) == 2


async def test_expense_and_income_log_as_they_always_did(uow: UowFactory) -> None:
    user = await person(uow)
    await with_wallets(uow, user.id)
    mailbox = FakeMailbox(
        {
            "out": fake_email("out", "Receipt for your top-up", IBKR_RECEIPT),
            "in": fake_email("in", "Funds received", IBKR_BACK),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    ids = await waiting_emails(uow, user)
    bot = build(uow, scripted())
    assert only(await bot.press(user.id, f"email:log:{ids['out']}")).text == (
        "Logged 800.00 SGD at IBKR."
    )
    assert "Logged 300.00 SGD received from Interactive Brokers." in (
        only(await bot.press(user.id, f"email:income:{ids['in']}")).text
    )
    out, money_in = await all_entries(uow, user.id)
    if out.direction is Direction.IN:
        out, money_in = money_in, out
    assert (out.direction, out.amount, out.category_id is not None) == (
        Direction.OUT,
        sgd("800"),
        True,
    )
    assert (money_in.direction, money_in.amount) == (Direction.IN, sgd("300"))


async def test_move_needs_a_wallet_and_cant_be_logged_twice(uow: UowFactory) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "grab": fake_email("grab", "Grab receipt", GRAB),
            "out": fake_email("out", "Receipt for your top-up", IBKR_RECEIPT),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    ids = await waiting_emails(uow, user)
    # No wallet was named and none was picked.
    with pytest.raises(InvalidInput):
        await email_cases.move_email(uow, user, ids["grab"], now=NOW)
    wallets = await with_wallets(uow, user.id)
    with pytest.raises(InvalidInput):  # Spending is not "the other wallet"
        await email_cases.move_email(
            uow, user, ids["grab"], now=NOW, wallet_id=wallets["Spending"].id
        )
    # The user can pick the wallet themselves.
    picked = await email_cases.move_email(
        uow, user, ids["grab"], now=NOW, wallet_id=wallets["Savings"].id
    )
    assert picked.wallet.name == "Savings" and picked.transaction.amount == sgd("18.50")

    # Logged as an expense first, then "move" on the same email: refused.
    await email_cases.log_email(uow, user, ids["out"], now=NOW)
    with pytest.raises(Conflict):
        await email_cases.move_email(uow, user, ids["out"], now=NOW, wallet_id=wallets["IBKR"].id)

    # An email whose message was logged elsewhere in the meantime can't be logged again.
    mailbox.emails["late"] = fake_email(
        "late", "Receipt for your top-up", IBKR_RECEIPT, at=NOW + timedelta(minutes=10)
    )
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=30))
    late = (await waiting_emails(uow, user))["late"]
    key = external_id(connection.provider, connection.address, "late")
    await log_transaction(
        uow(),
        user.id,
        NewTransaction(Direction.OUT, sgd("800"), NOW, source=Source.EMAIL, external_id=key),
    )
    with pytest.raises(DuplicateSource):
        await email_cases.move_email(uow, user, late, now=NOW)
    found = (await email_cases.overview(uow(), user.id, now=NOW + timedelta(days=1))).emails
    assert {e.provider_message_id: e.status.value for e in found}["late"] == "duplicate"


async def test_the_chat_can_answer_a_waiting_email_with_move(uow: UowFactory) -> None:
    user = await person(uow)
    wallets = await with_wallets(uow, user.id)
    mailbox = FakeMailbox({"out": fake_email("out", "Receipt for your top-up", IBKR_RECEIPT)})
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    model = scripted(call("answer_email", number=1, action="move"), say("Done."))
    agent = build(uow, model)
    ask = only(await agent.handle_text(user.id, "that IBKR one was a move", "tg:1:1"))
    assert ask.text.startswith("Log it as a move between wallets, not spending or income? ")
    assert "may be a move to IBKR" in ask.text
    assert await all_entries(uow, user.id) == []
    await agent.resolve(user.id, ask.buttons[0][0].data.split(":")[1], True)
    [tx] = await all_entries(uow, user.id)
    assert (tx.direction, tx.to_wallet_id) == (Direction.MOVE, wallets["IBKR"].id)
    assert tool_results(model)[0].startswith("Logged a move (not spending or income): ")


# --- likely moves ------------------------------------------------------------------------


async def log(
    uow: UowFactory,
    user: UserId,
    direction: Direction,
    amount: str,
    day: str,
    who: str | None = None,
    **extra: Any,
) -> Transaction:
    return await log_transaction(
        uow(), user, NewTransaction(direction, sgd(amount), noon(day), counterparty=who, **extra)
    )


async def likely(uow: UowFactory, user: UserId) -> list[tuple[str | None, str | None, str]]:
    found = await wallet_cases.likely_moves(uow(), user, now=NOW)
    return [
        (m.transaction.counterparty, m.wallet.name if m.wallet else None, m.reason) for m in found
    ]


async def test_entries_naming_a_wallet_are_listed_as_likely_moves(
    uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    await log(uow, alice, Direction.OUT, "800", "2026-09-20", "IBKR")
    await log(uow, alice, Direction.IN, "300", "2026-09-10", "Interactive Brokers")
    await log(uow, alice, Direction.OUT, "55", "2026-09-05", "Cafe", notes="lunch via ibkr card")
    await log(uow, alice, Direction.OUT, "9", "2026-09-04", "FIBKRO SHOP")  # not a whole word
    await log(uow, alice, Direction.OUT, "5", "2026-09-03", "Kopitiam")
    await log(uow, alice, Direction.OUT, "700", "2026-01-02", "IBKR")  # too long ago
    assert await likely(uow, alice) == [
        ("IBKR", "IBKR", "matches 'ibkr'"),
        ("Interactive Brokers", "IBKR", "matches 'interactive brokers'"),
        ("Cafe", "IBKR", "matches 'ibkr'"),
    ]


async def test_a_same_amount_monthly_payment_is_a_likely_regular_transfer(
    uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    for day in ("2026-07-25", "2026-08-25", "2026-09-25"):
        await log(uow, alice, Direction.OUT, "500", day, "Acme Holdings")
    for day in ("2026-07-02", "2026-08-02", "2026-09-02"):  # the same payee, a changing amount
        await log(uow, alice, Direction.OUT, str(300 + int(day[6:7])), day, "Gym")
    for day in ("2026-08-10", "2026-09-10"):  # only two months so far
        await log(uow, alice, Direction.OUT, "40", day, "Newsletter")
    for day in ("2026-05-12", "2026-06-12", "2026-07-12"):  # a run that ended long ago
        await log(uow, alice, Direction.OUT, "75", day, "Old club")
    for day in ("2026-07-15", "2026-08-15", "2026-09-15"):  # money in is left alone (salary)
        await log(uow, alice, Direction.IN, "4000", day, "Acme Pte Ltd")

    found = await wallet_cases.likely_moves(uow(), alice, now=NOW)
    assert [m.transaction.occurred_at.date().isoformat() for m in found] == [
        "2026-09-25",
        "2026-08-25",
        "2026-07-25",
    ]
    assert {(m.transaction.counterparty, m.wallet) for m in found} == {("Acme Holdings", None)}
    assert found[0].reason == (
        "looks like a regular transfer: 500.00 SGD to Acme Holdings every month for 3+ months"
    )


async def test_a_regular_payee_naming_a_wallet_is_listed_once_with_the_wallet(
    uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    for day in ("2026-07-25", "2026-08-25", "2026-09-25"):
        await log(uow, alice, Direction.OUT, "500", day, "ibkr")
    assert await likely(uow, alice) == [("ibkr", "IBKR", "matches 'ibkr'")] * 3


async def test_a_month_with_two_payments_or_a_category_rule_is_not_a_regular_transfer(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.application import category_rules as rule_cases
    from nexus.application.categories import list_categories

    user = await user_of(uow, alice)
    await with_wallets(uow, alice)
    for day in ("2026-07-25", "2026-08-25", "2026-09-25", "2026-09-26"):  # twice in September
        await log(uow, alice, Direction.OUT, "500", day, "Acme Holdings")
    cats = {c.name: c.id for c in await list_categories(uow(), alice)}
    await rule_cases.set_rule(uow(), user, "landlord", cats["Other"], now=NOW)
    for day in ("2026-07-01", "2026-08-01", "2026-09-01"):  # filed by a rule: a known payee
        await log(uow, alice, Direction.OUT, "1800", day, "Landlord Lim")
    assert await likely(uow, alice) == []


async def test_splits_settlements_moves_and_deleted_entries_are_never_offered(
    uow: UowFactory, alice: UserId
) -> None:
    from nexus.application import splits as split_cases
    from nexus.domain.ledger import ShareRequest

    wallets = await with_wallets(uow, alice)
    shared = await log(uow, alice, Direction.OUT, "200", "2026-09-20", "IBKR dinner")
    await split_cases.split_bill(uow(), alice, shared.id, [ShareRequest("Wei Ming", sgd("100"))])
    owed = await log(uow, alice, Direction.OUT, "40", "2026-09-19", "Dinner")
    await split_cases.split_bill(uow(), alice, owed.id, [ShareRequest("Wei Ming", sgd("20"))])
    await split_cases.settle_iou(
        uow(), alice, "Wei Ming", sgd("20"), noon("2026-09-21"), notes="ibkr payback"
    )
    gone = await log(uow, alice, Direction.OUT, "10", "2026-09-18", "IBKR old")
    await delete_transaction(uow(), alice, gone.id)
    await log_move(
        uow(), alice, amount=sgd("800"), to_wallet_id=wallets["IBKR"].id,
        occurred_at=noon("2026-09-17"), counterparty="IBKR",
    )  # fmt: skip
    await log(uow, alice, Direction.OUT, "11", "2026-09-16", "IBKR top-up")
    assert await likely(uow, alice) == [("IBKR top-up", "IBKR", "matches 'ibkr'")]


async def test_listing_changes_nothing_and_converting_removes_the_suggestion(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    await with_wallets(uow, bob)
    tx = await log(uow, alice, Direction.OUT, "800", "2026-09-20", "IBKR")
    await log(uow, bob, Direction.OUT, "5", "2026-09-20", "IBKR")
    before = await all_entries(uow, alice)
    assert len(await wallet_cases.likely_moves(uow(), alice, now=NOW)) == 1
    assert await all_entries(uow, alice) == before  # nothing changed
    assert (await get_transaction(uow(), alice, tx.id)).direction is Direction.OUT

    await wallet_cases.mark_as_move(uow(), alice, tx.id, wallets["IBKR"].id)
    assert await wallet_cases.likely_moves(uow(), alice, now=NOW) == []


async def test_the_chat_lists_likely_moves_and_offers_to_convert_each(
    uow: UowFactory, alice: UserId
) -> None:
    wallets = await with_wallets(uow, alice)
    tx = await log(uow, alice, Direction.OUT, "800", "2026-09-20", "IBKR")
    for day in ("2026-07-25", "2026-08-25", "2026-09-25"):
        await log(uow, alice, Direction.OUT, "500", day, "Acme Holdings")
    model = scripted(
        call("find_likely_moves"),
        call("mark_as_move", transaction_id=str(tx.id), wallet="IBKR"),
        say("Done."),
    )
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "anything that should be a move?", "tg:1:1"))
    assert ask.text.startswith("Turn 2026-09-20 · -800.00 SGD · IBKR")
    listed = tool_results(model)[0]
    assert listed.startswith(
        "4 entries that may really have been moves (nothing has been changed):"
    )
    assert f"[id {tx.id}]" in listed and "→ IBKR: matches 'ibkr'" in listed
    assert "(which wallet? ask the user): looks like a regular transfer: 500.00 SGD" in listed
    assert (await get_transaction(uow(), alice, tx.id)).direction is Direction.OUT
    await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True)
    moved = await get_transaction(uow(), alice, tx.id)
    assert (moved.direction, moved.to_wallet_id) == (Direction.MOVE, wallets["IBKR"].id)


async def test_the_chat_says_when_there_is_nothing_to_suggest(
    uow: UowFactory, alice: UserId
) -> None:
    await with_wallets(uow, alice)
    model = scripted(call("find_likely_moves"), say("Nothing."))
    await build(uow, model).handle_text(alice, "anything that should be a move?", "tg:1:1")
    assert tool_results(model)[0] == (
        "No entries from the last six months look like moves between wallets."
    )


# --- a move already logged ---------------------------------------------------------------


async def later_sweep(
    engine: AsyncEngine, uow: UowFactory, user: User, emails: dict[str, Any]
) -> list[dict[str, Any]]:
    """Connect with nothing in the mailbox, then find ``emails`` on the next sweep, asked
    about one by one."""
    await set_frequency(uow(), user.id, Frequency.INSTANT, now=NOW)
    mailbox = FakeMailbox()
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    mailbox.emails.update(emails)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=30))
    return await messages(engine)


async def test_an_email_for_a_move_already_logged_asks_if_it_is_the_same_payment(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    wallets = await with_wallets(uow, user.id)
    spending = wallets["Spending"].id
    sent = await log_move(  # told to the chat the day before the email
        uow(), user.id, amount=sgd("800"), to_wallet_id=wallets["IBKR"].id,
        occurred_at=noon("2026-09-26"),
    )  # fmt: skip
    came_back = await log_move(
        uow(), user.id, amount=sgd("300"), from_wallet_id=wallets["IBKR"].id,
        to_wallet_id=spending, occurred_at=noon("2026-09-27"),
    )  # fmt: skip
    at = NOW + timedelta(minutes=10)
    asked = await later_sweep(
        engine,
        uow,
        user,
        {
            "out": fake_email("out", "Receipt for your top-up", IBKR_RECEIPT, at=at),
            "in": fake_email("in", "Funds received", IBKR_BACK, at=at),
        },
    )
    assert len(asked) == 2
    for message in asked:
        assert "Was this a move" not in message["text"] and "Same payment?" in message["text"]
        assert "already in your ledger" in message["text"]
        assert [b["label"] for row in message["buttons"] for b in row] == [
            "Same one",
            "It's another",
            "Skip",
        ]
    assert "This looks like no name, 800.00 SGD on 26 Sep" in asked[0]["text"]
    ids = await waiting_emails(uow, user)

    # No second move can be made from either email, however it is asked for.
    for key in ("out", "in"):
        with pytest.raises(Conflict):
            await email_cases.move_email(uow, user, ids[key], now=NOW)
    bot = build(uow, scripted())
    assert only(await bot.press(user.id, f"email:move:{ids['out']}")).text.startswith(
        "That move is already in your ledger"
    )
    assert {t.id for t in await all_entries(uow, user.id)} == {sent.id, came_back.id}

    # "Same one" adds nothing and marks the email handled against the existing move.
    same = only(await bot.press(user.id, f"email:same:{ids['out']}"))
    assert same.text.startswith("Got it, one payment: kept 800.00 SGD")
    page = await email_cases.overview(uow(), user.id, now=NOW)
    found = {e.provider_message_id: e for e in page.emails}
    assert (found["out"].status.value, found["out"].transaction_id) == ("logged", sent.id)
    assert {t.id for t in await all_entries(uow, user.id)} == {sent.id, came_back.id}


async def test_a_different_amount_wallet_direction_or_day_still_asks_about_a_move(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    wallets = await with_wallets(uow, user.id)
    await log_move(uow(), user.id, amount=sgd("801"), to_wallet_id=wallets["IBKR"].id,
                   occurred_at=noon("2026-09-27"))  # fmt: skip
    await log_move(uow(), user.id, amount=sgd("800"), to_wallet_id=wallets["Savings"].id,
                   occurred_at=noon("2026-09-27"))  # fmt: skip
    await log_move(uow(), user.id, amount=sgd("800"), from_wallet_id=wallets["IBKR"].id,
                   to_wallet_id=wallets["Spending"].id, occurred_at=noon("2026-09-27"))  # fmt: skip
    await log_move(uow(), user.id, amount=sgd("800"), to_wallet_id=wallets["IBKR"].id,
                   occurred_at=noon("2026-09-20"))  # fmt: skip
    at = NOW + timedelta(minutes=10)
    asked = await later_sweep(
        engine,
        uow,
        user,
        {"out": fake_email("out", "Receipt for your top-up", IBKR_RECEIPT, at=at)},
    )
    [message] = asked
    assert message["text"].endswith("Was this a move to IBKR?")
    assert [b["label"] for row in message["buttons"] for b in row] == ["Move", "Expense", "Skip"]
    ids = await waiting_emails(uow, user)
    moved = await email_cases.move_email(uow, user, ids["out"], now=NOW)  # nothing in the way
    assert moved.transaction.amount == sgd("800")
    assert len(await all_entries(uow, user.id)) == 5
