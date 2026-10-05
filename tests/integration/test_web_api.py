"""The web API through the real app: login, invites, sessions, CSRF, ledger, export, chat."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient, Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import bills as bill_cases
from nexus.application import departments as department_cases
from nexus.application import email as email_cases
from nexus.application import market as market_cases
from nexus.application import receipts as receipt_cases
from nexus.application import research as research_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application.transactions import NewTransaction, log_transaction
from nexus.channels.web.telegram_login import sign_for_tests, sign_webapp_for_tests
from nexus.domain.ledger import Direction, Source, UserId
from nexus.domain.money import Money
from nexus.infra.crypto.fernet import FernetCipher
from nexus.infra.db.tables import jobs, users
from nexus.infra.db.uow import SqlUnitOfWork
from nexus.main import Overrides, create_app
from nexus.settings import Settings
from tests.fakes import (
    NOW,
    FakeBucket,
    FakeEmailReader,
    FakeForwarding,
    FakeHoldings,
    FakeMailbox,
    FakeNews,
    FakePrices,
    FakeRates,
    FakeTelegram,
    ScriptedModel,
    call,
    fake_email,
    models,
    say,
    scripted,
)
from tests.integration.conftest import UowFactory
from tests.integration.test_departments import Shown

pytestmark = pytest.mark.integration

ORIGIN = "https://nexus.test"
TEST_KEY = Fernet.generate_key().decode()
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
    rates: FakeRates
    bucket: FakeBucket
    engine: AsyncEngine
    mailbox: FakeMailbox
    forwarding: FakeForwarding

    def browser(self) -> Browser:
        return Browser(self.app, self.clock)


@pytest.fixture
async def world(engine: AsyncEngine, empty_database_url: str) -> AsyncIterator[World]:
    clock = Clock()
    bucket = FakeBucket()
    mailbox = FakeMailbox()
    forwarding = FakeForwarding()
    model = scripted()
    telegram = FakeTelegram()
    rates = FakeRates({("USD", "SGD"): {date(2026, 9, 25): "1.2905", date(2026, 9, 28): "1.3000"}})
    settings = Settings(
        _env_file=None,
        database_url=empty_database_url,
        telegram_bot_token=TOKEN,
        telegram_webhook_secret="hook",
        admin_telegram_chat_id=OWNER,
        telegram_allowed_user_ids=(MEMBER,),
        web_origin=ORIGIN,
        default_timezone="UTC",
        google_client_id="cid",
        google_client_secret="secret",
        token_encryption_key=TEST_KEY,
        agentmail_api_key="am_test",
    )
    app = create_app(
        settings,
        Overrides(
            models=models(model),
            telegram=telegram,
            checkpointer=InMemorySaver(),
            clock=lambda: clock.now,
            rates=rates,
            receipt_store=bucket,
            mailbox=mailbox,
            forwarding=forwarding,
            email_reader=FakeEmailReader(),
            holdings=FakeHoldings(),
            prices=FakePrices(),
            news=FakeNews(),
        ),
    )
    async with app.router.lifespan_context(app):
        yield World(app, clock, model, telegram, rates, bucket, engine, mailbox, forwarding)


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


# --- Telegram Mini App ------------------------------------------------------------------


def init_data(telegram_id: int, auth_date: datetime = NOW, token: str = TOKEN) -> str:
    fields = {
        "query_id": "AAH",
        "user": json.dumps({"id": telegram_id, "first_name": "T", "username": "t"}),
        "auth_date": str(int(auth_date.timestamp())),
    }
    return sign_webapp_for_tests(fields, token)


async def test_mini_app_signs_in_without_the_widget(world: World) -> None:
    browser = world.browser()
    response = await browser.client.post(
        "/api/auth/webapp", json={"init_data": init_data(OWNER)}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "owner"
    cookie = response.headers["set-cookie"].lower()
    # Telegram's web clients embed the app in an iframe.
    assert "samesite=none" in cookie and "partitioned" in cookie and "secure" in cookie
    browser.csrf = response.json()["csrf_token"]
    assert (await browser.get("/api/me")).json()["user"]["telegram_user_id"] == OWNER
    made = await browser.send("POST", "/api/transactions", {"direction": "out", "amount": "3"})
    assert made.status_code == 201


async def test_mini_app_rejects_forged_expired_uninvited_and_cross_site(world: World) -> None:
    client = world.browser().client

    async def attempt(data: str, origin: str = ORIGIN) -> Response:
        return await client.post(
            "/api/auth/webapp", json={"init_data": data}, headers={"Origin": origin}
        )

    assert (await attempt(init_data(OWNER, token="999:other"))).status_code == 401
    assert (await attempt(init_data(OWNER, NOW - timedelta(days=2)))).status_code == 401
    assert (await attempt(init_data(OWNER) + "&user=%7B%22id%22%3A1%7D")).status_code == 401
    assert (await attempt("not-init-data")).status_code == 401
    assert (await attempt(init_data(STRANGER))).status_code == 403
    assert (await attempt(init_data(MEMBER))).status_code == 403  # allow-listed, no invite
    assert (await attempt(init_data(OWNER), "https://evil.test")).status_code == 403


async def test_bot_offers_the_mini_app(world: World) -> None:
    await asyncio.sleep(0)  # the menu button is set in the background at startup
    assert world.telegram.menu_button == ("Open Nexus", f"{ORIGIN}/")
    async with AsyncClient(transport=ASGITransport(app=world.app), base_url=ORIGIN) as client:
        update = {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": OWNER},
                "chat": {"id": OWNER, "type": "private"},
                "text": "/app",
            },
        }
        response = await client.post(
            "/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "hook"}
        )
    assert response.status_code == 200
    assert world.telegram.app_buttons == [(OWNER, "Open Nexus", f"{ORIGIN}/")]


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


async def test_categories_add_rename_archive(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    names = [c["name"] for c in (await owner.get("/api/categories")).json()]
    assert len(names) == 12 and "Other" in names

    made = await owner.send("POST", "/api/categories", {"name": "Pets"})
    assert made.status_code == 201
    pets = made.json()["id"]
    # Names are unique regardless of case, for adding and renaming alike.
    assert (await owner.send("POST", "/api/categories", {"name": "pets"})).status_code == 409
    clash = await owner.send("PATCH", f"/api/categories/{pets}", {"name": "groceries"})
    assert clash.status_code == 409

    renamed = await owner.send("PATCH", f"/api/categories/{pets}", {"name": "Pet care"})
    assert renamed.json()["name"] == "Pet care"
    await owner.send("PATCH", f"/api/categories/{pets}", {"active": False})
    active = [c["name"] for c in (await owner.get("/api/categories")).json()]
    assert "Pet care" not in active
    every = (await owner.get("/api/categories?include_inactive=true")).json()
    assert {"name": "Pet care", "active": False} in [
        {"name": c["name"], "active": c["active"]} for c in every
    ]

    # Merging moves its expenses over and archives it; merging into itself is refused.
    await owner.send("PATCH", f"/api/categories/{pets}", {"active": True})
    other = next(c["id"] for c in every if c["name"] == "Other")
    await owner.send(
        "POST", "/api/transactions",
        {"direction": "out", "amount": "9", "category_id": pets, "date": "2026-09-27"},
    )  # fmt: skip
    merged = await owner.send("POST", f"/api/categories/{pets}/merge", {"into_id": other})
    assert merged.status_code == 200
    assert merged.json()["moved"] == 1 and merged.json()["into"]["name"] == "Other"
    same = await owner.send("POST", f"/api/categories/{other}/merge", {"into_id": other})
    assert same.status_code == 422


async def test_ledger_round_trip(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    cats = (await owner.get("/api/categories")).json()
    food = next(c for c in cats if c["name"] == "Dining Out")

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
    assert summary["currency"] == "SGD"
    assert summary["totals"] == [
        {
            "direction": "out",
            "total": {"amount": "12.4000", "currency": "SGD"},
            "count": 1,
            "converted": [],
            "unconverted": [],
        },
        {
            "direction": "in",
            "total": {"amount": "0.0000", "currency": "SGD"},
            "count": 0,
            "converted": [],
            "unconverted": [],
        },
    ]
    assert world.rates.asked == []  # nothing foreign, nothing looked up

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


# --- foreign currencies -----------------------------------------------------------------


async def spend(owner: Browser, amount: str, currency: str, day: str, **extra: Any) -> Any:
    body = {"direction": "out", "amount": amount, "currency": currency, "date": day, **extra}
    made = await owner.send("POST", "/api/transactions", body)
    assert made.status_code == 201
    return made.json()


async def test_foreign_rows_show_home_amount_at_their_days_rate(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await spend(owner, "10", "SGD", "2026-09-27")
    await spend(owner, "33.80", "USD", "2026-09-26")  # a Saturday: Friday's rate
    await spend(owner, "5000", "JPY", "2026-09-26")  # no rate published

    rows = {
        r["amount"]["currency"]: r for r in (await owner.get("/api/transactions")).json()["items"]
    }
    assert rows["SGD"]["home"] is None
    assert rows["USD"]["amount"] == {"amount": "33.8000", "currency": "USD"}
    assert rows["USD"]["home"] == {
        "amount": {"amount": "43.6200", "currency": "SGD"},  # 33.80 x 1.2905 = 43.6189
        "rate": "1.2905",
        "rate_date": "2026-09-25",  # never the later 2026-09-28 rate
    }
    assert rows["JPY"]["home"] == {"amount": None, "rate": None, "rate_date": None}


async def test_summary_is_in_home_currency(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    food = next(c for c in (await owner.get("/api/categories")).json() if c["name"] == "Dining Out")
    await spend(owner, "10", "SGD", "2026-09-27", category_id=food["id"])
    await spend(owner, "20", "USD", "2026-09-26", category_id=food["id"])
    await spend(owner, "30", "USD", "2026-09-28")
    await spend(owner, "5000", "JPY", "2026-09-26")
    await owner.send(
        "POST",
        "/api/transactions",
        {"direction": "in", "amount": "100", "currency": "USD", "date": "2026-09-01"},
    )  # before any published rate

    summary = (await owner.get("/api/summary", params={"start": "2026-09-01"})).json()
    out, received = summary["totals"]
    # 10 + 20 x 1.2905 (25.81) + 30 x 1.3000 (39.00)
    assert out["total"] == {"amount": "74.8100", "currency": "SGD"}
    assert out["count"] == 3
    assert out["converted"] == [{"amount": "50.0000", "currency": "USD"}]
    assert out["unconverted"] == [{"amount": "5000.0000", "currency": "JPY"}]
    assert received["total"] == {"amount": "0.0000", "currency": "SGD"}
    assert received["unconverted"] == [{"amount": "100.0000", "currency": "USD"}]
    by_cat = [(c["category_name"], c["total"]["amount"]) for c in summary["by_category"]]
    assert by_cat == [("Other", "39.0000"), ("Dining Out", "35.8100")]


async def test_export_has_home_currency_columns(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    await spend(owner, "33.80", "USD", "2026-09-26")
    await spend(owner, "5000", "JPY", "2026-09-26")
    lines = (await owner.get("/api/export.csv")).text.strip().split("\r\n")
    assert lines[0].startswith("date,direction,amount,currency,home_amount,home_currency,fx_rate,")
    assert "2026-09-26,out,33.8000,USD,43.6200,SGD,1.2905,2026-09-25," in response_lines(lines)
    assert "2026-09-26,out,5000.0000,JPY,,,,," in response_lines(lines)


def response_lines(lines: list[str]) -> str:
    return "\n".join(lines)


# --- budgets --------------------------------------------------------------------------


async def test_budgets_round_trip(world: World) -> None:
    owner, token = await owner_and_invite(world)
    food = next(c for c in (await owner.get("/api/categories")).json() if c["name"] == "Dining Out")
    assert (await owner.get("/api/budgets")).json() == []
    for body in ({"amount": "1,000"}, {"category_id": food["id"], "amount": "100"}):
        assert (await owner.send("PUT", "/api/budgets", body)).status_code == 204
    await spend(owner, "85", "SGD", "2026-09-27", category_id=food["id"])
    await spend(owner, "20", "USD", "2026-09-26", category_id=food["id"])  # 25.81 SGD
    overall, meal = (await owner.get("/api/budgets")).json()
    assert overall["name"] == "Overall" and overall["limit"]["amount"] == "1000.0000"
    assert meal["name"] == "Dining Out"
    assert meal["spent"] == {"amount": "110.8100", "currency": "SGD"}
    assert meal["percent"] == 110 and meal["remaining"]["amount"] == "-10.8100"

    bad = await owner.send("PUT", "/api/budgets", {"amount": "0"})
    assert bad.status_code == 422
    csrf = await owner.client.put("/api/budgets", json={"amount": "5"}, headers={"Origin": ORIGIN})
    assert csrf.status_code == 403

    member = world.browser()
    await member.login(MEMBER, invite=token)
    assert (await member.get("/api/budgets")).json() == []
    assert (await member.send("DELETE", f"/api/budgets/{meal['id']}")).status_code == 404
    theirs = await member.send("PUT", "/api/budgets", {"category_id": food["id"], "amount": "5"})
    assert theirs.status_code == 404  # someone else's category

    assert (await owner.send("DELETE", f"/api/budgets/{meal['id']}")).status_code == 204
    assert [b["name"] for b in (await owner.get("/api/budgets")).json()] == ["Overall"]


# --- receipts -------------------------------------------------------------------------


async def user_id(world: World, telegram_id: int) -> UserId:
    async with world.engine.connect() as db:
        found = await db.scalar(select(users.c.id).where(users.c.telegram_user_id == telegram_id))
    assert found is not None
    return UserId(found)


async def test_receipt_links_are_short_lived_and_private(world: World) -> None:
    owner, token = await owner_and_invite(world)
    me = await user_id(world, OWNER)

    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(world.engine)

    stored = await receipt_cases.stash(uow(), world.bucket, me, b"img", "image/png", now=NOW)
    cmd = NewTransaction(Direction.OUT, Money.of("8", "SGD"), NOW, source=Source.PHOTO)
    tx = await receipt_cases.log_with_receipt(uow(), me, cmd, stored.id, now=NOW)
    await spend(owner, "3", "SGD", "2026-09-28")

    rows = {
        r["id"]: r["has_receipt"] for r in (await owner.get("/api/transactions")).json()["items"]
    }
    assert rows[str(tx.id)] is True and list(rows.values()).count(True) == 1

    link = await owner.get(f"/api/transactions/{tx.id}/receipt")
    assert link.status_code == 303
    assert link.headers["location"].startswith(
        f"https://bucket.test/{stored.object_key}?expires=300"
    )
    assert link.headers["cache-control"] == "no-store"

    member = world.browser()
    await member.login(MEMBER, invite=token)
    assert (await member.get(f"/api/transactions/{tx.id}/receipt")).status_code == 404
    assert (await world.browser().get(f"/api/transactions/{tx.id}/receipt")).status_code == 401

    assert (await owner.send("DELETE", f"/api/transactions/{tx.id}")).status_code == 200
    assert (await owner.get(f"/api/transactions/{tx.id}/receipt")).status_code == 404


# --- Connect Gmail -------------------------------------------------------------------


async def test_connect_gmail_from_a_one_time_link(world: World) -> None:
    owner, token = await owner_and_invite(world)
    made = await owner.send("POST", "/api/email/link")
    url = made.json()["url"]
    assert url.startswith(f"{ORIGIN}/connect/gmail?t=")
    link = url.split("t=", 1)[1]

    # The link works in a browser with no Nexus session (opened from Telegram).
    phone = world.browser()
    check = (await phone.get(f"/api/email/link?t={link}")).json()
    assert check == {"valid": True, "account_hint": str(OWNER)[-4:]}
    start = await phone.get(f"/api/email/gmail/start?t={link}")
    assert start.status_code == 303
    assert start.headers["location"].startswith(f"https://accounts.test/auth?state={link}")
    world.mailbox.emails["m1"] = fake_email(
        "m1", "Your Grab e-receipt", "Merchant: Grab\nTotal: 18.50", at=NOW - timedelta(days=1)
    )
    done = await phone.get(f"/api/email/gmail/callback?state={link}&code=ok")
    assert done.headers["location"] == "/connect/gmail/done?ok=1"
    again = await phone.get(f"/api/email/gmail/callback?state={link}&code=ok")
    assert again.headers["location"] == "/connect/gmail/done?error=expired"
    assert (await phone.get(f"/api/email/link?t={link}")).json()["valid"] is False
    declined = await phone.get("/api/email/gmail/callback?state=x&error=access_denied")
    assert declined.headers["location"] == "/connect/gmail/done?error=declined"

    # Connecting queues the look-back sweep and tells the user in Telegram.
    async with world.engine.connect() as db:
        kinds = [r[0] for r in await db.execute(select(jobs.c.kind).order_by(jobs.c.id))]
    assert kinds[-2:] == ["email.sweep", "telegram.send"]

    def uow() -> SqlUnitOfWork:
        return SqlUnitOfWork(world.engine)

    me = await user_id(world, OWNER)
    async with uow() as tx:
        [connection] = await tx.email.list_connections(me)
        user = await tx.ledger.get_user(me)
    assert user is not None
    cipher = FernetCipher(TEST_KEY)
    await email_cases.sweep(
        uow, world.mailbox, FakeEmailReader(), cipher, None, user, connection, now=NOW
    )
    page = (await owner.get("/api/email")).json()
    assert page["available"] is True
    assert [c["address"] for c in page["connections"]] == ["ann@gmail.com"]
    [email] = page["emails"]
    assert (email["status"], email["merchant"], email["actionable"]) == ("pending", "Grab", True)

    member = world.browser()
    await member.login(MEMBER, invite=token)
    assert (await member.get("/api/email")).json()["emails"] == []
    assert (await member.send("POST", f"/api/email/{email['id']}/log", {})).status_code == 404
    other = f"/api/email/connections/{connection.id}"
    assert (await member.send("DELETE", other)).status_code == 404

    assert (await owner.send("POST", f"/api/email/{email['id']}/log", {})).status_code == 204
    [row] = (await owner.get("/api/transactions")).json()["items"]
    assert (row["source"], row["counterparty"]) == ("email", "Grab")
    assert (await owner.send("DELETE", other)).status_code == 204
    assert (await owner.get("/api/email")).json()["connections"] == []
    assert world.mailbox.revocations == ["refresh-token-1"]


async def test_the_bot_offers_connecting_through_its_tool(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    world.model.script += [call("connect_email"), say("Tap the button to connect Gmail.")]
    ask = {"message": "can you log my expenses automatically?"}
    [reply] = (await owner.send("POST", "/api/chat", ask)).json()
    [[button]] = reply["buttons"]
    assert button["label"] == "Connect Gmail"
    assert button["data"].startswith(f"url:{ORIGIN}/connect/gmail?t=")


async def test_the_bot_gives_a_forwarding_address_when_asked(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    world.model.script += [
        call("forward_email", provider="outlook"),
        say("Here's your address and the steps."),
    ]
    ask = {"message": "I use outlook, can you log my receipts automatically?"}
    [reply] = (await owner.send("POST", "/api/chat", ask)).json()
    assert reply["text"] == "Here's your address and the steps."
    result = world.model.seen[-1][-1].content
    assert "nexus-inbox-1@agentmail.test" in result and "Subject includes" in result
    overview = (await owner.get("/api/email")).json()
    assert overview["available"] and overview["forwarding_available"]
    [connection] = overview["connections"]
    assert connection["provider"] == "forward"
    assert connection["address"] == "nexus-inbox-1@agentmail.test"
    assert connection["last_received"] is None

    world.model.script += [call("test_email_setup"), say("Send the test email now.")]
    [reply] = (await owner.send("POST", "/api/chat", {"message": "test my setup"})).json()
    assert '"Nexus test receipt"' in world.model.seen[-1][-1].content


# --- category rules -------------------------------------------------------------------


async def test_category_rules_round_trip(world: World) -> None:
    owner, token = await owner_and_invite(world)
    cats = {c["name"]: c["id"] for c in (await owner.get("/api/categories")).json()}
    ride = await spend(owner, "12", "SGD", "2026-09-27", counterparty="Grab")
    assert ride["category_id"] == cats["Other"] and ride["category_rule_id"] is None

    # Correcting the category offers a rule; nothing is saved until it's accepted.
    edited = await owner.send(
        "PATCH", f"/api/transactions/{ride['id']}", {"category_id": cats["Transport"]}
    )
    offer = edited.json()["rule_suggestion"]
    assert offer == {
        "question": "Always file “grab” under Transport?",
        "pattern": "grab",
        "category_id": cats["Transport"],
        "replaces_category_id": None,
    }
    assert (await owner.get("/api/category-rules")).json() == []
    # An edit that leaves the category alone offers nothing.
    notes = await owner.send("PATCH", f"/api/transactions/{ride['id']}", {"notes": "airport"})
    assert notes.json()["rule_suggestion"] is None

    accepted = await owner.send(
        "POST", "/api/category-rules/accept", {"transaction_id": ride["id"]}
    )
    assert accepted.status_code == 204
    [rule] = (await owner.get("/api/category-rules")).json()
    assert rule["pattern"] == "grab" and rule["category_name"] == "Transport"
    assert rule["explanation"].startswith("Added on 28 Sep 2026 when you filed “Grab”")

    nxt = await spend(owner, "9", "SGD", "2026-09-28", counterparty="GRAB")
    assert (nxt["category_id"], nxt["category_rule_id"]) == (cats["Transport"], rule["id"])
    why = await owner.get(f"/api/transactions/{nxt['id']}/category-explanation")
    assert why.json()["text"].startswith("It's in Transport because of your rule “grab”.")

    made = await owner.send(
        "PUT", "/api/category-rules", {"pattern": "Netflix", "category_id": cats["Activities"]}
    )
    assert made.status_code == 204
    assert [r["pattern"] for r in (await owner.get("/api/category-rules")).json()] == [
        "grab",
        "netflix",
    ]
    short = {"pattern": "x", "category_id": cats["Travel"]}
    assert (await owner.send("PUT", "/api/category-rules", short)).status_code == 422

    member = world.browser()
    await member.login(MEMBER, invite=token)
    assert (await member.get("/api/category-rules")).json() == []
    assert (await member.send("DELETE", f"/api/category-rules/{rule['id']}")).status_code == 404
    taxi = {"pattern": "taxi", "category_id": cats["Transport"]}  # the owner's category
    assert (await member.send("PUT", "/api/category-rules", taxi)).status_code == 404
    accept = {"transaction_id": ride["id"]}
    assert (await member.send("POST", "/api/category-rules/accept", accept)).status_code == 404
    explain = f"/api/transactions/{ride['id']}/category-explanation"
    assert (await member.get(explain)).status_code == 404
    theirs = await spend(member, "5", "SGD", "2026-09-28", counterparty="Grab")
    assert theirs["category_rule_id"] is None  # the owner's rules are theirs alone

    assert (await owner.send("DELETE", f"/api/category-rules/{rule['id']}")).status_code == 204
    assert [r["pattern"] for r in (await owner.get("/api/category-rules")).json()] == ["netflix"]


# --- bills ----------------------------------------------------------------------------


async def test_bills_and_reminder_buttons(world: World) -> None:
    owner, token = await owner_and_invite(world)
    made = await owner.send(
        "POST", "/api/bills", {"name": "Rent", "due": "2026-09-30", "amount": "1,800"}
    )
    assert made.status_code == 201
    bill = made.json()
    assert bill["amount"] == {"amount": "1800.0000", "currency": "SGD"}
    assert (bill["cadence"], bill["days_until"], bill["snoozed"]) == ("monthly", 2, False)
    once = {"name": "Visa", "due": "2026-10-10", "cadence": "once"}
    assert (await owner.send("POST", "/api/bills", once)).status_code == 201
    assert [b["name"] for b in (await owner.get("/api/bills")).json()] == ["Rent", "Visa"]

    # The reminder sweep queues a message whose buttons work from the web chat too.
    web = world.app.state.web
    async with web.uow() as tx:
        user = await tx.ledger.get_user_by_telegram_id(OWNER)
    assert user is not None
    assert await bill_cases.send_reminders(web.uow, user, now=world.clock.now) == 1
    async with world.app.state.engine.connect() as db:
        (payload,) = [r.payload for r in await db.execute(select(jobs))]
    paid_button = payload["buttons"][0][0]["data"]

    member = world.browser()
    await member.login(MEMBER, invite=token)
    stranger = (await member.send("POST", "/api/chat/press", {"data": paid_button})).json()
    assert "out of date" in stranger[0]["text"]  # not their bill
    assert (await member.send("POST", f"/api/bills/{bill['id']}/paid")).status_code == 404

    done = (await owner.send("POST", "/api/chat/press", {"data": paid_button})).json()
    assert done[0]["text"] == "Marked Rent (30 Sep) as paid."
    again = (await owner.send("POST", "/api/chat/press", {"data": paid_button})).json()
    assert "out of date" in again[0]["text"]
    rent = next(b for b in (await owner.get("/api/bills")).json() if b["name"] == "Rent")
    assert rent["due"] == "2026-10-30"

    assert (await owner.send("POST", f"/api/bills/{bill['id']}/snooze")).status_code == 204
    rent = next(b for b in (await owner.get("/api/bills")).json() if b["name"] == "Rent")
    assert rent["snoozed"] is True
    assert (await owner.send("DELETE", f"/api/bills/{bill['id']}")).status_code == 204
    assert [b["name"] for b in (await owner.get("/api/bills")).json()] == ["Visa"]
    bad = await owner.send("POST", "/api/bills", {"name": "X", "due": "2026-10-01", "amount": "-5"})
    assert bad.status_code == 422


# --- cash flow --------------------------------------------------------------------------


async def test_cash_flow_month_by_month(world: World) -> None:
    owner, token = await owner_and_invite(world)
    await spend(owner, "12", "SGD", "2026-09-10")
    await spend(owner, "10", "USD", "2026-09-26")  # a Saturday: Friday's rate
    flow = (await owner.get("/api/cashflow")).json()
    assert (flow["start"], flow["end"], flow["currency"]) == ("2026-09-01", "2026-09-30", "SGD")
    by_day = {d["day"]: d for d in flow["days"]}
    assert len(by_day) == 30
    assert by_day["2026-09-10"]["net"] == {"amount": "-12.0000", "currency": "SGD"}
    assert by_day["2026-09-26"]["money_out"]["amount"] == "12.9100"
    assert flow["expected_out"] == {"amount": "0.0000", "currency": "SGD"}
    october = (await owner.get("/api/cashflow?month=2026-10")).json()
    assert (october["start"], len(october["days"])) == ("2026-10-01", 31)
    assert (await owner.get("/api/cashflow?month=2026-13")).status_code == 422
    assert (await owner.get("/api/cashflow?month=soon")).status_code == 422
    # Each user sees only their own.
    member = world.browser()
    assert (await member.login(MEMBER, invite=token)).status_code == 200
    theirs = (await member.get("/api/cashflow")).json()
    assert theirs["logged_out"]["amount"] == "0.0000"


# --- subscriptions ----------------------------------------------------------------------


async def test_subscriptions_are_proposed_then_tracked_or_turned_down(
    world: World, uow: UowFactory
) -> None:
    owner, token = await owner_and_invite(world)
    assert (await owner.get("/api/subscriptions")).json() == {
        "tracked": [],
        "proposed": [],
        "monthly_totals": [],
    }
    for day in ("2026-07-10", "2026-08-10", "2026-09-10"):
        await spend(owner, "15.98", "SGD", day, counterparty="Netflix")
        await spend(owner, "10", "SGD", day, counterparty="Spotify")
    async with uow() as tx:
        user = await tx.ledger.get_user_by_telegram_id(OWNER)
    assert user is not None
    await subscription_cases.check(uow, user, now=world.clock.now)
    found = (await owner.get("/api/subscriptions")).json()
    proposed = {p["name"]: p for p in found["proposed"]}
    assert set(proposed) == {"Netflix", "Spotify"}
    netflix = proposed["Netflix"]
    assert netflix["cadence"] == "monthly" and netflix["next_charge"] == "2026-10-10"

    tracked = await owner.send("POST", f"/api/subscriptions/{netflix['id']}/track", {})
    assert tracked.status_code == 204
    skipped = await owner.send(
        "POST", f"/api/subscriptions/{proposed['Spotify']['id']}/dismiss", {}
    )
    assert skipped.status_code == 204
    found = (await owner.get("/api/subscriptions")).json()
    assert [t["name"] for t in found["tracked"]] == ["Netflix"] and found["proposed"] == []
    assert found["monthly_totals"] == [{"amount": "15.9800", "currency": "SGD"}]

    # Someone else's subscription can't be touched.
    member = world.browser()
    assert (await member.login(MEMBER, invite=token)).status_code == 200
    other = await member.send("POST", f"/api/subscriptions/{netflix['id']}/dismiss", {})
    assert other.status_code == 404


# --- telegram updates -------------------------------------------------------------------


async def test_telegram_updates_default_to_daily_and_can_be_changed(world: World) -> None:
    owner, _ = await owner_and_invite(world)
    current = (await owner.get("/api/notifications")).json()
    assert current["frequency"] == "daily"
    assert current["description"] == "You get a summary of your transactions once a day at 9pm."
    assert list(current["options"]) == ["instant", "hourly", "thrice_daily", "daily", "off"]
    changed = await owner.send("PUT", "/api/notifications", {"frequency": "hourly"})
    assert changed.json()["frequency"] == "hourly"
    assert (await owner.get("/api/notifications")).json()["frequency"] == "hourly"
    bad = await owner.send("PUT", "/api/notifications", {"frequency": "weekly"})
    assert bad.status_code == 422


# --- salary -----------------------------------------------------------------------------


async def test_salary_schedule_and_confirming_the_usual_amount(world: World) -> None:
    owner, token = await owner_and_invite(world)
    assert (await owner.get("/api/salary")).json() is None
    body = {"rule": "monthly_day", "day": 25}
    assert (await owner.send("PUT", "/api/salary", body)).status_code == 204
    assert (await owner.send("PUT", "/api/salary/usual", {"amount": "5,000"})).status_code == 204
    pay = (await owner.get("/api/salary")).json()
    assert pay["description"] == "the 25th of each month"
    assert pay["usual"] == {"amount": "5000.0000", "currency": "SGD"}
    assert pay["next_payday"] == "2026-10-23"  # the 25th is a Sunday
    bad = await owner.send("PUT", "/api/salary", {"rule": "monthly_day"})
    assert bad.status_code == 422

    # Reporting a different salary logs it, then asks before changing the usual amount.
    (reply,) = (await owner.send("POST", "/api/chat", {"message": "salary 5200"})).json()
    assert reply["text"] == (
        "Recorded 5200.00 SGD salary. That's different from your usual 5000.00 SGD. "
        "Make 5200.00 SGD your usual salary?"
    )
    yes, no = reply["buttons"][0]
    assert (yes["label"], no["label"]) == ("Yes, update", "No")
    assert (await owner.get("/api/salary")).json()["usual"]["amount"] == "5000.0000"
    (done,) = (await owner.send("POST", "/api/chat/press", {"data": yes["data"]})).json()
    assert done["text"] == "Your usual salary is now 5200.00 SGD."
    assert (await owner.get("/api/salary")).json()["usual"]["amount"] == "5200.0000"
    world.clock.now += timedelta(minutes=1)  # a new message, not a redelivery
    (same,) = (await owner.send("POST", "/api/chat", {"message": "salary 5200"})).json()
    assert same["text"] == "Recorded 5200.00 SGD salary."  # nothing to ask

    # The payday button logs the usual salary once.
    log = {"data": "salary:log:2026-10-23"}
    (logged,) = (await owner.send("POST", "/api/chat/press", log)).json()
    assert logged["text"].startswith("Logged 5200.00 SGD salary.")
    (again,) = (await owner.send("POST", "/api/chat/press", log)).json()
    assert again["text"] == "Your salary for that payday is already logged."

    member = world.browser()
    await member.login(MEMBER, invite=token)
    assert (await member.get("/api/salary")).json() is None
    assert (await member.send("DELETE", "/api/salary")).status_code == 404
    assert (await owner.send("DELETE", "/api/salary")).status_code == 204


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


async def test_widget_redirect_login(world: World) -> None:
    browser = world.browser()
    signed = sign_for_tests({"id": OWNER, "auth_date": int(NOW.timestamp())}, TOKEN)
    ok = await browser.get("/api/auth/telegram/callback", params=signed)
    assert ok.status_code == 303 and ok.headers["location"] == "/"
    assert (await browser.get("/api/me")).status_code == 200

    forged = {**signed, "id": str(MEMBER)}
    bad = await world.browser().get("/api/auth/telegram/callback", params=forged)
    assert bad.headers["location"] == "/login?error=signin"

    member = sign_for_tests({"id": MEMBER, "auth_date": int(NOW.timestamp())}, TOKEN)
    denied = await world.browser().get("/api/auth/telegram/callback", params=member)
    assert denied.headers["location"] == "/login?error=access"

    _, token = await owner_and_invite(world)
    invited = world.browser()
    accepted = await invited.get("/api/auth/telegram/callback", params={**member, "invite": token})
    assert accepted.headers["location"] == "/"
    assert (await invited.get("/api/me")).json()["user"]["role"] == "member"


async def test_config_and_security_headers(world: World) -> None:
    response = await world.browser().get("/api/config")
    assert response.json() == {"bot_username": "nexus_test_bot"}
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "unsafe" not in csp
    assert "frame-ancestors https://web.telegram.org" in csp  # only Telegram may embed us


async def test_what_nexus_remembers(world: World, engine: AsyncEngine) -> None:
    from nexus.application import memory as memory_cases
    from nexus.application.memory import Action, MemoryChange
    from nexus.application.users import get_user
    from nexus.domain.memory import MemoryKind

    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite)).status_code == 200
    # A chat turn queues the memory writer for the user's own words.
    world.model.script += [say("Got it.")]
    await owner.send("POST", "/api/chat", {"message": "ann is my sister"})
    async with engine.connect() as db:
        queued = (await db.execute(select(jobs).where(jobs.c.kind == "memory.update"))).all()
    assert [j.payload["messages"] for j in queued] == [["ann is my sister"]]

    async with engine.connect() as db:
        owner_id: Any = (
            await db.execute(select(users.c.id).where(users.c.telegram_user_id == OWNER))
        ).scalar_one()
    user = await get_user(SqlUnitOfWork(engine), UserId(owner_id))
    await memory_cases.apply_changes(
        SqlUnitOfWork(engine),
        user,
        [
            MemoryChange(Action.ADD, MemoryKind.FACT, "Ann is the user's sister."),
            MemoryChange(Action.ADD, MemoryKind.EPISODE, "Ride was for work.", date(2026, 9, 27)),
        ],
        now=NOW,
    )
    listed = (await owner.get("/api/memories")).json()
    assert {(m["kind"], m["text"]) for m in listed} == {
        ("fact", "Ann is the user's sister."),
        ("episode", "Ride was for work."),
    }
    assert (await member.get("/api/memories")).json() == []
    first = listed[0]["id"]
    assert (await member.send("DELETE", f"/api/memories/{first}")).status_code == 404
    assert (await owner.send("DELETE", f"/api/memories/{first}")).status_code == 204
    assert len((await owner.get("/api/memories")).json()) == 1
    assert (await owner.send("DELETE", "/api/memories")).status_code == 204
    assert (await owner.get("/api/memories")).json() == []


async def test_import_a_statement(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    assert (await member.login(MEMBER, invite)).status_code == 200
    csv = (
        "Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1\n"
        "28 Sep 2026,POS,4.20,,KOPITIAM\n"
        "27 Sep 2026,POS,,50.00,ANN\n"
        "someday,POS,1.00,,MYSTERY\n"
    )
    shown = (await owner.send("POST", "/api/imports/preview", {"csv": csv})).json()
    assert shown["headers"][0] == "Transaction Date"
    assert [r["verdict"] for r in shown["rows"]] == ["new", "new", "unclear"]
    assert shown["rows"][1]["direction"] == "in" and shown["rows"][1]["category"] == "Income"
    assert (await owner.get("/api/transactions")).json()["total"] == 0  # nothing saved yet

    body = {
        "csv": csv,
        "layout": shown["layout"],
        "include": [0, 1],
        "file_name": "sept.csv",
        "save_as": "Everyday",
    }
    done = await owner.send("POST", "/api/imports", body)
    assert done.status_code == 201 and done.json()["added"] == 2
    assert (await owner.get("/api/transactions")).json()["total"] == 2
    [record] = (await owner.get("/api/imports")).json()
    assert record["file_name"] == "sept.csv"
    [layout] = (await owner.get("/api/imports/layouts")).json()
    assert layout["name"] == "Everyday"

    # Another user sees none of it and can't undo it.
    assert (await member.get("/api/imports")).json() == []
    assert (await member.send("POST", f"/api/imports/{record['id']}/undo")).status_code == 404
    assert (await member.send("DELETE", f"/api/imports/layouts/{layout['id']}")).status_code == 404
    # A request without the CSRF token is refused.
    bare = await owner.client.post("/api/imports/preview", json={"csv": csv})
    assert bare.status_code == 403

    undone = (await owner.send("POST", f"/api/imports/{record['id']}/undo")).json()
    assert undone == {"removed": 2}
    assert (await owner.get("/api/transactions")).json()["total"] == 0
    assert (await owner.send("DELETE", f"/api/imports/layouts/{layout['id']}")).status_code == 204
    bad = await owner.send("POST", "/api/imports/preview", {"csv": "Date,Amount\n"})
    assert bad.status_code == 422


async def test_import_a_pdf_statement(world: World) -> None:
    import base64

    from tests.pdfs import make_pdf
    from tests.unit.test_statement_pdf import CARD

    owner = world.browser()
    await owner.login(OWNER)
    locked = base64.b64encode(make_pdf(CARD, password="S1234567A")).decode()
    asked = (await owner.send("POST", "/api/imports/pdf", {"pdf": locked})).json()
    assert asked["needs_password"] and not asked["wrong_password"]
    wrong = (await owner.send("POST", "/api/imports/pdf", {"pdf": locked, "password": "x"})).json()
    assert wrong["wrong_password"]
    read = (
        await owner.send("POST", "/api/imports/pdf", {"pdf": locked, "password": "S1234567A"})
    ).json()
    assert read["rows"] == 5 and read["reconciles"] is True and read["kind"] == "card"
    shown = (
        await owner.send(
            "POST", "/api/imports/preview", {"csv": read["csv"], "layout": read["layout"]}
        )
    ).json()
    assert [r["verdict"] for r in shown["rows"]] == ["new"] * 5
    done = await owner.send(
        "POST",
        "/api/imports",
        {"csv": read["csv"], "layout": read["layout"], "include": [0, 1], "file_name": "e.pdf"},
    )
    assert done.json()["added"] == 2
    bad = await owner.send("POST", "/api/imports/pdf", {"pdf": "%%%not base64"})
    assert bad.status_code == 422
    plain = base64.b64encode(make_pdf(["Dear customer, nothing to see."])).decode()
    assert (await owner.send("POST", "/api/imports/pdf", {"pdf": plain})).status_code == 422


async def test_security_headers_size_cap_and_import_limit(world: World) -> None:
    from nexus.application.limits import RateLimiter

    owner = world.browser()
    await owner.login(OWNER)
    me = await owner.get("/api/me")
    assert me.headers["cache-control"] == "no-store"
    assert me.headers["x-content-type-options"] == "nosniff"
    assert me.headers["x-frame-options"] == "DENY"
    assert me.headers["strict-transport-security"].startswith("max-age=")
    huge = await owner.client.post(
        "/api/chat",
        content=b"{}",
        headers={"Content-Length": str(17 * 1024 * 1024), "Origin": ORIGIN},
    )
    assert huge.status_code == 413
    # Statement imports: a few at once is fine, a flood isn't.
    web = world.app.state.web
    object.__setattr__(web, "limits", RateLimiter({"import": ((2, timedelta(minutes=10)),)}))
    csv = "Date,Description,Amount\n28/09/2026,Kopi,-1.80\n"
    codes = [
        (await owner.send("POST", "/api/imports/preview", {"csv": csv})).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


async def test_api_docs_are_not_served_in_production(engine: AsyncEngine) -> None:
    from nexus.settings import Environment

    app = create_app(
        Settings(_env_file=None, database_url="postgresql://u:p@h/db", environment=Environment.PROD)
    )
    client = AsyncClient(transport=ASGITransport(app=app), base_url=ORIGIN)
    for path in ("/docs", "/redoc", "/openapi.json"):
        page = await client.get(path)  # the web app's own page may answer; the docs don't
        assert "swagger" not in page.text.lower() and '"openapi"' not in page.text


async def test_possible_duplicates_merge_or_stay_two(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)

    made = await owner.send(
        "POST",
        "/api/transactions",
        {
            "direction": "out",
            "amount": "23.40",
            "counterparty": "Grab Singapore",
            "date": "2026-09-27",
        },
    )
    receipt = str(made.json()["id"])
    # The bank's card alert, logged from email.
    async with world.engine.connect() as db:
        user_id = await db.scalar(select(users.c.id).where(users.c.telegram_user_id == OWNER))
    assert user_id is not None
    logged = await log_transaction(
        SqlUnitOfWork(world.engine),
        UserId(user_id),
        NewTransaction(
            direction=Direction.OUT,
            amount=Money(Decimal("23.40"), "SGD"),
            occurred_at=datetime(2026, 9, 27, 2, tzinfo=UTC),
            counterparty="Grab* A-7KXPLMQZRTWB",
            source=Source.EMAIL,
            external_id="gmail:ann@gmail.com:a1",
            notes="Card alert",
        ),
    )
    alert = str(logged.id)
    rows = {t["id"]: t for t in (await owner.get("/api/transactions")).json()["items"]}
    assert rows[alert]["duplicate"]["transaction_id"] == receipt
    assert rows[receipt]["duplicate"]["counterparty"] == "Grab* A-7KXPLMQZRTWB"

    merged = await owner.send("POST", f"/api/transactions/{receipt}/merge", {"other_id": alert})
    assert merged.status_code == 200
    assert merged.json()["kept"]["id"] == receipt  # logged first
    assert merged.json()["kept"]["counterparty"] == "Grab Singapore"
    assert merged.json()["removed"]["deleted"]
    [left] = (await owner.get("/api/transactions")).json()["items"]
    assert left["duplicate"] is None

    await owner.send("POST", f"/api/transactions/{alert}/restore")
    gone = await owner.send(
        "POST", f"/api/transactions/{alert}/not-duplicate", {"other_id": receipt}
    )
    assert gone.status_code == 204
    items = (await owner.get("/api/transactions")).json()["items"]
    assert [t["duplicate"] for t in items] == [None, None]


async def test_departments_and_runs(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    departments = (await owner.get("/api/departments")).json()
    assert [d["name"] for d in departments] == ["accounting", "investment"]
    assert departments[0]["label"] == "Accounting"
    assert (await owner.get("/api/runs")).json() == []
    missing = "/api/runs/00000000-0000-0000-0000-000000000000"
    assert (await owner.get(missing)).status_code == 404
    assert (await owner.send("POST", f"{missing}/cancel")).status_code == 404


async def test_home_lists_what_needs_the_user(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    assert (await owner.get("/api/home")).json() == []
    food = next(c for c in (await owner.get("/api/categories")).json() if c["name"] == "Dining Out")
    await owner.send("PUT", "/api/budgets", {"category_id": food["id"], "amount": "100"})
    await spend(owner, "85", "SGD", "2026-09-27", category_id=food["id"])
    await owner.send("POST", "/api/bills", {"name": "Rent", "due": "2026-09-29", "amount": "1,800"})
    await owner.send("POST", "/api/bills", {"name": "Visa", "due": "2026-10-20"})  # weeks away
    feed = (await owner.get("/api/home")).json()
    assert [(i["kind"], i["text"], i["link"], i["urgent"]) for i in feed] == [
        (
            "budget",
            "Dining Out budget is at 85% (85.00 SGD of 100.00 SGD)",
            "/accounting/plan",
            False,
        ),
        ("bill", "Rent (1800.00 SGD) due tomorrow", "/accounting/plan", False),
    ]


async def test_holdings_from_a_screenshot_on_the_web(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    empty = (await owner.get("/api/investments")).json()
    assert empty["holdings"] == [] and empty["draft"] is None and empty["screenshots"]
    assert empty["totals"]["value"] is None and empty["prices"] is True
    image = base64.b64encode(b"a screenshot").decode()
    draft = await owner.send(
        "POST", "/api/investments/screenshot", {"image": image, "mime_type": "image/png"}
    )
    assert draft.status_code == 200
    body = draft.json()
    assert body["first"] and [p["symbol"] for p in body["positions"]] == ["AAPL", "NVDA"]
    assert (await owner.get("/api/investments")).json()["draft"]["id"] == body["id"]
    saved = await owner.send("POST", f"/api/investments/drafts/{body['id']}/save")
    assert [p["quantity"] for p in saved.json()] == ["5", "10"]

    edit = {"quantity": "12", "average_cost": "120.50", "currency": "USD"}
    assert (await owner.send("PUT", "/api/investments/holdings/nvda", edit)).status_code == 204
    assert (await owner.send("DELETE", "/api/investments/holdings/AAPL")).status_code == 204
    after = (await owner.get("/api/investments")).json()
    assert [(h["symbol"], h["quantity"], h["cost"]["amount"]) for h in after["holdings"]] == [
        ("NVDA", "12", "1446.0000")
    ]
    assert after["draft"] is None
    assert after["holdings"][0]["price"] is None and after["totals"]["missing"] == ["NVDA"]

    prices = FakePrices({"NVDA": {date(2026, 9, 24): "128", date(2026, 9, 25): "130.25"}})
    await market_cases.refresh(world.app.state.web.uow, prices, now=NOW)
    valued = (await owner.get("/api/investments")).json()
    nvda = valued["holdings"][0]
    assert (nvda["price"]["amount"], nvda["value"]["amount"], nvda["gain"]["amount"]) == (
        "130.2500",
        "1563.0000",
        "117.0000",
    )
    assert nvda["price_day"] == "2026-09-25" and nvda["day_percent"] == "1.76"
    assert valued["totals"]["value"] == {"amount": "2017.0500", "currency": "SGD"}
    assert valued["totals"]["missing"] == [] and valued["totals"]["as_of"] == "2026-09-25"
    bad = await owner.send("PUT", "/api/investments/holdings/NOT A TICKER", edit)
    assert bad.status_code == 422
    gone = await owner.send("DELETE", "/api/investments/holdings/AMD")
    assert gone.status_code == 404


async def test_watchlist_and_a_stock_page_on_the_web(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    empty = (await owner.get("/api/investments/watchlist")).json()
    assert empty == {"stocks": [], "prices": True, "news": True}
    added = await owner.send("POST", "/api/investments/watchlist", {"symbol": "amd"})
    assert added.json() == {"added": True}
    again = await owner.send("POST", "/api/investments/watchlist", {"symbol": "AMD"})
    assert again.json() == {"added": False}
    bad = await owner.send("POST", "/api/investments/watchlist", {"symbol": "NOT A TICKER"})
    assert bad.status_code == 422

    last = date(2026, 9, 25)
    closes = {last - timedelta(days=59 - i): f"{100 + i * 0.5:.2f}" for i in range(60)}
    web = world.app.state.web
    await market_cases.refresh(web.uow, FakePrices({"AMD": closes}), now=NOW)
    news = FakeNews(
        headlines={"AMD": [(NOW - timedelta(hours=5), "Acme rival opens a plant")]},
        earnings_days={"AMD": [date(2026, 10, 29)]},
    )
    await research_cases.refresh_news(web.uow, news, now=NOW)
    listed = (await owner.get("/api/investments/watchlist")).json()["stocks"]
    assert listed == [
        {
            "symbol": "AMD",
            "price": "129.50",
            "price_day": "2026-09-25",
            "day_percent": "0.39",
            "earnings": {"day": "2026-10-29", "timing": "after close"},
        }
    ]
    page = (await owner.get("/api/investments/stocks/amd")).json()
    assert page["symbol"] == "AMD" and page["watching"] and page["held"] is None
    assert page["levels"]["close"] == "129.50" and page["levels"]["averages"]["50"] == "117.25"
    assert [n["headline"] for n in page["news"]] == ["Acme rival opens a plant"]
    assert page["news"][0]["url"].startswith("https://")
    unknown = (await owner.get("/api/investments/stocks/ZZZ")).json()
    assert unknown["levels"] is None and unknown["news"] == []
    assert (await owner.send("DELETE", "/api/investments/watchlist/AMD")).status_code == 204
    assert (await owner.send("DELETE", "/api/investments/watchlist/AMD")).status_code == 404


async def test_research_plans_on_the_web(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    early = await owner.send("POST", "/api/investments/stocks/AMD/plan")
    assert early.status_code == 422 and "a month of prices" in early.json()["detail"]

    await owner.send("POST", "/api/investments/watchlist", {"symbol": "AMD"})
    last = date(2026, 9, 25)
    closes = {last - timedelta(days=79 - i): f"{100 + i * 0.5:.2f}" for i in range(80)}
    web = world.app.state.web
    await market_cases.refresh(web.uow, FakePrices({"AMD": closes}), now=NOW)
    page = (await owner.get("/api/investments/stocks/AMD")).json()
    assert page["plans_enabled"] and page["plan"] is None

    started = await owner.send("POST", "/api/investments/stocks/amd/plan")
    assert started.status_code == 200 and started.json()["title"] == "Plan for AMD"
    world.model.script.extend(
        [
            call("TechnicalView", summary="A steady climb."),
            call("Debate", bull=["Trend intact."], bear=["Stretched."]),
            call(
                "LeadView", summary="Wait for a pullback.", invalidation="A close below the stop."
            ),
        ]
    )  # no headlines, so the news analyst isn't asked
    run_id = UUID(started.json()["run_id"])
    async with web.uow() as tx:
        user = await tx.ledger.get_user_by_telegram_id(OWNER)
    assert user is not None
    for _ in range(5):
        await department_cases.advance(
            web.uow, web.departments, Shown(), user, run_id, now=world.clock.now
        )
    listed = (await owner.get("/api/investments/plans")).json()
    assert len(listed) == 1 and listed[0]["headline"] == "AMD: Wait for a dip to buy"
    detail = (await owner.get(f"/api/investments/plans/{listed[0]['id']}")).json()
    assert (
        detail["plan"]["verdict"] == "wait" and detail["plan"]["summary"] == "Wait for a pullback."
    )
    assert len(detail["closes"]) == 80 and detail["closes"][-1] == {
        "day": "2026-09-25",
        "close": "139.50",
    }
    assert (await owner.get("/api/investments/stocks/AMD")).json()["plan"]["id"] == listed[0]["id"]
    assert (await owner.get("/api/investments/plans/not-a-plan")).status_code == 404
    plan_id = listed[0]["id"]
    assert listed[0]["status"] == "open" and listed[0]["alerts"] and listed[0]["followed"]
    off = await owner.send("POST", f"/api/investments/plans/{plan_id}/alerts", {"on": False})
    assert off.status_code == 204
    assert not (await owner.get("/api/investments/plans")).json()[0]["alerts"]
    record = (await owner.get("/api/investments/plans/record")).json()
    assert record["finished"] == 0 and record["open"] == 1
    assert record["text"].startswith("No plans have finished yet (1 still open)")
