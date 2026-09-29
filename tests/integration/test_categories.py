"""Every transaction gets a category, the new defaults reach existing users, and
users can add, rename and archive their own."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from nexus.application import category_rules as rule_cases
from nexus.application import email as email_cases
from nexus.application.categories import list_categories
from nexus.application.users import DEFAULT_CATEGORIES
from nexus.infra.db.engine import make_engine
from tests.fakes import NOW, FakeEmailReader, FakeMailbox, call, fake_email, say, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, only, tool_results
from tests.integration.test_email import CIPHER, connect, person

pytestmark = pytest.mark.integration


async def names(uow: UowFactory, user_id: object) -> list[str]:
    return [c.name for c in await list_categories(uow(), user_id)]  # type: ignore[arg-type]


async def test_new_users_get_the_eleven_defaults(uow: UowFactory) -> None:
    user = await person(uow)
    assert sorted(await names(uow, user.id)) == sorted(DEFAULT_CATEGORIES)
    assert len(DEFAULT_CATEGORIES) == 11


async def test_existing_users_get_the_new_defaults(empty_database_url: str) -> None:
    await upgrade(empty_database_url, "0013")
    engine = make_engine(empty_database_url)
    ann, ben = uuid4(), uuid4()
    old = ("Food & Drink", "Groceries", "Transport", "Entertainment", "Other", "Income")
    try:
        async with engine.begin() as db:
            for n, user in enumerate((ann, ben)):
                await db.execute(
                    text(
                        "INSERT INTO users (id, telegram_user_id, timezone, home_currency, role) "
                        "VALUES (:id, :tg, 'Asia/Singapore', 'SGD', 'owner')"
                    ),
                    {"id": user, "tg": 100 + n},
                )
                for name in old:
                    await db.execute(
                        text("INSERT INTO categories (id, user_id, name) VALUES (:id, :u, :n)"),
                        {"id": uuid4(), "u": user, "n": name},
                    )
            # Ben already made his own "Dining Out": both are kept as they are.
            await db.execute(
                text("INSERT INTO categories (id, user_id, name) VALUES (:id, :u, 'dining out')"),
                {"id": uuid4(), "u": ben},
            )
        await upgrade(empty_database_url)
        async with engine.connect() as db:
            rows = (await db.execute(text("SELECT user_id, name FROM categories"))).all()
    finally:
        await engine.dispose()
    ann_names = sorted(r.name for r in rows if r.user_id == ann)
    ben_names = sorted(r.name for r in rows if r.user_id == ben)
    assert ann_names == sorted(DEFAULT_CATEGORIES)  # renamed, and the missing ones added
    assert "Food & Drink" in ben_names and "dining out" in ben_names
    assert "Dining Out" not in ben_names  # no duplicate of his own
    assert {"Activities", "Socialising", "Health"} <= set(ben_names)


async def test_the_models_guess_files_an_expense_unless_a_rule_or_the_user_decides(
    uow: UowFactory,
) -> None:
    user = await person(uow)
    cats = {c.name: c.id for c in await list_categories(uow(), user.id)}
    await rule_cases.set_rule(uow(), user, "grab", cats["Transport"], now=NOW)
    model = scripted(
        call("log_expense", amount="8", merchant="Toast Box", best_guess_category="Dining Out"),
        say("ok"),
        call("log_expense", amount="12", merchant="Grab", best_guess_category="Activities"),
        say("ok"),
        call(
            "log_expense",
            amount="15",
            merchant="Grab",
            category="Socialising",
            best_guess_category="Transport",
        ),
        say("ok"),
        call("log_expense", amount="3", merchant="Thing", best_guess_category="Made Up"),
        say("ok"),
    )
    agent = build(uow, model)
    await agent.handle_text(user.id, "toast box 8", "tg:1:1")
    assert "Toast Box · Dining Out" in tool_results(model)[-1]  # the guess
    await agent.handle_text(user.id, "grab 12", "tg:1:2")
    assert "Grab · Transport" in tool_results(model)[-1]  # the rule beats the guess
    await agent.handle_text(user.id, "grab to the party 15, socialising", "tg:1:3")
    assert "Grab · Socialising" in tool_results(model)[-1]  # the user beats the rule
    await agent.handle_text(user.id, "thing 3", "tg:1:4")
    assert "Thing · Other" in tool_results(model)[-1]  # an unknown guess: Other


async def test_email_receipts_use_the_readers_category(uow: UowFactory) -> None:
    user = await person(uow)
    mailbox = FakeMailbox(
        {
            "m1": fake_email(
                "m1", "Grab receipt", "Merchant: Kopitiam\nTotal: 6.50\nCategory: Dining Out"
            )
        }
    )
    connection = await connect(uow, user, mailbox)
    await email_cases.sweep(
        uow, mailbox, FakeEmailReader(), CIPHER, None, user, connection, now=NOW
    )
    [email] = (await email_cases.overview(uow(), user.id, now=NOW)).emails
    tx = await email_cases.log_email(uow, user, email.id, now=NOW)
    cats = {c.id: c.name for c in await list_categories(uow(), user.id)}
    assert cats[tx.category_id] == "Dining Out"  # type: ignore[index]


async def test_users_add_rename_and_archive_their_own(uow: UowFactory) -> None:
    user = await person(uow)
    model = scripted(
        call("add_category", category="Pets"),
        say("Added."),
        call("add_category", category="pets"),
        say("Already there."),
        call("rename_category", category="Activities", new_name="Hobbies"),
        say("Renamed."),
        call("rename_category", category="Hobbies", new_name="Travel"),
        say("Taken."),
        call("archive_category", category="Travel"),
        say("Archived."),
    )
    agent = build(uow, model)
    await agent.handle_text(user.id, "add a category for pets", "tg:1:1")
    assert tool_results(model)[-1] == "Added the category Pets."
    await agent.handle_text(user.id, "add pets", "tg:1:2")
    assert tool_results(model)[-1] == "There's already a category called Pets."
    await agent.handle_text(user.id, "call activities hobbies", "tg:1:3")
    assert tool_results(model)[-1].startswith("Renamed Activities to Hobbies.")
    await agent.handle_text(user.id, "rename hobbies to travel", "tg:1:4")
    assert "already a category called Travel" in tool_results(model)[-1]
    ask = only(await agent.handle_text(user.id, "I don't need travel", "tg:1:5"))
    assert ask.text.startswith("Stop using the category Travel?")
    assert "Travel" in await names(uow, user.id)  # nothing until confirmed
    await agent.resolve(user.id, ask.buttons[0][0].data.split(":")[1], True)
    current = await names(uow, user.id)
    assert "Travel" not in current and {"Pets", "Hobbies"} <= set(current)

    # Adding an archived one brings it back.
    again = scripted(call("add_category", category="travel"), say("Back."))
    await build(uow, again).handle_text(user.id, "add travel back", "tg:1:6")
    assert tool_results(again) == ["Brought back Travel."]
