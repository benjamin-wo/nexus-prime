"""Wallets and moves through the web API: CRUD, moves in the ledger, the summary's put away
figures, the CSV export and tenant isolation. Every name and figure is made up."""

from typing import Any

import pytest

from tests.integration import test_web_api
from tests.integration.test_web_api import MEMBER, OWNER, Browser, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

DAY = "2026-09-20"


async def wallets_by_name(browser: Browser) -> dict[str, dict[str, Any]]:
    found = (await browser.get("/api/wallets")).json()
    return {w["name"]: w for w in found}


async def add(browser: Browser, name: str, kind: str, **extra: Any) -> dict[str, Any]:
    made = await browser.send("POST", "/api/wallets", {"name": name, "kind": kind, **extra})
    assert made.status_code == 201, made.text
    created: dict[str, Any] = made.json()
    return created


async def move(browser: Browser, amount: str, to: str, **extra: Any) -> dict[str, Any]:
    body = {"amount": amount, "to_wallet_id": to, "occurred_at": DAY, **extra}
    made = await browser.send("POST", "/api/moves", body)
    assert made.status_code == 201, made.text
    created: dict[str, Any] = made.json()
    return created


async def test_wallets_add_edit_and_refusals(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    first = (await owner.get("/api/wallets")).json()
    assert [(w["name"], w["kind"], w["match_words"]) for w in first] == [
        ("Spending", "spending", [])
    ]
    assert set(first[0]) == {"id", "name", "kind", "match_words"}

    ibkr = await add(owner, "IBKR", "investment", match_words=["Interactive Brokers", "ibkr"])
    assert ibkr["match_words"] == ["Interactive Brokers", "ibkr"] and ibkr["kind"] == "investment"
    await add(owner, "Emergency fund", "savings")
    assert [w["name"] for w in (await owner.get("/api/wallets")).json()] == [
        "Spending",
        "Emergency fund",
        "IBKR",
    ]

    renamed = await owner.send(
        "PATCH", f"/api/wallets/{ibkr['id']}", {"name": "Brokerage", "kind": "other"}
    )
    assert renamed.status_code == 200
    assert renamed.json() == {
        **ibkr,
        "name": "Brokerage",
        "kind": "other",
    }
    cleared = await owner.send("PATCH", f"/api/wallets/{ibkr['id']}", {"match_words": []})
    assert cleared.json()["match_words"] == [] and cleared.json()["name"] == "Brokerage"

    # Refusals: a clashing name, a bad kind, a second Spending, changing Spending's kind.
    assert (await owner.send("POST", "/api/wallets", {"name": "brokerage", "kind": "other"})
            ).status_code == 409  # fmt: skip
    assert (
        await owner.send("POST", "/api/wallets", {"name": "X", "kind": "bank"})
    ).status_code == 422
    assert (
        await owner.send("POST", "/api/wallets", {"name": "Again", "kind": "spending"})
    ).status_code == 422
    spending = first[0]["id"]
    assert (
        await owner.send("PATCH", f"/api/wallets/{spending}", {"kind": "savings"})
    ).status_code == 422
    assert (await owner.send("DELETE", f"/api/wallets/{spending}")).status_code == 422


async def test_a_move_is_logged_and_listed_with_its_wallets(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await add(owner, "IBKR", "investment")
    made = await move(owner, "800", ibkr["id"], notes="monthly top-up")
    spending = (await wallets_by_name(owner))["Spending"]
    assert made["direction"] == "move"
    assert made["amount"] == {"amount": "800.0000", "currency": "SGD"}
    assert made["from_wallet"] == {"id": spending["id"], "name": "Spending", "kind": "spending"}
    assert made["to_wallet"] == {"id": ibkr["id"], "name": "IBKR", "kind": "investment"}
    assert made["received"] is None and made["category_id"] is None and made["split"] is None

    await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "5"})
    items = (await owner.get("/api/transactions")).json()["items"]
    listed = next(t for t in items if t["direction"] == "move")
    assert listed["to_wallet"]["name"] == "IBKR" and listed["links"] == []
    plain = next(t for t in items if t["direction"] == "out")
    assert plain["from_wallet"] is None and plain["to_wallet"] is None and plain["received"] is None

    only = (await owner.get("/api/transactions", params={"direction": "move"})).json()
    assert only["total"] == 1 and only["items"][0]["id"] == made["id"]
    one = (await owner.get(f"/api/transactions/{made['id']}")).json()
    assert one["from_wallet"]["name"] == "Spending"

    # Amount, notes and date may be edited; a move can't turn into money in or out.
    edited = await owner.send(
        "PATCH", f"/api/transactions/{made['id']}", {"amount": "850", "notes": "bonus"}
    )
    assert edited.status_code == 200
    assert edited.json()["amount"]["amount"] == "850.0000"
    assert edited.json()["to_wallet"]["name"] == "IBKR"
    flipped = await owner.send("PATCH", f"/api/transactions/{made['id']}", {"direction": "in"})
    assert flipped.status_code == 422
    # ... and nothing but in/out can be created on the ordinary route.
    assert (
        await owner.send("POST", "/api/transactions", {"direction": "move", "amount": "1"})
    ).status_code == 422

    # Undo and delete answer with the wallets too.
    deleted = await owner.send("DELETE", f"/api/transactions/{made['id']}")
    assert deleted.json()["deleted"] is True and deleted.json()["to_wallet"]["name"] == "IBKR"
    restored = await owner.send("POST", f"/api/transactions/{made['id']}/restore")
    assert restored.json()["from_wallet"]["name"] == "Spending"


