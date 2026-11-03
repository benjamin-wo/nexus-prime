"""The demo persona (``seed_demo``), read back the way the web app reads it: through the
web API, signed in as the seeded account. Everything seeded is made up."""

import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from nexus.application.demo_seed import seed_demo
from nexus.domain.ledger import User, ZoneSource
from nexus.infra.db.uow import SqlUnitOfWork
from tests.integration import test_web_api
from tests.integration.test_web_api import MEMBER, STRANGER, Browser, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

SG = ZoneInfo("Asia/Singapore")
# Mid-month, the first half hour of a month, and the last minutes of a year.
NOWS = [
    datetime(2026, 9, 28, 12, 0, tzinfo=SG),
    datetime(2026, 10, 1, 0, 30, tzinfo=SG),
    datetime(2026, 12, 31, 23, 50, tzinfo=SG),
]


async def visitor(world: World, telegram_id: int, invite: str) -> tuple[Browser, User]:
    """A new account as the demo makes them: signed in, in Singapore, with nothing in it."""
    browser = world.browser()
    assert (await browser.login(telegram_id, invite)).status_code == 200
    async with SqlUnitOfWork(world.engine) as db:
        found = await db.ledger.get_user_by_telegram_id(telegram_id)
        assert found is not None
        await db.ledger.set_timezone(found.id, "Asia/Singapore", ZoneSource.HOME, None)
        await db.commit()
        user = await db.ledger.get_user(found.id)
    assert user is not None and user.home_currency == "SGD"
    return browser, user


async def seeded_visitor(world: World, telegram_id: int, invite: str) -> tuple[Browser, float]:
    browser, user = await visitor(world, telegram_id, invite)
    started = time.perf_counter()
    await seed_demo(lambda: SqlUnitOfWork(world.engine), user, now=world.clock.now)
    return browser, time.perf_counter() - started


async def get(browser: Browser, path: str) -> Any:
    response = await browser.get(path)
    assert response.status_code == 200, (path, response.text)
    return response.json()


def local_day(stamp: str) -> date:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(SG).date()


