"""Cards found in bank emails: the issuer from the sender's domain, matching a card by its
last four digits (and issuer), adding a card that isn't there yet, the one notice with Keep
and Remove, the one-time question for someone who doesn't track cards, and a bank alert that
gives the card to the entry it duplicates. Every name, sender and digit is made up."""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import email as email_cases
from nexus.application import found_cards
from nexus.application.transactions import (
    NewTransaction,
    get_transaction,
    log_transaction,
)
from nexus.application.users import RegisterUser, get_user, register_user, set_track_cards
from nexus.application.wallets import add_wallet, list_wallets, log_move, set_usual_card
from nexus.domain.email import InboundEmail
from nexus.domain.ledger import Direction, User, Wallet, WalletKind
from nexus.domain.money import Money
from nexus.domain.notifications import UNCAPPED
from nexus.infra.db.engine import make_engine
from tests.fakes import NOW, FakeMailbox, fake_email, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, only
from tests.integration.test_email import connect, messages, person, statuses, sweep
from tests.integration.test_paid_with import world  # noqa: F401  (the web API tests' app)
from tests.integration.test_wallets import downgrade
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration

BANK = "alerts@uob.com.sg"
FOUND = "Found a new card: UOB ·· 1234. I've added it to Wallets."


def alert(
    message_id: str,
    amount: str = "10.20",
    *,
    sender: str = BANK,
    last4: str = "1234",
    at: Any = NOW,
    merchant: str = "Kopi Corner",
) -> Any:
    body = (
        f"Merchant: {merchant}\nTotal: {amount}\nCurrency: SGD\n"
        f"A transaction of SGD {amount} was made with your Bank Card ending {last4} on "
        f"04/11/26 at {merchant.upper()}."
    )
    return fake_email(message_id, "Card receipt alert", body, sender=sender, at=at)


async def tracking_user(uow: UowFactory, telegram_id: int = 4242) -> User:
    user = await person(uow, telegram_id)
    await set_track_cards(uow(), user.id, True)
    return user


async def inbox(uow: UowFactory, user: User, mailbox: FakeMailbox) -> dict[str, InboundEmail]:
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    found = await email_cases.overview(uow(), user.id, now=NOW + timedelta(days=1))
    return {e.provider_message_id: e for e in found.emails}


async def cards_of(uow: UowFactory, user: User) -> list[Wallet]:
    return [w for w in await list_wallets(uow(), user.id) if w.kind is WalletKind.CARD]


async def sent(engine: AsyncEngine, kind: str) -> list[dict[str, Any]]:
    return [m for m in await messages(engine) if m["kind"] == kind]


# --- adding a card that isn't there yet ----------------------------------------------------


