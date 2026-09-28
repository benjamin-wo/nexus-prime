"""The web API through the real app: login, invites, sessions, CSRF, ledger, export, chat."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.channels.web.telegram_login import sign_for_tests
from nexus.main import Overrides, create_app
from nexus.settings import Settings
from tests.fakes import NOW, FakeTelegram, ScriptedModel, call, models, say, scripted

pytestmark = pytest.mark.integration

ORIGIN = "https://nexus.test"
TOKEN = "123:fake"
OWNER, MEMBER, STRANGER = 555, 666, 777


@dataclass
class Clock:
    now: datetime = NOW


class Browser:
    """One browser: its own cookie jar and CSRF token."""

    def __init__(self, app: Any, clock: Clock) -> None:
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN)
        self.clock = clock
        self.csrf = ""

    async def login(self, telegram_id: int, invite: str | None = None) -> Response:
        signed = sign_for_tests(
            {"id": telegram_id, "first_name": "T", "auth_date": int(self.clock.now.timestamp())},
            TOKEN,
        )
        body: dict[str, Any] = {"telegram": signed}
        if invite:
            body["invite"] = invite
        response = await self.client.post(
            "/api/auth/telegram", json=body, headers={"Origin": ORIGIN}
        )
        if response.status_code == 200:
            self.csrf = response.json()["csrf_token"]
        return response

    async def get(self, path: str, **kw: Any) -> Response:
        return await self.client.get(path, **kw)

    async def send(self, method: str, path: str, json: Any = None, **headers: str) -> Response:
        base = {"Origin": ORIGIN, "X-CSRF-Token": self.csrf}
        base.update(headers)
        return await self.client.request(method, path, json=json, headers=base)


@dataclass
class World:
    app: Any
    clock: Clock
    model: ScriptedModel
    telegram: FakeTelegram

    def browser(self) -> Browser:
        return Browser(self.app, self.clock)


@pytest.fixture
async def world(engine: AsyncEngine, empty_database_url: str) -> AsyncIterator[World]:
    clock = Clock()
    model = scripted()
    telegram = FakeTelegram()
    settings = Settings(
        _env_file=None,
        database_url=empty_database_url,
        telegram_bot_token=TOKEN,
        telegram_webhook_secret="hook",
        admin_telegram_chat_id=OWNER,
        telegram_allowed_user_ids=(MEMBER,),
        web_origin=ORIGIN,
        default_timezone="UTC",
    )
    app = create_app(
        settings,
        Overrides(
            models=models(model),
            telegram=telegram,
            checkpointer=InMemorySaver(),
            clock=lambda: clock.now,
        ),
    )
    async with app.router.lifespan_context(app):
        yield World(app, clock, model, telegram)


async def owner_and_invite(world: World) -> tuple[Browser, str]:
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    invite = await owner.send("POST", "/api/invites")
    assert invite.status_code == 200
    return owner, invite.json()["url"].rsplit("/", 1)[-1]


# --- login and sessions ---------------------------------------------------------------


async def test_owner_logs_in_with_a_hardened_cookie(world: World) -> None:
    owner = world.browser()
    response = await owner.login(OWNER)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "owner"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    me = await owner.get("/api/me")
    assert me.json()["user"]["telegram_user_id"] == OWNER


async def test_login_rejects_forged_expired_and_cross_site(world: World) -> None:
    browser = world.browser()
    forged = sign_for_tests({"id": OWNER, "auth_date": int(NOW.timestamp())}, "999:other")
    bad = await browser.client.post(
        "/api/auth/telegram", json={"telegram": forged}, headers={"Origin": ORIGIN}
    )
    assert bad.status_code == 401

    world.clock.now = NOW + timedelta(days=2)
    stale = sign_for_tests({"id": OWNER, "auth_date": int(NOW.timestamp())}, TOKEN)
    expired = await browser.client.post(
        "/api/auth/telegram", json={"telegram": stale}, headers={"Origin": ORIGIN}
    )
    assert expired.status_code == 401
    assert "expired" in expired.json()["detail"]

    world.clock.now = NOW
    fresh = sign_for_tests({"id": OWNER, "auth_date": int(NOW.timestamp())}, TOKEN)
    cross = await browser.client.post(
        "/api/auth/telegram", json={"telegram": fresh}, headers={"Origin": "https://evil.test"}
    )
    assert cross.status_code == 403


async def test_invites_are_single_use_and_expire(world: World) -> None:
    member = world.browser()
    assert (await member.login(MEMBER)).status_code == 403  # no invite yet

    _, token = await owner_and_invite(world)
    assert (await member.login(MEMBER, invite=token)).status_code == 200
    # Web access sticks; the invite is spent.
    assert (await world.browser().login(MEMBER)).status_code == 200
    assert (await world.browser().login(STRANGER, invite=token)).status_code == 403

    _, second = await owner_and_invite(world)
    world.clock.now = NOW + timedelta(hours=25)
    late = world.browser()
    assert (await late.login(STRANGER, invite=second)).status_code == 403


async def test_only_the_owner_can_invite(world: World) -> None:
    _, token = await owner_and_invite(world)
    member = world.browser()
    await member.login(MEMBER, invite=token)
    assert (await member.send("POST", "/api/invites")).status_code == 403


async def test_sessions_expire_and_log_out(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    assert (await owner.send("POST", "/api/auth/logout")).status_code == 204
    assert (await owner.get("/api/me")).status_code == 401

    await owner.login(OWNER)
    world.clock.now = NOW + timedelta(days=31)
    assert (await owner.get("/api/me")).status_code == 401
    assert (await world.browser().get("/api/transactions")).status_code == 401


async def test_writes_need_csrf_token_and_our_origin(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    body = {"direction": "out", "amount": "3"}
    assert (
        await owner.send("POST", "/api/transactions", body, **{"X-CSRF-Token": ""})
    ).status_code == 403
    assert (
        await owner.send("POST", "/api/transactions", body, Origin="https://evil.test")
    ).status_code == 403
    assert (await owner.send("POST", "/api/transactions", body)).status_code == 201


# --- ledger -----------------------------------------------------------------------------


async def test_ledger_round_trip(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    cats = (await owner.get("/api/categories")).json()
    food = next(c for c in cats if c["name"] == "Food & Drink")

    made = await owner.send(
        "POST",
        "/api/transactions",
        {
            "direction": "out",
            "amount": "12.40",
            "counterparty": "Maxwell",
            "category_id": food["id"],
            "date": "2026-09-27",
        },
    )
    assert made.status_code == 201
    tx = made.json()
    assert tx["amount"] == {"amount": "12.4000", "currency": "SGD"}
    assert tx["occurred_at"].startswith("2026-09-27T12:00")

    edited = await owner.send("PATCH", f"/api/transactions/{tx['id']}", {"notes": "laksa"})
    assert edited.json()["notes"] == "laksa"
    cleared = await owner.send("PATCH", f"/api/transactions/{tx['id']}", {"category_id": None})
    assert cleared.json()["category_id"] is None

    page = (await owner.get("/api/transactions", params={"search": "max"})).json()
    assert page["total"] == 1

    summary = (await owner.get("/api/summary", params={"start": "2026-09-01"})).json()
    assert summary["totals"] == [
        {"direction": "out", "total": {"amount": "12.4000", "currency": "SGD"}, "count": 1}
    ]

    assert (await owner.send("DELETE", f"/api/transactions/{tx['id']}")).json()["deleted"]
    assert (await owner.get("/api/transactions")).json()["total"] == 0
    undone = await owner.send("POST", "/api/undo")
    assert undone.json()["undone"] == "delete"
    assert (await owner.get("/api/transactions")).json()["total"] == 1

    bad = await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "0"})
    assert bad.status_code == 422


async def test_bulk_delete_and_undo(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    ids = [
        (
            await owner.send("POST", "/api/transactions", {"direction": "out", "amount": str(n)})
        ).json()["id"]
        for n in (1, 2, 3)
    ]
    gone = await owner.send("POST", "/api/transactions/bulk-delete", {"ids": ids[:2]})
    assert sorted(gone.json()["ids"]) == sorted(ids[:2])
    assert (await owner.get("/api/transactions")).json()["total"] == 1
    back = await owner.send("POST", "/api/transactions/bulk-restore", {"ids": ids[:2]})
    assert len(back.json()["ids"]) == 2
    assert (await owner.get("/api/transactions")).json()["total"] == 3


async def test_other_users_data_does_not_exist(world: World) -> None:
    owner, token = await owner_and_invite(world)
    theirs = (
        await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "9"})
    ).json()
    owner_cat = (await owner.get("/api/categories")).json()[0]["id"]

    member = world.browser()
    await member.login(MEMBER, invite=token)
    tid = theirs["id"]
    assert (
        await member.send("PATCH", f"/api/transactions/{tid}", {"notes": "x"})
    ).status_code == 404
    assert (await member.send("DELETE", f"/api/transactions/{tid}")).status_code == 404
    assert (await member.send("POST", f"/api/transactions/{tid}/restore")).status_code == 404
    mine = (
        await member.send("POST", "/api/transactions", {"direction": "out", "amount": "1"})
    ).json()
    mixed = await member.send("POST", "/api/transactions/bulk-delete", {"ids": [mine["id"], tid]})
    assert mixed.status_code == 404
    assert (await member.get("/api/transactions")).json()["total"] == 1  # nothing deleted
    assert (await member.send(
        "POST", "/api/transactions", {"direction": "out", "amount": "1", "category_id": owner_cat}
    )).status_code == 404  # fmt: skip
    assert (
        await member.send("PATCH", f"/api/categories/{owner_cat}", {"name": "x"})
    ).status_code == 404
    assert (await owner.get("/api/transactions")).json()["total"] == 1


async def test_csv_export(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await owner.send(
        "POST", "/api/transactions", {"direction": "out", "amount": "5", "counterparty": "=1+1"}
    )
    await owner.send("POST", "/api/transactions", {"direction": "in", "amount": "100"})
    response = await owner.get("/api/export.csv", params={"direction": "out"})
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="nexus-ledger-20260928.csv"' in response.headers["content-disposition"]
    lines = response.text.strip().split("\r\n")
    assert len(lines) == 2 and ",'=1+1," in lines[1]


# --- chat ---------------------------------------------------------------------------------


async def test_chat_with_confirmation(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    tx = (await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "7"})).json()
    world.model.script += [call("delete_transaction", transaction_id=tx["id"]), say("Deleted.")]
    replies = (await owner.send("POST", "/api/chat", {"message": "delete the 7"})).json()
    assert replies[0]["text"].startswith("Delete ")
    confirm = replies[0]["buttons"][0][0]["data"]
    done = (await owner.send("POST", "/api/chat/press", {"data": confirm})).json()
    assert done[0]["text"] == "Deleted."
    assert (await owner.get("/api/transactions")).json()["total"] == 0


async def test_telegram_invite_command(world: World, engine: AsyncEngine) -> None:
    from nexus.channels.telegram.webhook import handle_update

    runtime = world.app.state.telegram
    base = {"chat": {"type": "private"}, "text": "/invite"}
    await handle_update(
        runtime,
        {"update_id": 1, "message": {**base, "message_id": 1, "from": {"id": OWNER},
                                     "chat": {"id": OWNER, "type": "private"}}},
    )  # fmt: skip
    link = world.telegram.sent[-1].text
    assert f"{ORIGIN}/invite/" in link
    await handle_update(
        runtime,
        {"update_id": 2, "message": {**base, "message_id": 2, "from": {"id": MEMBER},
                                     "chat": {"id": MEMBER, "type": "private"}}},
    )  # fmt: skip
    assert world.telegram.sent[-1].text == "Only the owner can invite people."

    token = link.rsplit("/", 1)[-1]
    assert (await world.browser().login(MEMBER, invite=token)).status_code == 200