async def test_a_move_can_start_elsewhere_and_arrive_in_another_currency(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    savings = await add(owner, "Rainy day", "savings")
    ibkr = await add(owner, "IBKR", "investment")
    made = await move(
        owner, "1000", ibkr["id"], from_wallet_id=savings["id"],
        received_amount="760", received_currency="USD",
    )  # fmt: skip
    assert made["from_wallet"]["name"] == "Rainy day" and made["to_wallet"]["name"] == "IBKR"
    assert made["received"] == {"amount": "760.0000", "currency": "USD"}
    same = await owner.send(
        "POST",
        "/api/moves",
        {"amount": "5", "to_wallet_id": ibkr["id"], "from_wallet_id": ibkr["id"]},
    )
    assert same.status_code == 422
    bad = await owner.send("POST", "/api/moves", {"amount": "0", "to_wallet_id": ibkr["id"]})
    assert bad.status_code == 422
    unknown = await owner.send(
        "POST",
        "/api/moves",
        {"amount": "5", "to_wallet_id": "00000000-0000-4000-8000-000000000000"},
    )
    assert unknown.status_code == 404


async def test_money_out_or_in_is_marked_as_a_move(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    savings = await add(owner, "Rainy day", "savings")
    out = (
        await owner.send(
            "POST", "/api/transactions",
            {"direction": "out", "amount": "300", "counterparty": "Rainy day top-up", "date": DAY},
        )
    ).json()  # fmt: skip
    marked = await owner.send(
        "POST", f"/api/transactions/{out['id']}/move", {"wallet_id": savings["id"]}
    )
    assert marked.status_code == 200
    body = marked.json()
    assert body["direction"] == "move" and body["category_id"] is None
    assert body["from_wallet"]["name"] == "Spending" and body["to_wallet"]["name"] == "Rainy day"
    again = await owner.send(
        "POST", f"/api/transactions/{out['id']}/move", {"wallet_id": savings["id"]}
    )
    assert again.status_code == 422

    refund = (
        await owner.send(
            "POST", "/api/transactions", {"direction": "in", "amount": "50", "date": DAY}
        )
    ).json()
    back = await owner.send(
        "POST", f"/api/transactions/{refund['id']}/move", {"wallet_id": savings["id"]}
    )
    assert back.json()["from_wallet"]["name"] == "Rainy day"
    assert back.json()["to_wallet"]["name"] == "Spending"

    # Undo brings the refund back as money in.
    undone = await owner.send("POST", "/api/undo")
    assert undone.status_code == 200 and undone.json()["transaction"]["direction"] == "in"
    assert undone.json()["transaction"]["from_wallet"] is None

    # Marking as a move to Spending itself, or to a wallet that isn't there, is refused.
    spending = (await wallets_by_name(owner))["Spending"]["id"]
    more = (
        await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "4"})
    ).json()
    assert (
        await owner.send("POST", f"/api/transactions/{more['id']}/move", {"wallet_id": spending})
    ).status_code == 422
    assert (
        await owner.send(
            "POST", f"/api/transactions/{more['id']}/move",
            {"wallet_id": "00000000-0000-4000-8000-000000000000"},
        )
    ).status_code == 404  # fmt: skip


