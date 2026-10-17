"""Scheduled moves through the web API: adding one to a wallet, marking it done, and the
Home nudge with its two actions. Every name and figure is made up."""

from datetime import timedelta
from typing import Any

import pytest

from tests.integration import test_web_api
from tests.integration.test_web_api import MEMBER, OWNER, Browser, World, owner_and_invite

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too


async def wallet(browser: Browser, name: str = "IBKR", kind: str = "investment") -> dict[str, Any]:
    made = await browser.send("POST", "/api/wallets", {"name": name, "kind": kind})
    assert made.status_code == 201, made.text
    created: dict[str, Any] = made.json()
    return created


async def scheduled(browser: Browser, wallet_id: str, due: str = "2026-10-05") -> dict[str, Any]:
    body = {
        "name": "IBKR top-up",
        "due": due,
        "amount": "1,000",
        "spending": False,
        "wallet_id": wallet_id,
    }
    made = await browser.send("POST", "/api/bills", body)
    assert made.status_code == 201, made.text
    created: dict[str, Any] = made.json()
    return created


async def moves(browser: Browser) -> list[dict[str, Any]]:
    found = (await browser.get("/api/transactions?direction=move")).json()
    items: list[dict[str, Any]] = found["items"]
    return items


async def test_a_bill_can_point_at_a_wallet_and_says_so(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await wallet(owner)
    bill = await scheduled(owner, ibkr["id"])
    assert bill["wallet"] == {"id": ibkr["id"], "name": "IBKR", "kind": "investment"}
    assert bill["spending"] is False
    listed = (await owner.get("/api/bills")).json()
    assert [(b["name"], b["wallet"]["name"]) for b in listed] == [("IBKR top-up", "IBKR")]

    plain = {"name": "Rent", "due": "2026-10-01", "amount": "1,800"}
    rent = await owner.send("POST", "/api/bills", plain)
    assert rent.json()["wallet"] is None


async def test_a_wallet_on_a_spending_bill_or_an_unknown_wallet_is_refused(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await wallet(owner)
    spending = {"name": "Rent", "due": "2026-10-01", "wallet_id": ibkr["id"]}  # spending: true
    refused = await owner.send("POST", "/api/bills", spending)
    assert refused.status_code == 422
    unknown = {**spending, "spending": False, "wallet_id": "8e2d6a4e-0000-4000-8000-000000000001"}
    assert (await owner.send("POST", "/api/bills", unknown)).status_code == 404
    home = next(w for w in (await owner.get("/api/wallets")).json() if w["kind"] == "spending")
    to_spending = {**spending, "spending": False, "wallet_id": home["id"]}
    assert (await owner.send("POST", "/api/bills", to_spending)).status_code == 422
    assert (await owner.get("/api/bills")).json() == []


async def test_marking_done_reports_whether_a_move_was_logged(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await wallet(owner)
    bill = await scheduled(owner, ibkr["id"])
    done = await owner.send("POST", f"/api/bills/{bill['id']}/paid")
    assert done.status_code == 200
    assert done.json() == {
        "message": (
            "Marked IBKR top-up (5 Oct) as done and logged a move of 1000.00 SGD from "
            "Spending to IBKR."
        ),
        "logged": False,
        "moved": True,
        "needs_amount": False,
    }
    (move,) = await moves(owner)
    assert move["to_wallet"]["name"] == "IBKR" and move["amount"]["amount"] == "1000.0000"

    # No set amount: marked done, nothing logged, and the page is told to ask.
    body = {
        "name": "Savings top-up",
        "due": "2026-10-06",
        "spending": False,
        "wallet_id": ibkr["id"],
    }
    open_ended = (await owner.send("POST", "/api/bills", body)).json()
    nothing = await owner.send("POST", f"/api/bills/{open_ended['id']}/paid")
    assert (nothing.json()["moved"], nothing.json()["needs_amount"]) == (False, True)
    assert len(await moves(owner)) == 1


async def test_the_nudge_flows_through_home_and_its_actions_settle_it(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await wallet(owner)
    went = await scheduled(owner, ibkr["id"], due="2026-10-05")
    other = (
        await owner.send(
            "POST",
            "/api/bills",
            {
                "name": "Savings top-up",
                "due": "2026-10-05",
                "amount": "300",
                "spending": False,
                "wallet_id": ibkr["id"],
            },
        )
    ).json()

    world.clock.now = world.clock.now.replace(month=10, day=7)  # two days after: too soon
    feed = (await owner.get("/api/home")).json()
    assert [i["kind"] for i in feed] == ["bill", "bill"]
    assert all(i["actions"] == [] for i in feed)

    world.clock.now = world.clock.now + timedelta(days=3)  # five days after
    feed = (await owner.get("/api/home")).json()
    assert [i["kind"] for i in feed] == ["missed_move", "missed_move"]
    top_up = next(i for i in feed if "IBKR top-up" in i["text"])
    assert top_up["text"] == (
        "Your SGD 1,000.00 IBKR top-up on 5 Oct hasn't shown up. Did it go through?"
    )
    assert [(a["key"], a["label"], a["method"]) for a in top_up["actions"]] == [
        ("went_through", "It went through", "POST"),
        ("skip", "Skip this month", "POST"),
    ]
    assert top_up["actions"][0]["path"] == f"/bills/{went['id']}/paid?due=2026-10-05"

    # "It went through": the move is logged and the nudge is gone.
    through = next(a for a in top_up["actions"] if a["key"] == "went_through")
    done = await owner.send(through["method"], "/api" + through["path"])
    assert done.status_code == 200 and done.json()["moved"] is True
    assert len(await moves(owner)) == 1

    # "Skip this month": nothing is logged and the nudge is gone.
    skipped_item = next(i for i in (await owner.get("/api/home")).json() if "Savings" in i["text"])
    skip = next(a for a in skipped_item["actions"] if a["key"] == "skip")
    assert skip["path"] == f"/bills/{other['id']}/skip?due=2026-10-05"
    assert (await owner.send(skip["method"], "/api" + skip["path"])).status_code == 204
    assert (await owner.get("/api/home")).json() == []
    assert len(await moves(owner)) == 1

    # Neither can be pressed twice, or for a date the bill doesn't have.
    assert (await owner.send("POST", "/api" + through["path"])).status_code == 422
    assert (
        await owner.send("POST", f"/api/bills/{went['id']}/skip?due=2026-10-06")
    ).status_code == 422


async def test_the_nudge_is_private_to_its_owner(world: World) -> None:
    owner, token = await owner_and_invite(world)
    member = world.browser()
    await member.login(MEMBER, invite=token)
    ibkr = await wallet(owner)
    bill = await scheduled(owner, ibkr["id"])
    world.clock.now = world.clock.now.replace(month=10, day=10)
    assert [i["kind"] for i in (await owner.get("/api/home")).json()] == ["missed_move"]
    assert (await member.get("/api/home")).json() == []
    assert (await member.send("POST", f"/api/bills/{bill['id']}/skip")).status_code == 404
    assert (await member.send("POST", f"/api/bills/{bill['id']}/paid")).status_code == 404
    assert (await member.get("/api/bills")).json() == []


async def test_deleting_the_wallet_repoints_the_bill(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ibkr = await wallet(owner)
    savings = await wallet(owner, "Savings", "savings")
    await scheduled(owner, ibkr["id"])
    needs = await owner.send("DELETE", f"/api/wallets/{ibkr['id']}")
    assert needs.status_code == 422
    preview = await owner.get(f"/api/wallets/{ibkr['id']}/delete-preview?move_to={savings['id']}")
    assert preview.json() == {"moved": 0, "removed": 0, "bills": 1}
    gone = await owner.send("DELETE", f"/api/wallets/{ibkr['id']}?move_to={savings['id']}")
    assert gone.status_code == 200 and gone.json()["bills"] == 1
    (bill,) = (await owner.get("/api/bills")).json()
    assert bill["wallet"]["name"] == "Savings"
