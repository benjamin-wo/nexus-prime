"""Which of Invest and Travel show in the web menu (``users.show_invest`` and
``users.show_travel``): null (not decided, hidden), true (shown), false (switched off, never
turned on by itself). The migration, the API, demos, and chat turning a section on the first
time it is used, with a one-line note. Chat works the same whatever they say. Made-up data
only."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from nexus.agent.service import MENU_NOTES
from nexus.agent.tools import MENU_OF, build_tools
from nexus.application import research as research_cases
from nexus.application.users import get_user, set_preferences, turn_on_menu
from nexus.domain.ledger import MenuSection, UserId
from nexus.infra.db.engine import make_engine
from tests.fakes import NOW, call, say, scripted
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import build, only
from tests.integration.test_wallets import downgrade
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

INVEST_NOTE = MENU_NOTES[MenuSection.INVEST]
TRAVEL_NOTE = MENU_NOTES[MenuSection.TRAVEL]
TRIP = {"destination": "Lisbon", "start": "2027-02-01", "end": "2027-02-08", "currency": "EUR"}


async def menu(uow: UowFactory, user: UserId) -> tuple[bool | None, bool | None]:
    found = await get_user(uow(), user)
    return found.show_invest, found.show_travel


# --- the setting -------------------------------------------------------------------------


async def test_a_new_user_has_not_decided_and_a_choice_is_kept(
    uow: UowFactory, alice: UserId
) -> None:
    assert await menu(uow, alice) == (None, None)
    await set_preferences(uow(), alice, show_invest=True)
    assert await menu(uow, alice) == (True, None)
    await set_preferences(uow(), alice, show_travel=False, show_invest=False)
    assert await menu(uow, alice) == (False, False)
    # Only what is sent changes, and card tracking is among what was not sent.
    assert (await get_user(uow(), alice)).track_cards is False
    await set_preferences(uow(), alice, track_cards=True)
    assert await menu(uow, alice) == (False, False)
    assert (await get_user(uow(), alice)).track_cards is True


async def test_turning_on_by_use_only_ever_changes_a_null(uow: UowFactory, alice: UserId) -> None:
    assert await turn_on_menu(uow(), alice, MenuSection.INVEST) is True
    assert await turn_on_menu(uow(), alice, MenuSection.INVEST) is False  # already on
    await set_preferences(uow(), alice, show_travel=False)
    assert await turn_on_menu(uow(), alice, MenuSection.TRAVEL) is False  # their choice
    assert await menu(uow, alice) == (True, False)


async def test_me_shows_the_menu_choices_and_a_partial_put_changes_only_what_is_sent(
    world: World,
) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    start = {"track_cards": False, "show_invest": None, "show_travel": None}
    assert (await owner.get("/api/me")).json()["preferences"] == start

    on = await owner.send("PUT", "/api/settings/preferences", {"show_invest": True})
    assert on.status_code == 200
    assert on.json() == {"track_cards": False, "show_invest": True, "show_travel": None}

    both = await owner.send(
        "PUT", "/api/settings/preferences", {"show_travel": False, "track_cards": True}
    )
    assert both.json() == {"track_cards": True, "show_invest": True, "show_travel": False}
    assert (await owner.get("/api/me")).json()["preferences"] == both.json()

    # The card switch alone leaves the menu as it was, and the other way round.
    cards_off = await owner.send("PUT", "/api/settings/preferences", {"track_cards": False})
    assert cards_off.json() == {"track_cards": False, "show_invest": True, "show_travel": False}
    off = await owner.send("PUT", "/api/settings/preferences", {"show_invest": False})
    assert off.json() == {"track_cards": False, "show_invest": False, "show_travel": False}


async def test_the_menu_choices_are_strict(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    bad: tuple[dict[str, object], ...] = (
        {},
        {"show_invest": "maybe"},
        {"show_travel": None},
        {"show_invest": True, "x": 1},
    )
    for body in bad:
        refused = await owner.send("PUT", "/api/settings/preferences", body)
        assert refused.status_code == 422, body
    assert (await owner.get("/api/me")).json()["preferences"] == {
        "track_cards": False,
        "show_invest": None,
        "show_travel": None,
    }


# --- chat turns a section on the first time it is used -------------------------------------


async def test_an_investing_tool_adds_invest_once_with_one_line(
    uow: UowFactory, alice: UserId
) -> None:
    await research_cases.watch(uow(), alice, "AMD", now=NOW)
    model = scripted(
        call("show_watchlist"),
        say("You watch AMD."),
        call("show_watchlist"),
        say("Still just AMD."),
    )
    agent = build(uow, model)
    first = only(await agent.handle_text(alice, "what do I watch?", "m1"))
    assert first.text == f"You watch AMD.\n\n{INVEST_NOTE}"
    assert await menu(uow, alice) == (True, None)
    second = only(await agent.handle_text(alice, "and now?", "m2"))
    assert second.text == "Still just AMD."  # said once


async def test_a_travel_tool_adds_travel_and_a_confirmed_write_does_too(
    uow: UowFactory, alice: UserId
) -> None:
    model = scripted(call("create_trip", **TRIP), say("Trip to Lisbon saved."))
    agent = build(uow, model)
    ask = only(await agent.handle_text(alice, "I'm off to Lisbon on 1 Feb for a week", "m1"))
    assert TRAVEL_NOTE not in ask.text  # nothing has run yet
    assert await menu(uow, alice) == (None, None)
    done = only(await agent.resolve(alice, ask.buttons[0][0].data.split(":")[1], True))
    assert done.text.startswith("Trip to Lisbon saved.")
    assert done.text.endswith(f"\n\n{TRAVEL_NOTE}") and INVEST_NOTE not in done.text
    assert await menu(uow, alice) == (None, True)


async def test_both_sections_in_one_turn_give_one_line_each(uow: UowFactory, alice: UserId) -> None:
    model = scripted(call("list_trips"), call("show_portfolio"), say("Nothing in either."))
    reply = only(await build(uow, model).handle_text(alice, "anything on?", "m1"))
    assert reply.text == f"Nothing in either.\n\n{TRAVEL_NOTE}\n{INVEST_NOTE}"
    assert await menu(uow, alice) == (True, True)


async def test_a_section_the_user_turned_off_stays_off_and_chat_still_works(
    uow: UowFactory, alice: UserId
) -> None:
    await set_preferences(uow(), alice, show_invest=False, show_travel=False)
    await research_cases.watch(uow(), alice, "AMD", now=NOW)
    model = scripted(
        call("show_watchlist"), say("You watch AMD."), call("list_trips"), say("No trips.")
    )
    agent = build(uow, model)
    invest = only(await agent.handle_text(alice, "what do I watch?", "m1"))
    travel = only(await agent.handle_text(alice, "any trips?", "m2"))
    assert (invest.text, travel.text) == ("You watch AMD.", "No trips.")
    assert await menu(uow, alice) == (False, False)


async def test_a_tool_that_fails_adds_nothing(uow: UowFactory, alice: UserId) -> None:
    model = scripted(call("trip_status", trip="Atlantis"), say("I couldn't find it."))
    reply = only(await build(uow, model).handle_text(alice, "how is Atlantis going?", "m1"))
    assert reply.text == "I couldn't find it."
    assert await menu(uow, alice) == (None, None)


async def test_other_tools_leave_the_menu_alone(uow: UowFactory, alice: UserId) -> None:
    model = scripted(call("log_expense", amount="5.50", merchant="Kopi"), say("Logged."))
    reply = only(await build(uow, model).handle_text(alice, "kopi 5.50", "m1"))
    assert reply.text == "Logged."
    assert await menu(uow, alice) == (None, None)


def test_every_menu_tool_exists_and_both_sections_have_some() -> None:
    tools = build_tools(lambda _: "")
    assert set(MENU_OF) <= set(tools)
    assert set(MENU_OF.values()) == {MenuSection.INVEST, MenuSection.TRAVEL}
    assert set(MENU_NOTES) == set(MenuSection)


# --- the migration -----------------------------------------------------------------------


USER_SQL = text(
    "INSERT INTO users (id, telegram_user_id, timezone, home_timezone, home_currency, role) "
    "VALUES (:id, :tg, 'UTC', 'UTC', 'SGD', 'owner')"
)
INVESTING = {
    "holdings": (
        "INSERT INTO holdings (id, user_id, symbol, quantity, average_cost, currency, "
        "created_at, updated_at) VALUES (gen_random_uuid(), :u, 'AMD', 3, 100, 'USD', now(), now())"
    ),
    "watchlist": (
        "INSERT INTO watchlist (id, user_id, symbol, created_at) "
        "VALUES (gen_random_uuid(), :u, 'TSLA', now())"
    ),
    "trades": (
        "INSERT INTO trades (id, user_id, symbol, side, quantity, currency, traded_on, "
        "created_at) VALUES (gen_random_uuid(), :u, 'NVDA', 'buy', 2, 'USD', current_date, now())"
    ),
    "plans": (
        "INSERT INTO plans (id, user_id, symbol, verdict, as_of, valid_until, close, body, "
        "status, created_at) VALUES (gen_random_uuid(), :u, 'AMD', 'wait', current_date, "
        "current_date, 100, '{}', 'open', now())"
    ),
}
TRIP_SQL = (
    "INSERT INTO trips (id, user_id, destination, start_on, end_on, currency, home_currency, "
    "companions, planned, created_at, updated_at) VALUES (:t, :u, 'Lisbon', current_date, "
    "current_date, 'EUR', 'SGD', '[]', '[]', now(), now())"
)
TRAVEL = {
    "trips": TRIP_SQL,
    "bookings": (
        "INSERT INTO trip_bookings (id, user_id, kind, title, details, created_at) "
        "VALUES (gen_random_uuid(), :u, 'hotel', 'Hotel', '{}', now())"
    ),
    "research": (
        "INSERT INTO department_runs (id, user_id, department, kind, title, status, task, "
        "outputs, steps_done, steps_total, progress, spent, created_at, updated_at) VALUES "
        "(gen_random_uuid(), :u, 'travel', 'trip', 'Lisbon ideas', 'done', '{}', '{}', 1, 1, "
        "'', 0, now(), now())"
    ),
}


async def test_the_migration_shows_a_section_only_for_those_who_already_use_it(
    empty_database_url: str,
) -> None:
    await upgrade(empty_database_url, "0067")
    engine = make_engine(empty_database_url)
    users: dict[str, UUID] = {}
    try:
        async with engine.begin() as db:
            for n, name in enumerate([*INVESTING, *TRAVEL, "member", "spender", "nobody"]):
                users[name] = uuid4()
                await db.execute(USER_SQL, {"id": users[name], "tg": 700 + n})
            for name, sql in INVESTING.items():
                await db.execute(text(sql), {"u": users[name]})
            for name, sql in TRAVEL.items():
                await db.execute(text(sql), {"u": users[name], "t": uuid4()})
            # Added to someone else's trip; and a user whose data is only money.
            trip = uuid4()
            await db.execute(text(TRIP_SQL), {"u": users["trips"], "t": trip})
            await db.execute(
                text(
                    "INSERT INTO trip_members (id, trip_id, owner_id, member_id, added_at) "
                    "VALUES (gen_random_uuid(), :t, :o, :m, now())"
                ),
                {"t": trip, "o": users["trips"], "m": users["member"]},
            )
            await db.execute(
                text(
                    "INSERT INTO transactions (id, user_id, direction, amount, currency, "
                    "occurred_at, status, source, created_at, updated_at) VALUES "
                    "(gen_random_uuid(), :u, 'out', 5, 'SGD', now(), 'confirmed', 'manual', "
                    "now(), now())"
                ),
                {"u": users["spender"]},
            )

        await upgrade(empty_database_url, "0068")
        async with engine.connect() as db:
            rows = (await db.execute(text("SELECT id, show_invest, show_travel FROM users"))).all()
        shown = {r.id: (r.show_invest, r.show_travel) for r in rows}
        for name in INVESTING:
            assert shown[users[name]] == (True, None), name
        for name in TRAVEL:
            assert shown[users[name]] == (None, True), name
        assert shown[users["member"]] == (None, True)
        assert shown[users["spender"]] == (None, None)
        assert shown[users["nobody"]] == (None, None)

        # A user made after it has not decided.
        late = uuid4()
        async with engine.begin() as db:
            await db.execute(USER_SQL, {"id": late, "tg": 799})
            fresh = (
                await db.execute(
                    text("SELECT show_invest, show_travel FROM users WHERE id = :u"), {"u": late}
                )
            ).one()
        assert (fresh.show_invest, fresh.show_travel) == (None, None)

        await downgrade(empty_database_url, "0067")
        async with engine.connect() as db:
            gone: int = (
                await db.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'users' AND column_name IN "
                        "('show_invest', 'show_travel')"
                    )
                )
            ).scalar_one()
        assert gone == 0
    finally:
        await engine.dispose()