async def test_deleting_a_wallet_points_its_moves_elsewhere(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    old = await add(owner, "Old broker", "investment")
    new = await add(owner, "New broker", "investment")
    await move(owner, "100", old["id"])
    await move(owner, "200", old["id"])
    await move(owner, "50", new["id"], from_wallet_id=old["id"])  # would be from a wallet to itself

    # Moves need somewhere to go; so does a bad target.
    assert (await owner.send("DELETE", f"/api/wallets/{old['id']}")).status_code == 422
    assert (
        await owner.send("DELETE", f"/api/wallets/{old['id']}?move_to={old['id']}")
    ).status_code == 422
    assert (
        await owner.send(
            "DELETE", f"/api/wallets/{old['id']}?move_to=00000000-0000-4000-8000-000000000000"
        )
    ).status_code == 404

    gone = await owner.send("DELETE", f"/api/wallets/{old['id']}?move_to={new['id']}")
    assert gone.status_code == 200
    assert gone.json()["moved"] == 2 and gone.json()["removed"] == 1
    assert gone.json()["into"] == new
    names = [w["name"] for w in (await owner.get("/api/wallets")).json()]
    assert names == ["Spending", "New broker"]
    moves = (await owner.get("/api/transactions", params={"direction": "move"})).json()
    assert moves["total"] == 2
    assert {m["to_wallet"]["name"] for m in moves["items"]} == {"New broker"}

    # A wallet with no moves goes without a target.
    empty = await add(owner, "Spare", "other")
    deleted = await owner.send("DELETE", f"/api/wallets/{empty['id']}")
    assert deleted.json() == {"moved": 0, "removed": 0, "into": None}


async def test_delete_preview_counts_match_the_real_delete(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    old = await add(owner, "Old broker", "investment")
    new = await add(owner, "New broker", "investment")
    spare = await add(owner, "Spare", "other")
    await move(owner, "100", old["id"])
    await move(owner, "200", old["id"])
    await move(owner, "50", new["id"], from_wallet_id=old["id"])  # would be from a wallet to itself
    preview_url = f"/api/wallets/{old['id']}/delete-preview"

    # The same refusals as the delete, and nothing is changed by asking.
    assert (await owner.get(preview_url)).status_code == 422  # it has moves; pick another
    assert (await owner.get(f"{preview_url}?move_to={old['id']}")).status_code == 422
    unknown = "00000000-0000-4000-8000-000000000000"
    assert (await owner.get(f"{preview_url}?move_to={unknown}")).status_code == 404
    assert (await owner.get(f"/api/wallets/{unknown}/delete-preview")).status_code == 404
    spending = (await wallets_by_name(owner))["Spending"]["id"]
    assert (await owner.get(f"/api/wallets/{spending}/delete-preview")).status_code == 422
    assert (await owner.get(f"/api/wallets/{spare['id']}/delete-preview")).json() == {
        "moved": 0,
        "removed": 0,
    }

    preview = await owner.get(f"{preview_url}?move_to={new['id']}")
    assert preview.status_code == 200 and preview.json() == {"moved": 2, "removed": 1}
    assert (await owner.get("/api/transactions", params={"direction": "move"})).json()["total"] == 3
    assert len(await wallets_by_name(owner)) == 4

    deleted = await owner.send("DELETE", f"/api/wallets/{old['id']}?move_to={new['id']}")
    gone = deleted.json()
    assert {"moved": gone["moved"], "removed": gone["removed"]} == preview.json()


async def test_summary_has_put_away_total_out_and_the_saving_rate(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    card = await add(owner, "Visa", "card")
    ibkr = await add(owner, "IBKR", "investment")
    savings = await add(owner, "Rainy day", "savings")
    await owner.send(
        "POST", "/api/transactions", {"direction": "in", "amount": "5000", "date": "2026-09-01"}
    )
    for amount in ("1500", "1100"):
        await owner.send(
            "POST", "/api/transactions", {"direction": "out", "amount": amount, "date": DAY}
        )
    await move(owner, "900", card["id"])
    await move(owner, "1000", ibkr["id"])
    await move(owner, "500", savings["id"])
    await move(
        owner, "300", (await wallets_by_name(owner))["Spending"]["id"], from_wallet_id=savings["id"]
    )

    summary = (await owner.get("/api/summary", params={"start": "2026-09-01"})).json()
    out, received = summary["totals"]
    assert out["total"]["amount"] == "2600.0000" and out["count"] == 2  # no move in it
    assert received["total"]["amount"] == "5000.0000" and received["count"] == 1
    assert summary["put_away"] == {"amount": "1200.0000", "currency": "SGD"}
    assert summary["total_out"] == {"amount": "4100.0000", "currency": "SGD"}
    assert summary["saving_rate"] == 0.24

    # Without money in there is no rate, but the sums are still there.
    quiet = (
        await owner.get("/api/summary", params={"start": "2026-09-10", "end": "2026-09-25"})
    ).json()
    assert quiet["saving_rate"] is None
    assert quiet["put_away"]["amount"] == "1200.0000"


async def test_csv_export_has_the_move_and_its_wallets(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await add(owner, "IBKR", "investment")
    await move(owner, "800", ibkr["id"])
    await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "5", "date": DAY})
    text = (await owner.get("/api/export.csv")).text
    header, *rows = text.strip().split("\r\n")
    assert header.split(",")[:3] == ["date", "direction", "amount"]
    assert header.endswith(",status,source,from_wallet,to_wallet")
    moved = next(r for r in rows if ",move," in r)
    assert moved.endswith(",confirmed,manual,Spending,IBKR")
    spent = next(r for r in rows if ",out," in r)
    assert spent.endswith(",confirmed,manual,,")
    only = (await owner.get("/api/export.csv", params={"direction": "move"})).text.strip()
    assert len(only.split("\r\n")) == 2


async def test_other_users_wallets_do_not_exist(world: World) -> None:
    owner, token = await owner_and_invite(world)
    member = world.browser()
    await member.login(MEMBER, invite=token)
    theirs = await add(owner, "IBKR", "investment")
    mine = await add(member, "Mine", "savings")
    assert (await member.get(f"/api/wallets/{theirs['id']}/delete-preview")).status_code == 404
    assert [w["name"] for w in (await member.get("/api/wallets")).json()] == ["Spending", "Mine"]

    assert (
        await member.send("PATCH", f"/api/wallets/{theirs['id']}", {"name": "x"})
    ).status_code == 404
    assert (await member.send("DELETE", f"/api/wallets/{theirs['id']}")).status_code == 404
    # ... nor can their wallet be a move's target, origin or the place a delete moves to.
    assert (
        await member.send("POST", "/api/moves", {"amount": "5", "to_wallet_id": theirs["id"]})
    ).status_code == 404
    assert (
        await member.send(
            "POST",
            "/api/moves",
            {"amount": "5", "to_wallet_id": mine["id"], "from_wallet_id": theirs["id"]},
        )
    ).status_code == 404
    await move(member, "5", mine["id"])
    assert (
        await member.send("DELETE", f"/api/wallets/{mine['id']}?move_to={theirs['id']}")
    ).status_code == 404
    tx = (await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "9"})).json()
    assert (
        await member.send("POST", f"/api/transactions/{tx['id']}/move", {"wallet_id": mine["id"]})
    ).status_code == 404
    assert (
        await owner.send("POST", f"/api/transactions/{tx['id']}/move", {"wallet_id": mine["id"]})
    ).status_code == 404


