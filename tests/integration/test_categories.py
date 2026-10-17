"""Every transaction gets a category, the new defaults reach existing users, and
users can add, rename and delete their own."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from nexus.application import budgets as budget_cases
from nexus.application import categories as category_cases
from nexus.application import category_rules as rule_cases
from nexus.application import email as email_cases
from nexus.application.categories import list_categories
from nexus.application.transactions import (
    TransactionChanges,
    edit_transaction,
    get_transaction,
    log_transaction,
    undo_last,
)
from nexus.application.users import DEFAULT_CATEGORIES
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.money import Money
from nexus.infra.db.engine import make_engine
from tests.fakes import NOW, FakeEmailReader, FakeMailbox, call, fake_email, say, scripted
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, only, tool_results
from tests.integration.test_email import CIPHER, connect, person
from tests.integration.test_transactions import spend

pytestmark = pytest.mark.integration


async def names(uow: UowFactory, user_id: object) -> list[str]:
    return [c.name for c in await list_categories(uow(), user_id)]  # type: ignore[arg-type]


async def test_new_users_get_the_twelve_defaults(uow: UowFactory) -> None:
    user = await person(uow)
    assert sorted(await names(uow, user.id)) == sorted(DEFAULT_CATEGORIES)
    assert len(DEFAULT_CATEGORIES) == 12


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


async def test_the_old_bots_dining_and_general_fold_into_the_defaults(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0014")
    engine = make_engine(empty_database_url)
    ann, ben = uuid4(), uuid4()
    cat = {
        name: uuid4()
        for name in ("ann:Dining", "ann:Dining Out", "ann:General", "ann:Other", "ben:dining")
    }
    spent = [uuid4(), uuid4(), uuid4()]
    rule = uuid4()
    try:
        async with engine.begin() as db:
            for n, user in enumerate((ann, ben)):
                await db.execute(
                    text(
                        "INSERT INTO users (id, telegram_user_id, timezone, home_currency, role) "
                        "VALUES (:id, :tg, 'Asia/Singapore', 'SGD', 'owner')"
                    ),
                    {"id": user, "tg": 200 + n},
                )
            for key, cid in cat.items():
                owner, name = key.split(":")
                await db.execute(
                    text("INSERT INTO categories (id, user_id, name) VALUES (:id, :u, :n)"),
                    {"id": cid, "u": ann if owner == "ann" else ben, "n": name},
                )
            for tx, (user, category) in zip(
                spent,
                [(ann, cat["ann:Dining"]), (ann, cat["ann:General"]), (ben, cat["ben:dining"])],
                strict=True,
            ):
                await db.execute(
                    text(
                        "INSERT INTO transactions (id, user_id, direction, amount, currency, "
                        "occurred_at, category_id, status, source, created_at, updated_at) "
                        "VALUES (:id, :u, 'out', 5, 'SGD', now(), :c, 'confirmed', 'text', "
                        "now(), now())"
                    ),
                    {"id": tx, "u": user, "c": category},
                )
            await db.execute(
                text(
                    "INSERT INTO category_rules (id, user_id, pattern, category_id, explanation, "
                    "created_at, updated_at) VALUES (:id, :u, 'kopi', :c, 'x', now(), now())"
                ),
                {"id": rule, "u": ann, "c": cat["ann:Dining"]},
            )
            # Ann budgets Dining; General and Other both have budgets already.
            for category in (cat["ann:Dining"], cat["ann:General"], cat["ann:Other"]):
                await db.execute(
                    text(
                        "INSERT INTO budgets (id, user_id, category_id, amount, currency, "
                        "created_at, updated_at) VALUES (:id, :u, :c, 100, 'SGD', now(), now())"
                    ),
                    {"id": uuid4(), "u": ann, "c": category},
                )
        await upgrade(empty_database_url)
        async with engine.connect() as db:
            txs = await db.execute(text("SELECT id, category_id FROM transactions"))
            tx_cats: dict[UUID, UUID] = {r.id: r.category_id for r in txs}
            rules = await db.execute(text("SELECT category_id FROM category_rules"))
            rule_cat: UUID = rules.scalar_one()
            budgets = await db.execute(text("SELECT category_id FROM budgets"))
            budget_cats = sorted(str(r.category_id) for r in budgets)
            cats = await db.execute(text("SELECT id FROM categories"))
            kept = {r.id for r in cats}
    finally:
        await engine.dispose()
    assert tx_cats[spent[0]] == cat["ann:Dining Out"]
    assert tx_cats[spent[1]] == cat["ann:Other"]
    assert tx_cats[spent[2]] == cat["ben:dining"]  # Ben has no Dining Out: left alone
    assert rule_cat == cat["ann:Dining Out"]
    # Dining's budget moved; General's stayed, since Other already had one, and went
    # with General when the emptied category was deleted.
    assert budget_cats == sorted(str(c) for c in (cat["ann:Dining Out"], cat["ann:Other"]))
    assert cat["ann:Dining"] not in kept and cat["ann:General"] not in kept
    assert cat["ann:Dining Out"] in kept and cat["ben:dining"] in kept


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


async def test_users_add_rename_and_delete_their_own(uow: UowFactory) -> None:
    user = await person(uow)
    cats = {c.name: c.id for c in await list_categories(uow(), user.id)}
    trip = await log_transaction(
        uow(), user.id, spend("30", counterparty="Bus", category_id=cats["Travel"])
    )
    await rule_cases.set_rule(uow(), user, "bus", cats["Travel"], now=NOW)
    await budget_cases.set_budget(uow(), user, cats["Travel"], Money.of("200", "SGD"), now=NOW)
    model = scripted(
        call("add_category", category="Pets"),
        say("Added."),
        call("add_category", category="pets"),
        say("Already there."),
        call("rename_category", category="Activities", new_name="Hobbies"),
        say("Renamed."),
        call("rename_category", category="Hobbies", new_name="Travel"),
        say("Taken."),
        call("delete_category", category="Travel"),
        say("Deleted."),
        call("delete_category", category="Other"),
        say("Can't."),
        call("delete_category", category="Income"),
        say("Can't."),
        call("delete_category", category="Pets", move_to="Pets"),
        say("Can't."),
        call("add_category", category="Travel"),
        say("Back."),
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
    assert ask.text == "Delete Travel? Its expenses and rules move to Other."
    assert "Travel" in await names(uow, user.id)  # nothing until confirmed
    await agent.resolve(user.id, ask.buttons[0][0].data.split(":")[1], True)
    assert tool_results(model)[-1] == "Deleted Travel. Its 1 expense moved to Other."
    current = await names(uow, user.id)
    assert "Travel" not in current and {"Pets", "Hobbies"} <= set(current)

    # The expense and the rule went to Other; the budget went with the category.
    moved = await get_transaction(uow(), user.id, trip.id)
    assert moved.category_id == cats["Other"]
    [rule] = await rule_cases.list_rules(uow(), user.id)
    assert rule.category.id == cats["Other"]
    async with uow() as tx:
        assert await tx.planning.list_budgets(user.id) == []

    # Other and Income stay, and a category can't move into itself.
    for text_, refusal in (
        ("delete other", "Other and Income can't be deleted"),
        ("delete income", "Other and Income can't be deleted"),
        ("delete pets into pets", "pick a different category"),
    ):
        await agent.handle_text(user.id, text_, "tg:1:6")
        assert refusal in tool_results(model)[-1]
    assert {"Other", "Income", "Pets"} <= set(await names(uow, user.id))

    # The name is free to use again.
    await agent.handle_text(user.id, "add travel back", "tg:1:7")
    assert tool_results(model)[-1] == "Added the category Travel."


async def test_deleting_a_category_moves_its_expenses_where_the_user_says(uow: UowFactory) -> None:
    user = await person(uow)
    cats = {c.name: c.id for c in await list_categories(uow(), user.id)}
    trip = await log_transaction(uow(), user.id, spend("30", category_id=cats["Travel"]))
    await rule_cases.set_rule(uow(), user, "bus", cats["Travel"], now=NOW)
    deleted = await category_cases.delete_category(
        uow(), user.id, cats["Travel"], cats["Activities"], now=NOW
    )
    assert (deleted.into.name, deleted.moved) == ("Activities", 1)
    assert (await get_transaction(uow(), user.id, trip.id)).category_id == cats["Activities"]
    [rule] = await rule_cases.list_rules(uow(), user.id)
    assert rule.category.id == cats["Activities"]
    with pytest.raises(NotFound):
        await category_cases.delete_category(uow(), user.id, uuid4(), None, now=NOW)
    with pytest.raises(NotFound):
        await category_cases.delete_category(uow(), user.id, cats["Health"], uuid4(), now=NOW)
    with pytest.raises(NotFound):  # Travel is gone
        await category_cases.delete_category(uow(), user.id, cats["Travel"], None, now=NOW)
    with pytest.raises(InvalidInput):
        await category_cases.delete_category(uow(), user.id, cats["Other"], None, now=NOW)
    with pytest.raises(InvalidInput):
        await category_cases.delete_category(
            uow(), user.id, cats["Health"], cats["Health"], now=NOW
        )


async def test_undoing_a_recategorise_after_its_old_category_is_deleted(uow: UowFactory) -> None:
    user = await person(uow)
    cats = {c.name: c.id for c in await list_categories(uow(), user.id)}
    tx = await log_transaction(
        uow(), user.id, spend("30", counterparty="Bus", category_id=cats["Travel"])
    )
    await edit_transaction(uow(), user.id, tx.id, TransactionChanges(category_id=cats["Health"]))
    await category_cases.delete_category(uow(), user.id, cats["Travel"], None, now=NOW)
    result = await undo_last(uow(), user.id)
    assert result.transaction.category_id == cats["Health"]  # Travel no longer exists
    assert (await get_transaction(uow(), user.id, tx.id)).category_id == cats["Health"]


async def test_the_old_bots_other_categories_are_regrouped(empty_database_url: str) -> None:
    await upgrade(empty_database_url, "0015")
    engine = make_engine(empty_database_url)
    ann = uuid4()
    names_before = (*DEFAULT_CATEGORIES[:9], "Income", "Other")  # no Subscriptions & Software
    legacy = ("Software", "Digital Goods & In-App Purchases", "Others", "Automotive",
              "Personal Care")  # fmt: skip
    cat = {name: uuid4() for name in (*names_before, *legacy, "Pets")}
    txs: dict[str, UUID] = {}
    try:
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, timezone, home_currency, role) "
                    "VALUES (:id, 300, 'Asia/Singapore', 'SGD', 'owner')"
                ),
                {"id": ann},
            )
            for name, cid in cat.items():
                await db.execute(
                    text("INSERT INTO categories (id, user_id, name) VALUES (:id, :u, :n)"),
                    {"id": cid, "u": ann, "n": name},
                )
            # The old bot's categories have imported expenses; Pets is Ann's own.
            for name in (*legacy, "Pets"):
                txs[name] = uuid4()
                await db.execute(
                    text(
                        "INSERT INTO transactions (id, user_id, direction, amount, currency, "
                        "occurred_at, category_id, status, source, created_at, updated_at) "
                        "VALUES (:id, :u, 'out', 5, 'SGD', now(), :c, 'confirmed', :src, "
                        "now(), now())"
                    ),
                    {
                        "id": txs[name],
                        "u": ann,
                        "c": cat[name],
                        "src": "text" if name == "Pets" else "import",
                    },
                )
        await upgrade(empty_database_url)
        async with engine.connect() as db:
            rows = await db.execute(
                text(
                    "SELECT t.id, c.name FROM transactions AS t "
                    "JOIN categories AS c ON c.id = t.category_id"
                )
            )
            filed: dict[UUID, str] = {r.id: r.name for r in rows}
            cats = await db.execute(text("SELECT name FROM categories"))
            kept = {r.name for r in cats}
    finally:
        await engine.dispose()
    assert filed[txs["Software"]] == "Subscriptions & Software"
    assert filed[txs["Digital Goods & In-App Purchases"]] == "Subscriptions & Software"
    assert filed[txs["Others"]] == "Other"
    assert filed[txs["Automotive"]] == "Transport"
    assert filed[txs["Personal Care"]] == "Personal Care"  # kept, as asked
    assert filed[txs["Pets"]] == "Pets"  # Ann's own: left alone
    assert kept == {*DEFAULT_CATEGORIES, "Personal Care", "Pets"}


async def test_merging_one_category_into_another(uow: UowFactory) -> None:
    user = await person(uow)
    software = await category_cases.create_category(uow(), user.id, "Software")
    cats = {c.name: c.id for c in await list_categories(uow(), user.id)}
    await budget_cases.set_budget(uow(), user, software.id, Money.of("50", "SGD"), now=NOW)
    model = scripted(
        call("log_expense", amount="20", merchant="Cursor", category="Software"),
        say("ok"),
        call("merge_category", category="Software", into="Subscriptions & Software"),
        say("Merged."),
    )
    agent = build(uow, model)
    await agent.handle_text(user.id, "cursor 20 software", "tg:1:1")
    await rule_cases.set_rule(uow(), user, "cursor", software.id, now=NOW)
    ask = only(await agent.handle_text(user.id, "merge software into subscriptions", "tg:1:2"))
    assert ask.text.startswith("Move everything filed under Software into Subscriptions")
    await agent.resolve(user.id, ask.buttons[0][0].data.split(":")[1], True)
    assert tool_results(model)[-1] == (
        "Merged Software into Subscriptions & Software: 1 transaction moved, and Software is "
        "deleted."
    )
    assert "Software" not in await names(uow, user.id)
    [rule] = await rule_cases.list_rules(uow(), user.id)
    assert rule.category.id == cats["Subscriptions & Software"]
    async with uow() as tx:  # the budget moved over, since the target had none
        [budget] = await tx.planning.list_budgets(user.id)
    assert budget.category_id == cats["Subscriptions & Software"]
    with pytest.raises(InvalidInput):
        await category_cases.merge_category(uow(), user.id, cats["Other"], cats["Other"], now=NOW)
    with pytest.raises(InvalidInput):  # Other and Income can't be merged away
        await category_cases.merge_category(uow(), user.id, cats["Other"], cats["Health"], now=NOW)


async def test_archived_categories_are_deleted_or_made_normal_again(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0040")
    engine = make_engine(empty_database_url)
    ann, empty, used, spent, rule = (uuid4() for _ in range(5))
    try:
        async with engine.begin() as db:
            await db.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, timezone, home_currency, role) "
                    "VALUES (:id, 400, 'Asia/Singapore', 'SGD', 'owner')"
                ),
                {"id": ann},
            )
            for cid, name in ((empty, "Old Hobby"), (used, "Old Trip")):
                await db.execute(
                    text(
                        "INSERT INTO categories (id, user_id, name, active) "
                        "VALUES (:id, :u, :n, false)"
                    ),
                    {"id": cid, "u": ann, "n": name},
                )
            await db.execute(
                text(
                    "INSERT INTO category_rules (id, user_id, pattern, category_id, explanation, "
                    "created_at, updated_at) VALUES (:id, :u, 'hobby', :c, 'x', now(), now())"
                ),
                {"id": rule, "u": ann, "c": empty},
            )
            for cid in (empty, used):
                await db.execute(
                    text(
                        "INSERT INTO budgets (id, user_id, category_id, amount, currency, "
                        "created_at, updated_at) VALUES (:id, :u, :c, 100, 'SGD', now(), now())"
                    ),
                    {"id": uuid4(), "u": ann, "c": cid},
                )
            await db.execute(
                text(
                    "INSERT INTO transactions (id, user_id, direction, amount, currency, "
                    "occurred_at, category_id, status, source, created_at, updated_at) "
                    "VALUES (:id, :u, 'out', 5, 'SGD', now(), :c, 'confirmed', 'text', "
                    "now(), now())"
                ),
                {"id": spent, "u": ann, "c": used},
            )
        await upgrade(empty_database_url, "0041")
        async with engine.connect() as db:
            kept = {r.id for r in await db.execute(text("SELECT id FROM categories"))}
            rules: int = (
                await db.execute(text("SELECT count(*) FROM category_rules"))
            ).scalar_one()
            budgets = (await db.execute(text("SELECT category_id FROM budgets"))).all()
            filed: UUID = (
                await db.execute(text("SELECT category_id FROM transactions"))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert kept == {used}
    assert rules == 0
    assert [r.category_id for r in budgets] == [used]
    assert filed == used