async def test_an_unknown_card_is_added_tagged_and_announced_once(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    mailbox = FakeMailbox({"a1": alert("a1"), "a2": alert("a2", "6.00")})
    emails = await inbox(uow, user, mailbox)

    first = await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    [card] = await cards_of(uow, user)
    assert (card.name, card.issuer, card.last4) == ("UOB card", "UOB", "1234")
    assert card.network is None and card.product is None  # nothing is guessed
    assert first.paid_with_wallet_id == card.id

    # The next email for it matches the card: no second wallet, no second notice.
    second = await email_cases.log_email(uow, user, emails["a2"].id, now=NOW)
    assert second.paid_with_wallet_id == card.id
    assert len(await cards_of(uow, user)) == 1
    [notice] = await sent(engine, "card_found")
    assert notice["text"] == FOUND
    assert notice["buttons"] == [
        [
            {"label": "Keep", "data": f"card:keep:{card.id}"},
            {"label": "Remove", "data": f"card:remove:{card.id}"},
        ]
    ]
    # Like the other questions: held in quiet hours, counted toward the day's limit, and, as
    # it has buttons, still sent when the limit is used up.
    assert notice["level"] == "now"
    assert "card_found" not in UNCAPPED


async def test_a_card_from_an_unknown_sender_is_named_by_its_digits(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    mailbox = FakeMailbox({"a1": alert("a1", sender="alerts@smallbank.test")})
    emails = await inbox(uow, user, mailbox)
    tx = await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    [card] = await cards_of(uow, user)
    assert (card.name, card.issuer, card.last4) == ("Card ·· 1234", None, "1234")
    assert tx.paid_with_wallet_id == card.id
    [notice] = await sent(engine, "card_found")
    assert notice["text"] == "Found a new card: Card ·· 1234. I've added it to Wallets."


async def test_a_taken_name_gets_the_digits_added(uow: UowFactory) -> None:
    user = await tracking_user(uow)
    await add_wallet(uow(), user.id, "UOB card", "card", last4="9999")
    await add_wallet(uow(), user.id, "uob card ·· 1234", "other")  # any case
    mailbox = FakeMailbox({"a1": alert("a1")})
    emails = await inbox(uow, user, mailbox)
    await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    names = sorted(w.name for w in await cards_of(uow, user))
    assert names == ["UOB card", "UOB card ·· 1234 2"]


async def test_two_alerts_for_a_new_card_one_after_another_add_it_once(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1"), "a2": alert("a2", "7.00")}))
    one = await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    two = await email_cases.log_email(uow, user, emails["a2"].id, now=NOW)
    assert one.paid_with_wallet_id == two.paid_with_wallet_id is not None
    assert len(await cards_of(uow, user)) == 1
    assert len(await sent(engine, "card_found")) == 1


async def test_alerts_processed_at_the_same_moment_add_the_card_once(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    mailbox = FakeMailbox({f"a{n}": alert(f"a{n}", f"{n + 5}.00") for n in range(4)})
    emails = await inbox(uow, user, mailbox)
    logged = await asyncio.gather(
        *(email_cases.log_email(uow, user, e.id, now=NOW) for e in emails.values())
    )
    [card] = await cards_of(uow, user)
    assert {t.paid_with_wallet_id for t in logged} == {card.id}
    assert len(await sent(engine, "card_found")) == 1

    # And asked for the same card directly, all at once.
    others = await asyncio.gather(
        *(found_cards.card_for(uow, user.id, "5678", "DBS", now=NOW) for _ in range(5))
    )
    assert len(set(others)) == 1 and others[0] is not None
    assert len(await cards_of(uow, user)) == 2
    assert len(await sent(engine, "card_found")) == 2


async def test_cards_sharing_digits_are_told_apart_by_the_senders_bank(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    uob = await add_wallet(uow(), user.id, "Everyday", "card", issuer="uob", last4="1234")
    citi = await add_wallet(uow(), user.id, "Travel", "card", issuer="Citi", last4="1234")
    mailbox = FakeMailbox(
        {
            "u": alert("u", "3.00"),
            "c": alert("c", "4.00", sender="alerts@citibank.com.sg"),
            "x": alert("x", "5.00", sender="alerts@smallbank.test"),
        }
    )
    emails = await inbox(uow, user, mailbox)
    tagged = {
        key: (await email_cases.log_email(uow, user, emails[key].id, now=NOW)).paid_with_wallet_id
        for key in ("u", "c", "x")
    }
    # An alert from a bank neither card is from names no card, and no third one is added.
    assert tagged == {"u": uob.id, "c": citi.id, "x": None}
    assert len(await cards_of(uow, user)) == 2
    assert await sent(engine, "card_found") == []


async def test_a_card_that_is_there_is_just_matched(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await tracking_user(uow)
    mine = await add_wallet(uow(), user.id, "My Citi", "card", issuer="Citi", last4="1234")
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1")}))  # from UOB, but the one 1234
    tx = await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    assert tx.paid_with_wallet_id == mine.id
    assert len(await cards_of(uow, user)) == 1 and await sent(engine, "card_found") == []


async def test_an_email_that_names_no_card_adds_nothing(uow: UowFactory) -> None:
    user = await tracking_user(uow)
    receipt = fake_email("r1", "Grab receipt", "Merchant: Grab\nTotal: 8.00\nCurrency: SGD")
    emails = await inbox(uow, user, FakeMailbox({"r1": receipt}))
    tx = await email_cases.log_email(uow, user, emails["r1"].id, now=NOW)
    assert tx.paid_with_wallet_id is None and await cards_of(uow, user) == []


# --- Keep and Remove ----------------------------------------------------------------------


async def found_one(uow: UowFactory, user: User) -> tuple[Wallet, UUID]:
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1")}))
    tx = await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    [card] = await cards_of(uow, user)
    return card, tx.id


async def test_keep_only_acknowledges(uow: UowFactory) -> None:
    user = await tracking_user(uow)
    card, tx_id = await found_one(uow, user)
    reply = only(await build(uow, scripted()).press(user.id, f"card:keep:{card.id}"))
    assert reply.text.startswith("Kept.")
    assert [w.id for w in await cards_of(uow, user)] == [card.id]
    assert (await get_transaction(uow(), user.id, tx_id)).paid_with_wallet_id == card.id


async def test_remove_deletes_the_card_and_clears_the_expenses_it_tagged(
    uow: UowFactory,
) -> None:
    user = await tracking_user(uow)
    card, tx_id = await found_one(uow, user)
    bot = build(uow, scripted())
    reply = only(await bot.press(user.id, f"card:remove:{card.id}"))
    assert reply.text == "Removed UOB ·· 1234. 1 expense(s) no longer say which card paid."
    assert await cards_of(uow, user) == []
    kept = await get_transaction(uow(), user.id, tx_id)
    assert kept.paid_with_wallet_id is None and not kept.is_deleted
    again = only(await bot.press(user.id, f"card:remove:{card.id}"))
    assert again.text == "That card is already gone."
    assert only(await bot.press(user.id, "card:remove:not-an-id")).text == (
        "I don't know that button."
    )


@pytest.mark.parametrize("use", ["typed expense", "move", "usual card"])
async def test_remove_refuses_when_anything_else_uses_the_card(uow: UowFactory, use: str) -> None:
    user = await tracking_user(uow)
    card, tx_id = await found_one(uow, user)
    if use == "typed expense":
        await log_transaction(
            uow(),
            user.id,
            NewTransaction(Direction.OUT, Money.of("3", "SGD"), NOW, paid_with_wallet_id=card.id),
        )
    elif use == "move":
        await log_move(
            uow(), user.id, amount=Money.of("50", "SGD"), to_wallet_id=card.id, occurred_at=NOW
        )
    else:
        await set_usual_card(uow(), user.id, card.id)
    reply = only(await build(uow, scripted()).press(user.id, f"card:remove:{card.id}"))
    assert reply.text.startswith("I couldn't remove that card safely")
    assert "Wallets" in reply.text
    assert [w.id for w in await cards_of(uow, user)] == [card.id]
    assert (await get_transaction(uow(), user.id, tx_id)).paid_with_wallet_id == card.id


async def test_remove_cannot_delete_someone_elses_card(uow: UowFactory) -> None:
    ann, ben = await tracking_user(uow, 1), await tracking_user(uow, 2)
    card, _ = await found_one(uow, ann)
    reply = only(await build(uow, scripted()).press(ben.id, f"card:remove:{card.id}"))
    assert reply.text == "That card is already gone."
    assert [w.id for w in await cards_of(uow, ann)] == [card.id]


# --- someone who doesn't track cards -------------------------------------------------------


async def test_off_the_question_is_asked_once_and_no_card_is_added(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    mailbox = FakeMailbox({"a1": alert("a1"), "a2": alert("a2", "6.00", last4="4321")})
    emails = await inbox(uow, user, mailbox)

    first = await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    assert first.paid_with_wallet_id is None and await cards_of(uow, user) == []
    [ask] = await sent(engine, "card_tracking")
    assert ask["text"] == "Your bank emails show which card paid. Turn on card tracking?"
    assert ask["buttons"] == [
        [
            {"label": "Turn on", "data": "card:track:on"},
            {"label": "No thanks", "data": "card:track:no"},
        ]
    ]
    assert ask["level"] == "now"
    assert (await get_user(uow(), user.id)).card_tracking_asked is True

    await email_cases.log_email(uow, user, emails["a2"].id, now=NOW)  # a different card
    assert len(await sent(engine, "card_tracking")) == 1
    assert await sent(engine, "card_found") == [] and await cards_of(uow, user) == []


async def test_alerts_arriving_together_ask_once(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    mailbox = FakeMailbox({f"a{n}": alert(f"a{n}", f"{n + 5}.00") for n in range(4)})
    emails = await inbox(uow, user, mailbox)
    await asyncio.gather(
        *(email_cases.log_email(uow, user, e.id, now=NOW) for e in emails.values())
    )
    assert len(await sent(engine, "card_tracking")) == 1


async def test_a_receipt_without_a_card_does_not_ask(engine: AsyncEngine, uow: UowFactory) -> None:
    user = await person(uow)
    receipt = fake_email("r1", "Grab receipt", "Merchant: Grab\nTotal: 8.00\nCurrency: SGD")
    emails = await inbox(uow, user, FakeMailbox({"r1": receipt}))
    await email_cases.log_email(uow, user, emails["r1"].id, now=NOW)
    assert await sent(engine, "card_tracking") == []
    assert (await get_user(uow(), user.id)).card_tracking_asked is False


async def test_turn_on_switches_tracking_on_for_what_comes_next(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1"), "a2": alert("a2", "6.00")}))
    past = await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)

    reply = only(await build(uow, scripted()).press(user.id, "card:track:on"))
    assert reply.text.startswith("Card tracking is on.")
    now_on = await get_user(uow(), user.id)
    assert (now_on.track_cards, now_on.card_tracking_asked) == (True, True)
    # What was logged before is not tagged afterwards; the next email adds the card.
    assert (await get_transaction(uow(), user.id, past.id)).paid_with_wallet_id is None
    later = await email_cases.log_email(uow, user, emails["a2"].id, now=NOW)
    [card] = await cards_of(uow, user)
    assert later.paid_with_wallet_id == card.id
    assert len(await sent(engine, "card_tracking")) == 1


async def test_no_thanks_means_never_again_and_leaves_the_setting_alone(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1"), "a2": alert("a2", "6.00")}))
    await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    reply = only(await build(uow, scripted()).press(user.id, "card:track:no"))
    assert reply.text.startswith("OK, I won't ask again")
    declined = await get_user(uow(), user.id)
    assert (declined.track_cards, declined.card_tracking_asked) == (False, True)
    await email_cases.log_email(uow, user, emails["a2"].id, now=NOW)
    assert len(await sent(engine, "card_tracking")) == 1

    # A stale "No thanks" does not switch off what the user has since turned on.
    await set_track_cards(uow(), user.id, True)
    await build(uow, scripted()).press(user.id, "card:track:no")
    assert (await get_user(uow(), user.id)).track_cards is True


async def test_choosing_the_setting_yourself_means_never_being_asked(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await person(uow)
    await set_track_cards(uow(), user.id, False)  # chose simple mode on purpose
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1")}))
    await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    assert await sent(engine, "card_tracking") == []


async def test_the_preferences_endpoint_marks_the_user_as_asked(
    world: World,  # noqa: F811
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    async with world.engine.connect() as db:
        before: bool = (
            await db.execute(text("SELECT card_tracking_asked FROM users"))
        ).scalar_one()
    assert before is False
    put = await owner.send("PUT", "/api/settings/preferences", {"track_cards": False})
    assert put.status_code == 200
    async with world.engine.connect() as db:
        after: bool = (await db.execute(text("SELECT card_tracking_asked FROM users"))).scalar_one()
    assert after is True


async def test_a_user_with_no_chat_is_not_asked_yet(uow: UowFactory) -> None:
    registration = await register_user(
        uow(), RegisterUser(telegram_user_id=7001, home_currency="SGD", timezone="Asia/Singapore")
    )
    user = registration.user
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1")}))
    await email_cases.log_email(uow, user, emails["a1"].id, now=NOW)
    # Nobody to ask: it is left for when there is, not used up.
    assert (await get_user(uow(), user.id)).card_tracking_asked is False


# --- the same payment, twice ---------------------------------------------------------------


async def typed(uow: UowFactory, user: User, merchant: str = "Kopi Corner") -> UUID:
    tx = await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            Direction.OUT,
            Money.of("10.20", "SGD"),
            NOW - timedelta(hours=2),
            counterparty=merchant,
        ),
    )
    return tx.id


async def test_a_bank_alert_for_an_entry_already_logged_is_asked_about_and_gives_it_the_card(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    mine = await add_wallet(uow(), user.id, "Everyday", "card", issuer="UOB", last4="1234")
    entry = await typed(uow, user)
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1", at=NOW - timedelta(hours=1))}))
    twin = email_cases.duplicate_of(emails["a1"])
    assert twin is not None and twin["transaction_id"] == str(entry)  # it is found

    kept = await email_cases.same_payment(uow, user, emails["a1"].id, now=NOW)
    assert kept is not None and kept.id == entry
    assert kept.paid_with_wallet_id == mine.id  # copied from the alert
    assert (await get_transaction(uow(), user.id, entry)).paid_with_wallet_id == mine.id
    assert await statuses(uow, user) == {"a1": "logged"}


async def test_the_card_is_not_copied_when_the_kept_entry_has_one_or_tracking_is_off(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    mine = await add_wallet(uow(), user.id, "Everyday", "card", issuer="UOB", last4="1234")
    other = await add_wallet(uow(), user.id, "Travel", "card", issuer="Citi", last4="4321")
    tx = await log_transaction(
        uow(),
        user.id,
        NewTransaction(
            Direction.OUT,
            Money.of("10.20", "SGD"),
            NOW - timedelta(hours=2),
            counterparty="Kopi Corner",
            paid_with_wallet_id=other.id,
        ),
    )
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1", at=NOW - timedelta(hours=1))}))
    kept = await email_cases.same_payment(uow, user, emails["a1"].id, now=NOW)
    assert kept is not None and kept.id == tx.id and kept.paid_with_wallet_id == other.id

    # Tracking off: nothing is copied, though the user is asked once.
    simple = await person(uow, 5151)
    entry = await typed(uow, simple)
    second = await inbox(uow, simple, FakeMailbox({"a1": alert("a1", at=NOW - timedelta(hours=1))}))
    done = await email_cases.same_payment(uow, simple, second["a1"].id, now=NOW)
    assert done is not None and done.id == entry and done.paid_with_wallet_id is None
    assert mine.id not in {w.id for w in await cards_of(uow, simple)}
    assert len(await sent(engine, "card_tracking")) == 1


async def test_an_unknown_card_on_the_alert_is_added_when_it_is_copied(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    user = await tracking_user(uow)
    entry = await typed(uow, user)
    emails = await inbox(uow, user, FakeMailbox({"a1": alert("a1", at=NOW - timedelta(hours=1))}))
    kept = await email_cases.same_payment(uow, user, emails["a1"].id, now=NOW)
    [card] = await cards_of(uow, user)
    assert kept is not None and kept.id == entry and kept.paid_with_wallet_id == card.id
    assert [m["text"] for m in await sent(engine, "card_found")] == [FOUND]


async def test_a_shop_receipt_waiting_takes_the_card_from_the_bank_alert(
    uow: UowFactory,
) -> None:
    user = await tracking_user(uow)
    mine = await add_wallet(uow(), user.id, "Everyday", "card", issuer="UOB", last4="1234")
    receipt = fake_email(
        "r1",
        "Your Kopi receipt",
        "Merchant: Kopi Corner Pte Ltd\nTotal: 10.20\nCurrency: SGD",
        sender="orders@kopi.test",
        at=NOW - timedelta(hours=2),
    )
    mailbox = FakeMailbox({"r1": receipt, "a1": alert("a1", at=NOW - timedelta(hours=1))})
    emails = await inbox(uow, user, mailbox)
    twin = email_cases.duplicate_of(emails["a1"])
    assert twin is not None and twin["email_id"] == str(emails["r1"].id)

    assert await email_cases.same_payment(uow, user, emails["a1"].id, now=NOW) is None
    tx = await email_cases.log_email(uow, user, emails["r1"].id, now=NOW)
    assert tx.paid_with_wallet_id == mine.id  # the receipt had no card; the alert did
    assert await statuses(uow, user) == {"r1": "logged", "a1": "duplicate"}


async def test_a_bank_alert_for_a_receipt_already_logged_from_email_is_the_same_payment(
    uow: UowFactory,
) -> None:
    """The other order: the shop's receipt was logged first, the bank's alert comes after."""
    user = await tracking_user(uow)
    mine = await add_wallet(uow(), user.id, "Everyday", "card", issuer="UOB", last4="1234")
    receipt = fake_email(
        "r1",
        "Your Kopi receipt",
        "Merchant: Kopi Corner Pte Ltd\nTotal: 10.20\nCurrency: SGD",
        sender="orders@kopi.test",
        at=NOW - timedelta(hours=2),
    )
    mailbox = FakeMailbox({"r1": receipt})
    emails = await inbox(uow, user, mailbox)
    logged = await email_cases.log_email(uow, user, emails["r1"].id, now=NOW)
    assert logged.paid_with_wallet_id is None
    mailbox.emails["a1"] = alert("a1", at=NOW + timedelta(minutes=1))
    connection = (await email_cases.overview(uow(), user.id, now=NOW)).connections[0]
    await sweep(uow, user, mailbox, connection, at=NOW + timedelta(minutes=5))
    waiting = await email_cases.waiting(uow(), user.id, now=NOW)
    [bank] = [e for e in waiting if e.provider_message_id == "a1"]
    twin = email_cases.duplicate_of(bank)
    assert twin is not None and twin["transaction_id"] == str(logged.id)

    kept = await email_cases.same_payment(uow, user, bank.id, now=NOW)
    assert kept is not None and kept.id == logged.id and kept.paid_with_wallet_id == mine.id


async def test_a_second_alert_at_the_same_price_is_a_second_payment(uow: UowFactory) -> None:
    """Two alerts are two payments (same subject), so one is never folded into the other
    and no card moves between them."""
    user = await tracking_user(uow)
    mailbox = FakeMailbox(
        {
            "a1": alert("a1", at=NOW - timedelta(hours=3)),
            "a2": alert("a2", at=NOW - timedelta(hours=1)),
        }
    )
    emails = await inbox(uow, user, mailbox)
    assert [email_cases.duplicate_of(e) for e in emails.values()] == [None, None]


# --- migration 0067 ------------------------------------------------------------------------


async def test_the_migration_adds_the_asked_flag_false_for_everyone(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0066")
    engine = make_engine(empty_database_url)
    try:
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, "
                    "home_currency, role, track_cards) VALUES (gen_random_uuid(), 810, 'UTC', "
                    "'UTC', 'SGD', 'owner', true)"
                )
            )
        await upgrade(empty_database_url, "0067")
        async with engine.connect() as db:
            before: bool = (
                await db.execute(text("SELECT card_tracking_asked FROM users"))
            ).scalar_one()
        assert before is False  # nobody was asked, whatever they track

        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, "
                    "home_currency, role) VALUES (gen_random_uuid(), 811, 'UTC', 'UTC', "
                    "'SGD', 'owner')"
                )
            )
            fresh: bool = (
                await db.execute(
                    text("SELECT card_tracking_asked FROM users WHERE telegram_user_id = 811")
                )
            ).scalar_one()
        assert fresh is False
        async with engine.connect() as db:
            nullable: str = (
                await db.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns WHERE "
                        "table_name = 'users' AND column_name = 'card_tracking_asked'"
                    )
                )
            ).scalar_one()
        assert nullable == "NO"

        await downgrade(empty_database_url, "0066")
        async with engine.connect() as db:
            left: int = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns WHERE "
                        "table_name = 'users' AND column_name = 'card_tracking_asked'"
                    )
                )
            ).scalar_one()
            kept: int = (await db.execute(text("SELECT count(*) FROM users"))).scalar_one()
        assert (left, kept) == (0, 2)
    finally:
        await engine.dispose()


def test_found_card_notices_are_one_shot_buttons() -> None:
    from nexus.channels.telegram.webhook import ONE_SHOT

    assert found_cards.PREFIX in ONE_SHOT