@pytest.mark.parametrize("now", NOWS, ids=["mid-month", "first-of-month", "new-year-eve"])
async def test_the_demo_account_has_a_full_life(world: World, now: datetime) -> None:
    world.clock.now = now
    today = now.astimezone(SG).date()
    _, invite = await owner_and_invite(world)
    browser, seconds = await seeded_visitor(world, MEMBER, invite)
    assert seconds < 2

    # The ledger: about two months of spending, two paydays, money put away.
    page = await get(browser, "/api/transactions?limit=500")
    items = page["items"]
    spending = [t for t in items if t["direction"] == "out"]
    income = [t for t in items if t["direction"] == "in"]
    moves = [t for t in items if t["direction"] == "move"]
    assert 70 <= len(spending) <= 90
    assert all(t["category_id"] and t["status"] == "confirmed" for t in spending)
    assert all(datetime.fromisoformat(t["occurred_at"]) <= now for t in items)
    this_month = [
        t for t in spending if local_day(t["occurred_at"]).replace(day=1) == today.replace(day=1)
    ]
    last_month_end = today.replace(day=1) - timedelta(days=1)
    last_month = [
        t
        for t in spending
        if local_day(t["occurred_at"]).replace(day=1) == last_month_end.replace(day=1)
    ]
    assert len(this_month) >= 3 and len(last_month) >= 10
    assert sorted(t["counterparty"] for t in income) == ["Acme Pte Ltd"] * 2
    assert {Decimal(t["amount"]["amount"]) for t in income} == {Decimal(6200)}
    first, second = sorted(local_day(t["occurred_at"]) for t in income)
    assert today - timedelta(days=62) <= first < second <= today
    assert [m["to_wallet"]["name"] for m in moves].count("Savings") >= 3
    assert {m["from_wallet"]["name"] for m in moves} == {"Spending"}
    # The Grab rule filed the rides; a few entries carry a note.
    rides = [t for t in spending if t["counterparty"] == "Grab"]
    assert rides and all(t["category_rule_id"] for t in rides)
    assert sum(1 for t in spending if t["notes"]) >= 5
    # Spread over many days.
    assert len({local_day(t["occurred_at"]) for t in spending}) >= 40
    wallets = {w["name"]: w["kind"] for w in await get(browser, "/api/wallets")}
    assert wallets == {
        "Spending": "spending",
        "Cash": "cash",
        "Savings": "savings",
        "IBKR": "investment",
    }
    rules = await get(browser, "/api/category-rules")
    assert [(r["pattern"], r["category_name"]) for r in rules] == [("grab", "Transport")]

    # Ann owes the user from the dinners they shared.
    owed = await get(browser, "/api/ious")
    assert {i["participant_name"] for i in owed} == {"Ann"} and len(owed) == 2
    assert sum(Decimal(i["outstanding"]["amount"]) for i in owed) == Decimal("79.20")

    # Salary: the 25th, from Acme.
    pay = await get(browser, "/api/salary")
    assert (pay["rule"], pay["day"], pay["payer"]) == ("monthly_day", 25, "Acme Pte Ltd")
    assert Decimal(pay["usual"]["amount"]) == Decimal(6200)
    assert pay["unnamed_salaries"] == 0

    # Budgets: Dining Out nearly used up, the others comfortably under.
    budgets = {b["name"]: b for b in await get(browser, "/api/budgets")}
    assert set(budgets) == {"Dining Out", "Groceries", "Transport", "Shopping"}
    assert 85 <= budgets["Dining Out"]["percent"] <= 95
    assert all(b["percent"] <= 70 for n, b in budgets.items() if n != "Dining Out")

    # Bills: rent is paid this month, the phone and electricity are coming.
    bills = {b["name"]: b for b in await get(browser, "/api/bills")}
    assert set(bills) == {"Rent", "Singtel", "SP Group"}
    next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    assert bills["Rent"]["due"] == next_month.isoformat()
    assert [t["notes"] for t in this_month if t["counterparty"] == "Rent"] == [
        f"Bill due 1 {today:%b %Y}"
    ]
    assert bills["SP Group"]["days_until"] == 3 and bills["Singtel"]["days_until"] == 9
    subscriptions = await get(browser, "/api/subscriptions")
    assert {s["name"] for s in subscriptions["tracked"]} == {"Netflix", "Spotify"}

    # Home has something to say.
    needs = await get(browser, "/api/home")
    kinds = [i["kind"] for i in needs]
    assert "budget" in kinds and "bill" in kinds and "duplicates" not in kinds
    assert any("Dining Out" in i["text"] for i in needs)

    # The trip: Kyoto then Osaka, three weeks out, with a plan and ideas but no places.
    trips = await get(browser, "/api/travel/trips")
    assert len(trips) == 1
    trip = trips[0]
    assert (trip["destination"], trip["days"], trip["companions"]) == ("Japan", 6, ["Ann"])
    assert trip["start"] == (today + timedelta(days=21)).isoformat()
    assert Decimal(trip["budget"]["amount"]) > 0 and Decimal(trip["set_aside"]["amount"]) > 0
    assert [s["name"] for s in trip["stops"]] == ["Kyoto", "Osaka"]
    assert len(trip["packing"]) >= 8 and any(p["done"] for p in trip["packing"])
    detail = await get(browser, f"/api/travel/trips/{trip['id']}")
    entries = detail["bookings"]
    kinds_booked = sorted(e["kind"] for e in entries if e["kind"] != "activity")
    assert kinds_booked == ["flight", "hotel", "hotel"]
    plans = [e for e in entries if e["kind"] == "activity" and e["day"]]
    ideas = [e for e in entries if e["kind"] == "activity" and not e["day"]]
    assert len({p["day"] for p in plans}) >= 3 and all(p["at"] for p in plans)
    assert len(ideas) >= 5 and all(i["list_name"] for i in ideas)
    assert {i["id"] for i in ideas} == set(detail["places_order"])
    assert not [e for e in entries if e["place_id"] or e["lat"] is not None]
    assert len(detail["days"]) >= 4 and all(d["order"] for d in detail["days"])
    assert detail["ready"]["done"] == detail["ready"]["total"]
    # A day of plans with no places on the map: the hops come back empty, not as an error.
    assert (
        await get(browser, f"/api/travel/trips/{trip['id']}/days/{detail['days'][1]['day']}/hops")
        == []
    )

    # Investments: four holdings and two stocks watched. Prices are left to the usual jobs.
    holdings = {h["symbol"]: h for h in (await get(browser, "/api/investments"))["holdings"]}
    assert {s: Decimal(h["quantity"]) for s, h in holdings.items()} == {
        "NVDA": 12,
        "AAPL": 15,
        "VOO": 8,
        "MSFT": 6,
    }
    assert all(h["average_cost"]["currency"] == "USD" for h in holdings.values())
    watching = (await get(browser, "/api/investments/watchlist"))["stocks"]
    assert sorted(s["symbol"] for s in watching) == ["AMD", "GOOGL"]
    assert len(await get(browser, "/api/investments/trades")) == 6


async def test_two_demo_accounts_stay_apart_and_each_takes_under_two_seconds(world: World) -> None:
    world.clock.now = NOWS[0]
    owner, first_invite = await owner_and_invite(world)
    second_invite = (await owner.send("POST", "/api/invites")).json()["url"].rsplit("/", 1)[-1]
    one, took_one = await seeded_visitor(world, MEMBER, first_invite)
    two, took_two = await seeded_visitor(world, STRANGER, second_invite)
    assert max(took_one, took_two) < 2

    mine = (await get(one, "/api/transactions?limit=500"))["items"]
    theirs = (await get(two, "/api/transactions?limit=500"))["items"]
    assert {t["id"] for t in mine}.isdisjoint(t["id"] for t in theirs)

    def shape(items: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
        return sorted(
            (t["direction"], t["counterparty"], t["amount"]["amount"], t["occurred_at"], t["notes"])
            for t in items
        )

    # The same moment gives the same account, whoever it is for.
    assert shape(mine) == shape(theirs)
    own_trip = (await get(one, "/api/travel/trips"))[0]["id"]
    other_trip = (await get(two, "/api/travel/trips"))[0]["id"]
    assert own_trip != other_trip
    assert (await one.get(f"/api/travel/trips/{other_trip}")).status_code == 404
    assert len(await get(one, "/api/travel/trips")) == 1
    assert len(await get(two, "/api/ious")) == 2
    # Nobody else's rows leak: the owner's own account is still empty.
    assert (await get(owner, "/api/transactions"))["total"] == 0