async def test_budgets_month_has_left_to_spend_and_the_plan_check(world: World) -> None:
    owner = world.browser()  # the clock says 28 September, noon in Singapore; the user's UTC
    await owner.login(OWNER)
    spend = {"direction": "out", "date": DAY}
    await owner.send(
        "POST", "/api/transactions", {"direction": "in", "amount": "5000", "date": "2026-09-01"}
    )
    for amount in ("1500", "1100"):
        await owner.send("POST", "/api/transactions", {**spend, "amount": amount})
    bills = [
        {"name": "Phone plan", "due": "2026-09-29", "amount": "300"},
        {"name": "IBKR top-up", "due": "2026-09-30", "amount": "1000", "spending": False},
    ]
    for body in bills:
        assert (await owner.send("POST", "/api/bills", body)).status_code == 201

    plain = (await owner.get("/api/budgets/month")).json()

    def money(amount: int) -> dict[str, str]:
        return {"amount": f"{amount}.0000", "currency": "SGD"}

    assert plain == {
        "currency": "SGD",
        "total_out": money(2600),
        "left_to_spend": money(1100),
        "still_due_out": money(1300),
        "income": money(5000),
        "budget_left": None,
        "tighter": None,
        "plan_warning": None,
        "skipped": [],
    }

    assert (await owner.send("PUT", "/api/budgets", {"amount": "4000"})).status_code == 204
    # The list keeps its shape.
    listed = (await owner.get("/api/budgets")).json()
    assert [b["name"] for b in listed] == ["Overall"] and listed[0]["remaining"] == money(1400)
    month = (await owner.get("/api/budgets/month")).json()
    assert month["budget_left"] == money(1400) and month["tighter"] == "left_to_spend"
    assert month["plan_warning"] is None  # nothing to compare with: no pay schedule, no history

    # Pay is 4,500 a month: 4,000 of budget plus the 1,000 top-up is more than that.
    await owner.send("PUT", "/api/salary", {"rule": "monthly_day", "day": 25})
    await owner.send("PUT", "/api/salary/usual", {"amount": "4,500"})
    warned = (await owner.get("/api/budgets/month")).json()
    assert warned["plan_warning"] == (
        "A 4000.00 SGD budget plus 1000.00 SGD of scheduled moves is more than your usual "
        "4500.00 SGD income."
    )
    stranger = world.browser()
    assert (await stranger.get("/api/budgets/month")).status_code == 401
