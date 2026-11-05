"""Money in is believed only from a bank or a payment service, and the same payment in two
currencies (a merchant's euro receipt, the card's own conversion) is asked about, never
merged on a guess. Every merchant, sender and figure here is made up."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from nexus.application import email as email_cases
from nexus.application.transactions import NewTransaction, get_transaction, log_transaction
from nexus.domain.email import ExpenseDraft, InboundEmail
from nexus.domain.ledger import Direction, Source, User
from nexus.domain.money import Money
from tests.fakes import NOW, FakeEmailReader, FakeMailbox, FakeRates, fake_email
from tests.integration.conftest import UowFactory
from tests.integration.test_email import CIPHER, connect, person, statuses

pytestmark = pytest.mark.integration

# Subjects with "received" are read as money in by the scripted reader, as a model might
# misread a merchant's "payment received".
CONFIRMATION = "Merchant: Acme Hire\nTotal: 14.00\nCurrency: EUR\nDate: 2026-09-27"
TRANSFER = "From: TAN WEI MING\nTotal: 20.00\nCurrency: SGD\nDate: 2026-09-27"
EUR_SGD = FakeRates({("EUR", "SGD"): {date(2026, 9, 1): "1.48"}})


async def swept(
    uow: UowFactory,
    user: User,
    mailbox: FakeMailbox,
    *,
    rates: FakeRates | None = None,
    at: Any = NOW,
) -> dict[str, InboundEmail]:
    connection = await connect(uow, user, mailbox)
    async with uow() as tx:
        current = await tx.email.get_connection(user.id, connection.id)
    assert current is not None
    await email_cases.sweep(
        uow, mailbox, FakeEmailReader(), CIPHER, None, user, current, now=at, rates=rates
    )
    found = await email_cases.overview(uow(), user.id, now=NOW + timedelta(days=1))
    return {e.provider_message_id: e for e in found.emails}


# --- money in only from a bank or a payment service ----------------------------------------


async def test_a_merchants_payment_confirmation_misread_as_received_is_spent(
    uow: UowFactory, caplog: pytest.LogCaptureFixture
) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "m1": fake_email(
                "m1",
                "Payment received for your hire",
                CONFIRMATION,
                sender="billing@acmehire.example",
            )
        }
    )
    with caplog.at_level("INFO", logger="nexus.application.email"):
        [email] = (await swept(uow, user, mailbox)).values()
    draft = ExpenseDraft.from_dict(email.draft or {})
    assert email.status.value == "pending" and not draft.received
    assert (Decimal(draft.amount or "0"), draft.currency, draft.merchant) == (
        Decimal("14"),
        "EUR",
        "Acme Hire",
    )
    assert "direction" not in (email.draft or {})
    assert email_cases.prompt_text(email, ZoneInfo(user.timezone)).endswith("Log it?")
    assert "money in" not in email_cases.prompt_text(email, ZoneInfo(user.timezone))
    tx = await email_cases.log_email(uow, user, email.id, now=NOW)
    assert tx.direction is Direction.OUT and tx.amount == Money.of("14.00", "EUR")
    # The override is logged, with nothing about the email in it.
    logged = [r.getMessage() for r in caplog.records if "no bank or payment service" in r.message]
    assert len(logged) == 1
    assert "acmehire" not in logged[0] and "Acme" not in logged[0] and "14.00" not in logged[0]


@pytest.mark.parametrize(
    ("sender", "subject"),
    [
        ("alerts@uob.com.sg", "You've received a transfer"),
        ("noreply@mail.dbs.com", "PayNow: you have received money"),
        ("service@paypal.com", "You've received money from Wei Ming"),
        ("no-reply@wise.com", "You've received a transfer"),
    ],
)
async def test_money_in_from_a_bank_or_payment_service_stays_received(
    uow: UowFactory, sender: str, subject: str
) -> None:
    user = await person(uow)
    mailbox = FakeMailbox({"t1": fake_email("t1", subject, TRANSFER, sender=sender)})
    [email] = (await swept(uow, user, mailbox)).values()
    assert ExpenseDraft.from_dict(email.draft or {}).received
    assert (email.draft or {})["direction"] == "in"
    tx = await email_cases.log_email(uow, user, email.id, now=NOW)
    assert tx.direction is Direction.IN and tx.counterparty == "TAN WEI MING"


# --- the same payment in two currencies ----------------------------------------------------


def alert(amount: str = "20.67", merchant: str | None = "Acme Hire", **kw: Any) -> Any:
    lines = ([f"Merchant: {merchant}"] if merchant else []) + [
        f"Total: {amount}",
        "Currency: SGD",
    ]
    return fake_email(
        "a1",
        "Card receipt alert",
        "\n".join(lines),
        sender="alerts@uob.com.sg",
        at=NOW - timedelta(hours=1),
        **kw,
    )


async def eur_entry(uow: UowFactory, user: User, merchant: str = "Acme Hire") -> Any:
    return await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            Direction.OUT,
            Money.of("14.00", "EUR"),
            NOW - timedelta(hours=3),
            counterparty=merchant,
            source=Source.TEXT,
            notes="Payment confirmation",
        ),
    )


async def test_a_euro_entry_and_the_cards_conversion_are_asked_about(uow: UowFactory) -> None:
    user = await person(uow)
    entry = await eur_entry(uow, user)
    emails = await swept(uow, user, FakeMailbox({"a1": alert()}), rates=EUR_SGD)
    twin = email_cases.duplicate_of(emails["a1"])
    assert twin is not None and twin["transaction_id"] == str(entry.id)
    assert twin["label"].startswith("Acme Hire, 14.00 EUR on ")
    assert await statuses(uow, user) == {"a1": "pending"}  # asked, nothing merged
    assert (await get_transaction(uow(), user.id, entry.id)).amount == Money.of("14.00", "EUR")


async def test_same_one_keeps_the_entry_in_the_home_currency(uow: UowFactory) -> None:
    user = await person(uow)
    entry = await eur_entry(uow, user)
    emails = await swept(uow, user, FakeMailbox({"a1": alert()}), rates=EUR_SGD)
    kept = await email_cases.same_payment(uow, user, emails["a1"].id, now=NOW)
    assert kept is not None and kept.id == entry.id
    assert kept.amount == Money.of("20.67", "SGD")
    assert (await get_transaction(uow(), user.id, entry.id)).amount == Money.of("20.67", "SGD")
    assert await statuses(uow, user) == {"a1": "logged"}


async def test_a_home_currency_entry_is_kept_as_it_is(uow: UowFactory) -> None:
    user = await person(uow)
    sgd = await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            Direction.OUT,
            Money.of("20.67", "SGD"),
            NOW - timedelta(hours=3),
            counterparty="Acme Hire",
            source=Source.TEXT,
        ),
    )
    receipt = fake_email(
        "r1",
        "Your Acme receipt",
        CONFIRMATION.replace("2026-09-27", "2026-09-28"),
        sender="billing@acmehire.example",
        at=NOW - timedelta(hours=1),
    )
    emails = await swept(uow, user, FakeMailbox({"r1": receipt}), rates=EUR_SGD)
    twin = email_cases.duplicate_of(emails["r1"])
    assert twin is not None and twin["transaction_id"] == str(sgd.id)
    kept = await email_cases.same_payment(uow, user, emails["r1"].id, now=NOW)
    assert kept is not None and kept.amount == Money.of("20.67", "SGD")


async def test_two_waiting_emails_in_two_currencies_keep_the_home_one(uow: UowFactory) -> None:
    user = await person(uow)
    receipt = fake_email(
        "r1",
        "Your Acme receipt",
        CONFIRMATION.replace("2026-09-27", "2026-09-28"),
        sender="billing@acmehire.example",
        at=NOW - timedelta(hours=3),
    )
    mailbox = FakeMailbox({"r1": receipt, "a1": alert()})
    emails = await swept(uow, user, mailbox, rates=EUR_SGD)
    twin = email_cases.duplicate_of(emails["a1"])
    assert twin is not None and twin["email_id"] == str(emails["r1"].id)

    assert await email_cases.same_payment(uow, user, emails["a1"].id, now=NOW) is None
    tx = await email_cases.log_email(uow, user, emails["r1"].id, now=NOW)
    assert tx.amount == Money.of("20.67", "SGD")
    assert await statuses(uow, user) == {"r1": "logged", "a1": "duplicate"}


@pytest.mark.parametrize(
    ("what", "rates", "merchant", "amount"),
    [
        ("no rate for the currency", FakeRates(), "Acme Hire", "20.67"),
        ("rates unavailable", None, "Acme Hire", "20.67"),
        ("ten percent apart", EUR_SGD, "Acme Hire", "22.80"),
        ("a different merchant", EUR_SGD, "Zeta Taxis", "20.67"),
        ("the card alert has no name", EUR_SGD, None, "20.67"),
    ],
)
async def test_what_is_not_the_same_payment_in_two_currencies(
    uow: UowFactory, what: str, rates: FakeRates | None, merchant: str | None, amount: str
) -> None:
    user = await person(uow)
    await eur_entry(uow, user)
    emails = await swept(uow, user, FakeMailbox({"a1": alert(amount, merchant)}), rates=rates)
    assert email_cases.duplicate_of(emails["a1"]) is None, what
