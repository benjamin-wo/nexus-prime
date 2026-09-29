"""Receipts from a connected Gmail: connecting through a one-time link, the sweep,
the user's confirmation, and never importing an email twice."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import category_rules as rule_cases
from nexus.application import email as email_cases
from nexus.application import notifications as notify_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.categories import list_categories
from nexus.application.ports import LedgerQuery, MailboxGrant
from nexus.application.receipts import with_receipts
from nexus.application.transactions import delete_transaction, list_ledger
from nexus.application.users import RegisterUser, register_user
from nexus.domain.email import ConnectionStatus, EmailConnection, FetchedEmail, Screening
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.ledger import Source, User
from nexus.domain.money import Money
from nexus.domain.notifications import Frequency
from nexus.infra.crypto.fernet import FernetCipher
from nexus.infra.db.tables import email_connections, jobs
from tests.fakes import NOW, FakeBucket, FakeEmailReader, FakeMailbox, fake_email, scripted
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only

pytestmark = pytest.mark.integration

CIPHER = FernetCipher(Fernet.generate_key().decode())
GRAB = "Merchant: Grab\nTotal: 18.50\nCurrency: SGD\nDate: 2026-09-27"


async def person(uow: UowFactory, telegram_id: int = 4242) -> User:
    registration = await register_user(
        uow(),
        RegisterUser(
            telegram_user_id=telegram_id,
            telegram_chat_id=telegram_id,
            home_currency="SGD",
            timezone="Asia/Singapore",
        ),
    )
    return registration.user


async def connect(uow: UowFactory, user: User, mailbox: FakeMailbox) -> EmailConnection:
    token = await email_cases.create_link(uow(), user, now=NOW)
    return await email_cases.finish_connect(
        uow, mailbox, CIPHER, token=token, code="ok", redirect_uri="https://x/cb", now=NOW
    )


async def sweep(
    uow: UowFactory,
    user: User,
    mailbox: FakeMailbox,
    connection: EmailConnection,
    *,
    at: Any = NOW,
    bucket: FakeBucket | None = None,
) -> email_cases.SweepResult:
    async with uow() as tx:
        current = await tx.email.get_connection(user.id, connection.id)
    assert current is not None
    return await email_cases.sweep(
        uow,
        mailbox,
        FakeEmailReader(),
        CIPHER,
        bucket,
        user,
        current,
        now=at,
        review_url="https://nexus.test/email",
    )


async def messages(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as db:
        rows = await db.execute(
            select(jobs.c.payload).where(jobs.c.kind == TELEGRAM_SEND).order_by(jobs.c.id)
        )
        return [r[0] for r in rows]


async def statuses(uow: UowFactory, user: User) -> dict[str, str]:
    found = await email_cases.overview(uow(), user.id, now=NOW + timedelta(days=1))
    return {e.provider_message_id: e.status.value for e in found.emails}


async def test_connecting_stores_the_grant_encrypted_and_spends_the_link(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    mailbox = FakeMailbox()
    token = await email_cases.create_link(uow(), user, now=NOW)
    assert await email_cases.link_owner(uow(), token, now=NOW) == user.id
    connection = await email_cases.finish_connect(
        uow, mailbox, CIPHER, token=token, code="ok", redirect_uri="https://x/cb", now=NOW
    )
    assert connection.address == "ann@gmail.com"
    async with engine.connect() as db:
        found = await db.scalar(select(email_connections.c.token))
    assert found is not None
    stored = bytes(found)
    assert b"refresh-token-1" not in stored
    assert CIPHER.decrypt(stored) == "refresh-token-1"

    # A replayed callback connects nothing.
    with pytest.raises(NotFound):
        await email_cases.finish_connect(
            uow, mailbox, CIPHER, token=token, code="ok", redirect_uri="https://x/cb", now=NOW
        )
    # Links expire after 10 minutes.
    late = await email_cases.create_link(uow(), user, now=NOW)
    later = NOW + timedelta(minutes=10)
    assert await email_cases.link_owner(uow(), late, now=later) is None
    # Declining the read permission connects nothing.
    fresh = await email_cases.create_link(uow(), user, now=NOW)
    with pytest.raises(InvalidInput):
        await email_cases.finish_connect(
            uow, mailbox, CIPHER, token=fresh, code="no-permission", redirect_uri="x", now=NOW
        )
    # Connecting the same mailbox again refreshes it rather than adding a second one.
    again = await connect(uow, user, mailbox)
    assert again.id == connection.id


async def test_the_first_sweep_looks_back_and_asks_once(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "m1": fake_email("m1", "Your Grab e-receipt", GRAB, at=NOW - timedelta(days=2)),
            "m2": fake_email(
                "m2",
                "Receipt for your order",
                "Merchant: Shopee\nTotal: 42.00",
                at=NOW - timedelta(days=3),
                sender="noreply@shopee.sg",
            ),
            "m3": fake_email("m3", "50% off everything!", at=NOW - timedelta(days=1)),
            "m4": fake_email(
                "m4", "Receipt", "Thanks for your payment", at=NOW - timedelta(days=4)
            ),
            "old": fake_email("old", "Receipt", GRAB, at=NOW - timedelta(days=31)),
        }
    )
    connection = await connect(uow, user, mailbox)
    result = await sweep(uow, user, mailbox, connection)
    assert (result.read, result.waiting, result.first) == (4, 2, True)
    assert await statuses(uow, user) == {
        "m1": "pending",
        "m2": "pending",
        "m3": "not_receipt",
        "m4": "no_amount",
    }
    [summary] = await messages(engine)
    assert summary["text"].startswith("📧 I found 2 receipts from the last 30 days.")
    assert summary["buttons"] == [
        [{"label": "Review them", "data": "url:https://nexus.test/email"}]
    ]
    assert (await list_ledger(uow(), user.id, LedgerQuery())).total == 0  # nothing yet

    # By default a later receipt waits for the end-of-day summary; old ones aren't
    # read again.
    mailbox.emails["m5"] = fake_email("m5", "Grab receipt", GRAB, at=NOW + timedelta(minutes=20))
    mailbox.fetched.clear()
    result = await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=30))
    assert (result.read, result.waiting, result.first) == (1, 1, False)
    assert mailbox.fetched == ["m5"]
    assert len(await messages(engine)) == 1

    # With updates as they happen, it gets its own question.
    await notify_cases.set_frequency(uow(), user.id, Frequency.INSTANT, now=NOW)
    mailbox.emails["m6"] = fake_email("m6", "Grab receipt", GRAB, at=NOW + timedelta(minutes=40))
    result = await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=45))
    assert (result.read, result.waiting, result.first) == (1, 1, False)
    question = (await messages(engine))[-1]
    assert question["text"] == "📧 From your email: 18.50 SGD at Grab on 27 Sep. Log it?"
    [[log_it, skip]] = question["buttons"]
    assert (log_it["label"], skip["label"]) == ("Log it", "Skip")
    assert log_it["data"].startswith("email:log:")


async def test_confirming_logs_it_once_and_never_again(uow: UowFactory) -> None:
    user = await person(uow)
    transport = next(c for c in await list_categories(uow(), user.id) if c.name == "Transport")
    await rule_cases.set_rule(uow(), user, "grab", transport.id, now=NOW)
    mailbox = FakeMailbox({"m1": fake_email("m1", "Grab receipt", GRAB)})
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=1))
    [email] = (await email_cases.overview(uow(), user.id, now=NOW)).emails

    tx = await email_cases.log_email(uow, user, email.id, now=NOW)
    assert tx.source is Source.EMAIL and tx.amount == Money.of("18.50", "SGD")
    assert tx.counterparty == "Grab" and tx.category_id == transport.id  # rules still apply
    assert tx.occurred_at.date().isoformat() == "2026-09-27"
    assert await statuses(uow, user) == {"m1": "logged"}
    with pytest.raises(Conflict):
        await email_cases.log_email(uow, user, email.id, now=NOW)

    # Deleted, disconnected and reconnected: the email is still never imported again.
    await delete_transaction(uow(), user.id, tx.id)
    await email_cases.disconnect(uow, mailbox, CIPHER, user.id, connection.id)
    assert mailbox.revocations == ["refresh-token-1"]
    again = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, again, at=NOW + timedelta(minutes=2))
    assert await statuses(uow, user) == {"m1": "duplicate"}


async def test_skipping_and_supplying_a_missing_amount(uow: UowFactory) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "m1": fake_email("m1", "Grab receipt", GRAB),
            "m2": fake_email("m2", "Receipt", "Merchant: Kopitiam"),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=1))
    emails = {
        e.provider_message_id: e
        for e in (await email_cases.overview(uow(), user.id, now=NOW)).emails
    }

    await email_cases.skip_email(uow(), user.id, emails["m1"].id)
    with pytest.raises(InvalidInput, match="no amount"):
        await email_cases.log_email(uow, user, emails["m2"].id, now=NOW)
    tx = await email_cases.log_email(
        uow, user, emails["m2"].id, now=NOW, amount=Money.of("4.20", "SGD")
    )
    assert tx.counterparty == "Kopitiam"
    # A skipped one can still be logged later from the Email page.
    await email_cases.log_email(uow, user, emails["m1"].id, now=NOW)
    assert await statuses(uow, user) == {"m1": "logged", "m2": "logged"}


async def test_a_pdf_receipt_is_kept_with_the_expense(uow: UowFactory) -> None:
    user = await person(uow)
    bucket = FakeBucket()
    mailbox = FakeMailbox({"m1": fake_email("m1", "Tax invoice receipt", GRAB, pdf=b"%PDF-1.7")})
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=1), bucket=bucket)
    [(data, kind)] = bucket.objects.values()
    assert kind == "application/pdf" and data == b"%PDF-1.7"
    [email] = (await email_cases.overview(uow(), user.id, now=NOW)).emails
    tx = await email_cases.log_email(uow, user, email.id, now=NOW)
    assert await with_receipts(uow(), user.id, [tx.id]) == {tx.id}


async def test_a_revoked_mailbox_stops_and_says_so_once(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    mailbox = FakeMailbox()
    connection = await connect(uow, user, mailbox)
    mailbox.revoked = True
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=1))
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=2))
    [told] = await messages(engine)
    assert told["text"].startswith("I can't read ann@gmail.com any more")
    async with uow() as tx:
        assert await tx.email.connections_to_sweep() == []
        [broken] = await tx.email.list_connections(user.id)
    assert broken.status is ConnectionStatus.BROKEN
    # Reconnecting brings it back.
    mailbox.revoked = False
    assert (await connect(uow, user, mailbox)).status is ConnectionStatus.ACTIVE


async def test_mailboxes_are_private(uow: UowFactory) -> None:
    ann, ben = await person(uow, 1), await person(uow, 2)
    mailbox = FakeMailbox({"m1": fake_email("m1", "Grab receipt", GRAB)})
    connection = await connect(uow, ann, mailbox)
    await sweep(uow, ann, mailbox, connection, at=NOW + timedelta(minutes=1))
    [email] = (await email_cases.overview(uow(), ann.id, now=NOW)).emails

    assert (await email_cases.overview(uow(), ben.id, now=NOW)).emails == []
    with pytest.raises(NotFound):
        await email_cases.log_email(uow, ben, email.id, now=NOW)
    with pytest.raises(NotFound):
        await email_cases.skip_email(uow(), ben.id, email.id)
    with pytest.raises(NotFound):
        await email_cases.disconnect(uow, mailbox, CIPHER, ben.id, connection.id)
    # Ann's link can only ever connect a mailbox to Ann.
    token = await email_cases.create_link(uow(), ann, now=NOW)
    mailbox.grant = MailboxGrant("ben@gmail.com", "refresh-token-1")
    joined = await email_cases.finish_connect(
        uow, mailbox, CIPHER, token=token, code="ok", redirect_uri="x", now=NOW
    )
    assert joined.user_id == ann.id


async def test_telegram_buttons_log_and_skip(uow: UowFactory) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {"m1": fake_email("m1", "Grab receipt", GRAB), "m2": fake_email("m2", "Receipt", GRAB)}
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=1))
    emails = {
        e.provider_message_id: e.id
        for e in (await email_cases.overview(uow(), user.id, now=NOW)).emails
    }
    bot = build(uow, scripted())
    logged = only(await bot.press(user.id, f"email:log:{emails['m1']}"))
    assert logged.text == "Logged 18.50 SGD at Grab."
    assert logged.buttons[0][0].label == "Undo"
    again = only(await bot.press(user.id, f"email:log:{emails['m1']}"))
    assert again.text == "That email is already logged."
    skipped = only(await bot.press(user.id, f"email:skip:{emails['m2']}"))
    assert skipped.text == "Skipped. Nothing was logged."
    assert only(await bot.press(user.id, "email:log:nope")).text == "I don't know that button."


async def test_a_stuck_read_is_given_up_on(
    uow: UowFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    class StuckReader(FakeEmailReader):
        async def triage(self, email: FetchedEmail) -> Screening:
            if email.provider_message_id == "stuck":
                await asyncio.sleep(10)
            return await super().triage(email)

    monkeypatch.setattr(email_cases, "READ_TIMEOUT", timedelta(milliseconds=50))
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "stuck": fake_email("stuck", "Receipt", GRAB, at=NOW - timedelta(hours=2)),
            "m1": fake_email("m1", "Grab receipt", GRAB, at=NOW - timedelta(hours=1)),
        }
    )
    connection = await connect(uow, user, mailbox)
    result = await email_cases.sweep(
        uow, mailbox, StuckReader(), CIPHER, None, user, connection, now=NOW
    )
    assert result.read == 2
    found = {
        e.provider_message_id: e
        for e in (await email_cases.overview(uow(), user.id, now=NOW)).emails
    }
    assert (found["stuck"].status.value, found["stuck"].reason) == (
        "failed",
        "took too long to read",
    )
    assert found["m1"].status.value == "pending"


async def test_bank_alert_amounts_are_read_as_written(uow: UowFactory) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "a1": fake_email("a1", "PayLah receipt", "Merchant: Juz Bread\nTotal: S$5.20"),
            "a2": fake_email("a2", "Card receipt", "Merchant: Subway\nTotal: SGD 8.90"),
            "a3": fake_email("a3", "Bill receipt", "Merchant: MyRepublic\nTotal: see invoice"),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    found = await email_cases.overview(uow(), user.id, now=NOW + timedelta(days=1))
    by_id = {e.provider_message_id: e for e in found.emails}
    assert by_id["a1"].status.value == "pending"
    assert by_id["a1"].draft is not None
    assert Decimal(by_id["a1"].draft["amount"]) == Decimal("5.20")
    assert by_id["a1"].draft["currency"] == "SGD"
    assert by_id["a2"].draft is not None
    assert Decimal(by_id["a2"].draft["amount"]) == Decimal("8.90")
    # What couldn't be read is said, so the Email page can show why.
    assert by_id["a3"].status.value == "no_amount"
    assert by_id["a3"].reason == 'couldn\'t read the amount "see invoice"'
    assert by_id["a3"].draft is not None
    assert by_id["a3"].draft["amount"] is None
