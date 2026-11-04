"""The "track which card paid" preference (``users.track_cards``), off by default ("simple
mode"): what it changes when it is off and on, over the API, in chat, for emails and imports,
for demos, and the migration that keeps everyone who already used cards. Made-up data only."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from nexus.agent.snapshot import money_snapshot
from nexus.agent.tools import ToolContext
from nexus.application import email as email_cases
from nexus.application import statements as statement_cases
from nexus.application import wallets as wallet_cases
from nexus.application.ports import LedgerQuery
from nexus.application.transactions import get_transaction, list_ledger
from nexus.application.users import get_user, set_track_cards
from nexus.domain.ledger import Direction, UserId
from nexus.infra.db.engine import make_engine
from tests.fakes import NOW, FakeMailbox, call, fake_email, say, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build
from tests.integration.test_email import connect, person, sweep
from tests.integration.test_paid_with import (
    STATEMENT,
    add_card,
    cards,
    expense,
    put_on,
    run,
    track_cards,
    world,  # noqa: F401  (the web API tests' app, as a fixture here too)
)
from tests.integration.test_wallets import downgrade
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration


# --- the setting -------------------------------------------------------------------------


async def test_a_new_user_starts_in_simple_mode_and_the_setting_round_trips(
    uow: UowFactory, alice: UserId
) -> None:
    assert (await get_user(uow(), alice)).track_cards is False
    assert await set_track_cards(uow(), alice, True) is True
    assert (await get_user(uow(), alice)).track_cards is True
    assert await set_track_cards(uow(), alice, False) is False
    assert (await get_user(uow(), alice)).track_cards is False


async def test_me_shows_the_preference_and_the_endpoint_changes_it(world: World) -> None:  # noqa: F811
    owner = world.browser()
    await owner.login(OWNER)
    assert (await owner.get("/api/me")).json()["preferences"] == {"track_cards": False}

    on = await owner.send("PUT", "/api/settings/preferences", {"track_cards": True})
    assert on.status_code == 200 and on.json() == {"track_cards": True}
    assert (await owner.get("/api/me")).json()["preferences"] == {"track_cards": True}

    off = await owner.send("PUT", "/api/settings/preferences", {"track_cards": False})
    assert off.json() == {"track_cards": False}
    assert (await owner.get("/api/me")).json()["preferences"] == {"track_cards": False}


async def test_the_preference_endpoint_is_strict_and_needs_a_session_and_csrf(
    world: World,  # noqa: F811
) -> None:
    owner = world.browser()
    assert (
        await owner.client.put("/api/settings/preferences", json={"track_cards": True})
    ).status_code == 401  # not signed in
    await owner.login(OWNER)
    for bad in ({}, {"track_cards": "maybe"}, {"track_cards": True, "other": 1}):
        refused = await owner.send("PUT", "/api/settings/preferences", bad)
        assert refused.status_code == 422, bad
    owner.csrf = "wrong"
    blocked = await owner.send("PUT", "/api/settings/preferences", {"track_cards": True})
    assert blocked.status_code in (400, 403)
    owner.csrf = (await owner.get("/api/me")).json()["csrf_token"]
    assert (await owner.get("/api/me")).json()["preferences"] == {"track_cards": False}


# --- the usual card ------------------------------------------------------------------------


async def test_off_the_usual_card_is_not_applied_and_on_it_is_again(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    citi, dbs = found["Citi PremierMiles"], found["DBS Altitude"]
    await wallet_cases.set_usual_card(uow(), alice, citi.id)
    assert (await expense(uow, alice, use_usual_card=True)).paid_with_wallet_id == citi.id

    await set_track_cards(uow(), alice, False)
    off = await expense(uow, alice, use_usual_card=True)
    assert off.paid_with_wallet_id is None
    # Said outright, a wallet is still taken (an API client); the usual card is kept.
    said = await expense(uow, alice, use_usual_card=True, paid_with_wallet_id=dbs.id)
    assert said.paid_with_wallet_id == dbs.id
    assert (await get_user(uow(), alice)).usual_card_wallet_id == citi.id

    await set_track_cards(uow(), alice, True)
    assert (await expense(uow, alice, use_usual_card=True)).paid_with_wallet_id == citi.id
    # What was stored while it was off was never touched.
    assert (await get_transaction(uow(), alice, said.id)).paid_with_wallet_id == dbs.id


async def test_over_the_api_off_means_no_usual_card_but_a_sent_wallet_is_taken(
    world: World,  # noqa: F811
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    citi = await add_card(owner, "Citi PremierMiles")
    dbs = await add_card(owner, "DBS Altitude")
    await owner.send("PUT", "/api/wallets/usual-card", {"wallet_id": citi["id"]})

    assert (await put_on(owner, "5"))["paid_with"] is None  # simple mode
    sent = await put_on(owner, "5", paid_with_wallet_id=dbs["id"])
    assert sent["paid_with"]["name"] == "DBS Altitude"

    await track_cards(owner)
    assert (await put_on(owner, "5"))["paid_with"]["name"] == "Citi PremierMiles"
    await track_cards(owner, False)
    assert (await put_on(owner, "5"))["paid_with"] is None
    # Reading keeps returning what is stored.
    listed = (await owner.get("/api/transactions", params={"paid_with": dbs["id"]})).json()
    assert listed["total"] == 1 and listed["items"][0]["paid_with"]["name"] == "DBS Altitude"


# --- emails and imports --------------------------------------------------------------------


async def test_off_an_email_does_not_match_its_card_and_on_it_does(uow: UowFactory) -> None:
    user = await person(uow)
    found = await cards(uow, user.id, track=False)
    grab = "Merchant: Grab\nTotal: 18.50\nCurrency: SGD\nDate: 2026-09-27"
    mailbox = FakeMailbox(
        {
            "m1": fake_email("m1", "Grab receipt", f"{grab}\nPaid with card ending 8765"),
            "m2": fake_email("m2", "Grab receipt", f"{grab}\nPaid with card ending 8765\nB"),
        }
    )
    connection = await connect(uow, user, mailbox)
    await sweep(uow, user, mailbox, connection)
    inbox = {
        e.provider_message_id: e
        for e in (await email_cases.overview(uow(), user.id, now=NOW)).emails
    }

    off = await email_cases.log_email(uow, user, inbox["m1"].id, now=NOW)
    assert off.paid_with_wallet_id is None  # simple mode: the last four digits are not matched
    await set_track_cards(uow(), user.id, True)
    on = await email_cases.log_email(uow, user, inbox["m2"].id, now=NOW)
    assert on.paid_with_wallet_id == found["DBS Altitude"].id


async def test_off_a_statement_import_is_not_tagged_with_a_card(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice, track=False)
    dbs = found["DBS Altitude"]
    user = await get_user(uow(), alice)
    shown = await statement_cases.preview(uow, user, STATEMENT)
    assert shown.mapping is not None

    off = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {0}, file_name="a.csv", paid_with=dbs.id, now=NOW
    )
    [first] = off.record.transaction_ids
    assert (await get_transaction(uow(), alice, first)).paid_with_wallet_id is None
    # Not even a bad wallet is complained about: the tag is skipped altogether.
    skipped = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {2}, file_name="b.csv", paid_with=uuid4(), now=NOW
    )
    assert len(skipped.record.transaction_ids) == 1

    await set_track_cards(uow(), alice, True)
    done = await statement_cases.confirm(
        uow, user, STATEMENT, shown.mapping, {1}, file_name="c.csv", paid_with=dbs.id, now=NOW
    )
    [second] = done.record.transaction_ids
    assert (await get_transaction(uow(), alice, second)).paid_with_wallet_id == dbs.id


async def test_the_import_api_skips_the_card_when_off(world: World) -> None:  # noqa: F811
    owner = world.browser()
    await owner.login(OWNER)
    citi = await add_card(owner, "Citi PremierMiles")
    body = {
        "csv": STATEMENT,
        "layout": {"date": 0, "description": [1, 4], "debit": 2, "credit": 3},
        "include": [0, 1, 2],
        "file_name": "sept.csv",
        "paid_with_wallet_id": citi["id"],
    }
    sent = await owner.send("POST", "/api/imports", body)
    assert sent.status_code == 201, sent.text
    found = (await owner.get("/api/transactions", params={"paid_with": citi["id"]})).json()
    assert found["total"] == 0


# --- chat ---------------------------------------------------------------------------------


async def test_off_log_expense_ignores_paid_with_and_the_usual_card(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    await wallet_cases.set_usual_card(uow(), alice, found["Citi PremierMiles"].id)
    await set_track_cards(uow(), alice, False)

    said = await run(uow, alice, "log_expense", {"amount": "12.50", "paid_with": "dbs"})
    assert said.startswith("Logged: ") and "paid with" not in said
    plain = await run(uow, alice, "log_expense", {"amount": "6", "merchant": "Toast Box"})
    assert "paid with" not in plain and "usual card" not in plain
    # An unknown card is not asked about either: the argument is ignored altogether.
    unknown = await run(uow, alice, "log_expense", {"amount": "7", "paid_with": "amex"})
    assert unknown.startswith("Logged: ")
    page = await list_ledger(uow(), alice, LedgerQuery())
    assert page.total == 3 and all(t.paid_with_wallet_id is None for t in page.items)

    await set_track_cards(uow(), alice, True)
    on = await run(uow, alice, "log_expense", {"amount": "8", "paid_with": "dbs"})
    assert "paid with DBS Altitude" in on


async def test_off_a_photo_receipt_does_not_use_the_usual_card(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    await wallet_cases.set_usual_card(uow(), alice, found["DBS Altitude"].id)
    await set_track_cards(uow(), alice, False)
    result = await run(
        uow, alice, "log_receipt_expense",
        {"amount": "9.40", "merchant": "Ya Kun", "external_id": "photo-1"},
    )  # fmt: skip
    assert "paid with" not in result


async def test_off_edit_transaction_ignores_paid_with_and_stored_cards_stay(
    uow: UowFactory, alice: UserId
) -> None:
    found = await cards(uow, alice)
    citi, dbs = found["Citi PremierMiles"], found["DBS Altitude"]
    tx = await expense(uow, alice, paid_with_wallet_id=citi.id)
    await set_track_cards(uow(), alice, False)

    changed = await run(
        uow, alice, "edit_transaction",
        {"transaction_id": str(tx.id), "paid_with": "dbs", "notes": "lunch"},
    )  # fmt: skip
    assert changed.startswith("Updated: ") and "paid with" not in changed
    cleared = await run(
        uow, alice, "edit_transaction", {"transaction_id": str(tx.id), "paid_with": "none"}
    )
    assert cleared.startswith("Updated: ")
    stored = await get_transaction(uow(), alice, tx.id)
    assert stored.paid_with_wallet_id == citi.id and stored.notes == "lunch"  # never changed
    found_text = await run(uow, alice, "find_transactions", {})
    assert "paid with" not in found_text  # not shown to the model while off

    await set_track_cards(uow(), alice, True)
    on = await run(
        uow, alice, "edit_transaction", {"transaction_id": str(tx.id), "paid_with": "dbs"}
    )
    assert "paid with DBS Altitude" in on
    assert (await get_transaction(uow(), alice, tx.id)).paid_with_wallet_id == dbs.id


async def test_off_the_confirmation_does_not_mention_a_card(uow: UowFactory, alice: UserId) -> None:
    await cards(uow, alice, track=False)
    tx = await expense(uow, alice)
    model = scripted(
        call("edit_transaction", transaction_id=str(tx.id), paid_with="dbs", notes="lunch"),
        say("Done."),
    )
    [ask] = await build(uow, model).handle_text(alice, "that was on my DBS card", "tg:1:1")
    assert "paid with" not in ask.text and "notes → lunch" in ask.text


async def test_off_set_usual_card_saves_nothing_and_says_why(
    uow: UowFactory, alice: UserId
) -> None:
    await cards(uow, alice, track=False)
    said = await run(uow, alice, "set_usual_card", {"wallet": "citi"})
    assert "isn't tracking which card paid" in said
    assert (await get_user(uow(), alice)).usual_card_wallet_id is None

    await set_track_cards(uow(), alice, True)
    assert "is now the usual card" in await run(uow, alice, "set_usual_card", {"wallet": "citi"})
    assert (await get_user(uow(), alice)).usual_card_wallet_id is not None


async def test_the_turn_context_says_card_tracking_is_off_only_when_it_is(
    uow: UowFactory, alice: UserId
) -> None:
    await cards(uow, alice, track=False)

    async def snapshot() -> str:
        return await money_snapshot(ToolContext(await get_user(uow(), alice), uow, NOW))

    off = await snapshot()
    assert off.startswith("Card tracking is off: don't ask which card paid")
    assert "Citi PremierMiles" in off  # the cards are still there, for paying a card's bill
    await set_track_cards(uow(), alice, True)
    assert "Card tracking is off" not in await snapshot()


async def test_paying_a_card_bill_is_a_move_and_works_with_tracking_off(
    uow: UowFactory, alice: UserId
) -> None:
    await cards(uow, alice, track=False)
    moved = await run(uow, alice, "log_move", {"amount": "200", "to_wallet": "Citi PremierMiles"})
    assert "(move)" in moved and "Citi PremierMiles" in moved
    page = await list_ledger(uow(), alice, LedgerQuery())
    assert [t.direction for t in page.items] == [Direction.MOVE] * len(page.items)
    assert all(t.paid_with_wallet_id is None for t in page.items)


# --- the migration ---------------------------------------------------------------------------


async def test_the_migration_keeps_cards_tracked_for_those_who_used_them(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0065")
    engine = make_engine(empty_database_url)
    usual, paid, both, neither = uuid4(), uuid4(), uuid4(), uuid4()
    wallets: dict[UUID, UUID] = {}
    try:
        async with engine.begin() as db:
            for n, user in enumerate((usual, paid, both, neither)):
                await db.execute(
                    text(
                        "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, "
                        "home_currency, role) VALUES (:id, :tg, 'UTC', 'UTC', 'SGD', 'owner')"
                    ),
                    {"id": user, "tg": 800 + n},
                )
                wallets[user] = uuid4()
                await db.execute(
                    text(
                        "INSERT INTO wallets (id, user_id, name, kind) "
                        "VALUES (:w, :u, 'Card', 'card')"
                    ),
                    {"w": wallets[user], "u": user},
                )
            for user in (usual, both):
                await db.execute(
                    text("UPDATE users SET usual_card_wallet_id = :w WHERE id = :u"),
                    {"w": wallets[user], "u": user},
                )
            # An expense paid with a card, for two of them; an expense paid with nothing for the
            # last (money out, no wallet named).
            for user, wallet in ((paid, wallets[paid]), (both, wallets[both]), (neither, None)):
                await db.execute(
                    text(
                        "INSERT INTO transactions (id, user_id, direction, amount, currency, "
                        "occurred_at, status, source, created_at, updated_at, "
                        "paid_with_wallet_id) VALUES (gen_random_uuid(), :u, 'out', 5, 'SGD', "
                        "now(), 'confirmed', 'manual', now(), now(), :w)"
                    ),
                    {"u": user, "w": wallet},
                )

        await upgrade(empty_database_url, "0066")
        async with engine.connect() as db:
            rows = (await db.execute(text("SELECT id, track_cards FROM users"))).all()
        tracked = {r.id: r.track_cards for r in rows}
        assert tracked == {usual: True, paid: True, both: True, neither: False}

        # A user made after it starts in simple mode.
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, "
                    "home_currency, role) VALUES (gen_random_uuid(), 899, 'UTC', 'UTC', "
                    "'SGD', 'owner')"
                )
            )
            fresh: bool = (
                await db.execute(text("SELECT track_cards FROM users WHERE telegram_user_id = 899"))
            ).scalar_one()
        assert fresh is False

        await downgrade(empty_database_url, "0065")
        async with engine.connect() as db:
            left: int = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'users' AND column_name = 'track_cards'"
                    )
                )
            ).scalar_one()
        assert left == 0
    finally:
        await engine.dispose()
