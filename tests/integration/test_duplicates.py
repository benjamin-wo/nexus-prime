"""One payment recorded twice: an email that looks like an entry already in the
ledger, or like another email waiting, is asked about as "same payment?"; pairs
already in the ledger can be merged or marked as two. Every name and figure here is
made up."""

from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import duplicates as duplicate_cases
from nexus.application import email as email_cases
from nexus.application import splits as split_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import (
    NewTransaction,
    get_transaction,
    list_ledger,
    log_transaction,
    restore_transaction,
)
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, ShareRequest, Source, Transaction, User
from nexus.domain.money import Money
from tests.fakes import NOW, FakeMailbox, fake_email
from tests.integration.conftest import UowFactory
from tests.integration.test_email import connect, messages, person, statuses, sweep

pytestmark = pytest.mark.integration

ALERT = "Merchant: Grab* A-7KXPLMQZRTWB\nTotal: 23.40\nCurrency: SGD"
RECEIPT = "Merchant: Grab Singapore\nTotal: 23.40\nCurrency: SGD"


def sgd(amount: str) -> Money:
    return Money(Decimal(amount), "SGD")


async def typed(
    uow: UowFactory, user: User, merchant: str, amount: str = "23.40", hours: int = 2
) -> Transaction:
    return await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            direction=Direction.OUT,
            amount=sgd(amount),
            occurred_at=NOW - timedelta(hours=hours),
            counterparty=merchant,
        ),
    )


async def from_email(
    uow: UowFactory, user: User, merchant: str, amount: str = "23.40", hours: int = 3
) -> Transaction:
    """An expense logged from a card alert email."""
    return await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            direction=Direction.OUT,
            amount=sgd(amount),
            occurred_at=NOW - timedelta(hours=hours),
            counterparty=merchant,
            source=Source.EMAIL,
            external_id=f"gmail:ann@gmail.com:{merchant}:{amount}",
            notes="Card alert",
        ),
    )


async def live(uow: UowFactory, user: User) -> list[Transaction]:
    return (await list_ledger(uow(), user.id, LedgerQuery())).items


async def test_an_email_for_a_payment_already_logged_asks_same_one(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    entry = await typed(uow, user, "Grab* A-7KXPLMQZRTWB")
    mailbox = FakeMailbox(
        {"r1": fake_email("r1", "Your Grab receipt", RECEIPT, at=NOW - timedelta(hours=1))}
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    [question] = await messages(engine)
    assert question["text"] == (
        "📧 From your email: 23.40 SGD at Grab Singapore on 28 Sep. This looks like Grab* "
        "A-7KXPLMQZRTWB, 23.40 SGD on 28 Sep, already in your ledger. Same payment?"
    )
    labels = [b["label"] for row in question["buttons"] for b in row]
    assert labels == ["Same one", "It's another", "Skip"]

    [email] = await email_cases.waiting(uow(), user.id, now=NOW)
    assert "looks like the same payment as Grab* A-7KXP" in email_cases.describe(
        email, ZoneInfo("Asia/Singapore")
    )
    kept = await email_cases.same_payment(uow, user, email.id, now=NOW)
    assert kept is not None and kept.id == entry.id
    assert kept.counterparty == "Grab Singapore"  # the readable name wins
    assert [(t.id, t.amount) for t in await live(uow, user)] == [(entry.id, sgd("23.40"))]
    assert await statuses(uow, user) == {"r1": "logged"}


async def test_its_another_logs_it_as_usual(uow: UowFactory) -> None:
    user = await person(uow)
    await typed(uow, user, "Grab")
    mailbox = FakeMailbox(
        {"r1": fake_email("r1", "Your Grab receipt", RECEIPT, at=NOW - timedelta(hours=1))}
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    [email] = await email_cases.waiting(uow(), user.id, now=NOW)
    assert email_cases.duplicate_of(email) is not None
    await email_cases.log_email(uow, user, email.id, now=NOW)
    assert len(await live(uow, user)) == 2


async def test_a_card_alert_and_the_receipt_in_one_sweep(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "a1": fake_email("a1", "Card receipt", ALERT, at=NOW - timedelta(hours=2)),
            "r1": fake_email("r1", "Your Grab receipt", RECEIPT, at=NOW - timedelta(hours=1)),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection, at=NOW)
    await sweep(uow, user, mailbox, connection, at=NOW)  # nothing new: nothing asked twice
    by_id = {
        e.provider_message_id: e
        for e in (await email_cases.overview(uow(), user.id, now=NOW)).emails
    }
    assert email_cases.duplicate_of(by_id["a1"]) is None
    twin = email_cases.duplicate_of(by_id["r1"])
    assert twin is not None and twin["email_id"] == str(by_id["a1"].id)

    # "Same one" on the receipt: nothing is logged, the alert takes the better name.
    assert await email_cases.same_payment(uow, user, by_id["r1"].id, now=NOW) is None
    assert await statuses(uow, user) == {"a1": "pending", "r1": "duplicate"}
    tx = await email_cases.log_email(uow, user, by_id["a1"].id, now=NOW)
    assert (tx.counterparty, tx.amount) == ("Grab Singapore", sgd("23.40"))
    assert len(await live(uow, user)) == 1
    assert len(await messages(engine)) == 1  # the first sweep's one summary


async def test_two_card_alerts_at_one_price_are_two_rides(uow: UowFactory) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "a1": fake_email("a1", "Card receipt", ALERT, at=NOW - timedelta(hours=3)),
            "a2": fake_email("a2", "Card receipt", ALERT, at=NOW - timedelta(hours=1)),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    found = (await email_cases.overview(uow(), user.id, now=NOW)).emails
    assert [email_cases.duplicate_of(e) for e in found] == [None, None]


async def test_pairs_in_the_ledger_merge_or_stay_two(uow: UowFactory) -> None:
    user = await person(uow)
    alert = await from_email(uow, user, "Grab* A-7KXPLMQZRTWB")
    receipt = await typed(uow, user, "Grab Singapore", hours=2)
    bus = await from_email(uow, user, "BUS/MRT", "1.95")
    other_bus = await typed(uow, user, "Kopi place", "1.95")

    found = await duplicate_cases.matches(uow(), user, await live(uow, user))
    assert found[alert.id].id == receipt.id and found[receipt.id].id == alert.id
    assert bus.id not in found and other_bus.id not in found
    pairs = await duplicate_cases.find_pairs(
        uow, user, NOW - timedelta(days=1), NOW + timedelta(days=1)
    )
    assert [(p.first.id, p.second.id) for p in pairs] == [(receipt.id, alert.id)]

    merged = await duplicate_cases.merge(uow, user.id, receipt.id, alert.id)
    assert merged.kept.id == alert.id  # logged first
    assert merged.kept.counterparty == "Grab Singapore"
    assert merged.removed.id == receipt.id and merged.removed.is_deleted
    assert await duplicate_cases.matches(uow(), user, await live(uow, user)) == {}

    # Restored, they're a pair again until the user says they're two payments.
    await restore_transaction(uow(), user.id, receipt.id)
    assert receipt.id in await duplicate_cases.matches(uow(), user, await live(uow, user))
    await duplicate_cases.dismiss(uow(), user.id, alert.id, receipt.id, now=NOW)
    await duplicate_cases.dismiss(uow(), user.id, receipt.id, alert.id, now=NOW)  # again: fine
    assert await duplicate_cases.matches(uow(), user, await live(uow, user)) == {}


async def test_a_split_bill_is_the_one_kept(uow: UowFactory) -> None:
    user = await person(uow)
    first = await typed(uow, user, "Grab Singapore", hours=3)
    split = await typed(uow, user, "Grab* A-7KXP", hours=2)
    await split_cases.split_bill(uow(), user.id, split.id, [ShareRequest("Ann", sgd("20"))])
    merged = await duplicate_cases.merge(uow, user.id, first.id, split.id)
    assert merged.kept.id == split.id and merged.kept.counterparty == "Grab Singapore"
    assert (await get_transaction(uow(), user.id, first.id)).is_deleted

    other = await typed(uow, user, "Coffee", "5")
    with pytest.raises(InvalidInput):
        await duplicate_cases.merge(uow, user.id, split.id, other.id)  # not the same amount
    with pytest.raises(InvalidInput):
        await duplicate_cases.merge(uow, user.id, split.id, split.id)


async def test_an_email_entry_counts_like_any_other(uow: UowFactory) -> None:
    """A typed entry and an email of the same ride pair up in the ledger too."""
    user = await person(uow)
    await typed(uow, user, "Grab")
    await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            direction=Direction.OUT,
            amount=sgd("23.40"),
            occurred_at=NOW - timedelta(hours=1),
            counterparty="Grab Singapore",
            source=Source.EMAIL,
            external_id="gmail:ann@gmail.com:r9",
            notes="Your Grab receipt",
        ),
    )
    assert len(await duplicate_cases.matches(uow(), user, await live(uow, user))) == 2


async def test_the_same_one_button(uow: UowFactory) -> None:
    from tests.fakes import scripted
    from tests.integration.test_agent import build, only

    user = await person(uow)
    await typed(uow, user, "Grab* A-7KXP")
    mailbox = FakeMailbox(
        {"r1": fake_email("r1", "Your Grab receipt", RECEIPT, at=NOW - timedelta(hours=1))}
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    [email] = await email_cases.waiting(uow(), user.id, now=NOW)
    bot = build(uow, scripted())
    reply = only(await bot.press(user.id, f"email:same:{email.id}"))
    assert reply.text == "Got it, one payment: kept 23.40 SGD as Grab Singapore. Nothing added."
    again = only(await bot.press(user.id, f"email:same:{email.id}"))
    assert again.text == "That email is already logged."
