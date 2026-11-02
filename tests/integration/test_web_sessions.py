"""Sliding web sessions and the bot's one-tap sign-in link, through the real app.

Every name and figure here is made up."""

import asyncio
import hashlib
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import access
from nexus.application.access import LOGIN_LINK_TTL, SESSION_TTL
from nexus.application.limits import WEB_LINKS
from nexus.application.users import RegisterUser
from nexus.channels.telegram.webhook import WEB_LINK_TOO_OFTEN, handle_update
from nexus.infra.db.uow import SqlUnitOfWork
from tests.fakes import NOW
from tests.integration.test_web_api import (
    MEMBER,
    ORIGIN,
    OWNER,
    Browser,
    World,
    init_data,
    owner_and_invite,
    world,
)

pytestmark = pytest.mark.integration
fixtures = (world,)

COOKIE = "nexus_session"


async def expiry(engine: AsyncEngine, token: str) -> datetime:
    digest = hashlib.sha256(token.encode()).hexdigest()
    async with engine.connect() as db:
        found = await db.scalar(
            text("SELECT expires_at FROM web_sessions WHERE token_hash = :h"), {"h": digest}
        )
    assert isinstance(found, datetime)
    return found


async def signed_in(world: World, telegram_id: int = OWNER) -> tuple[Browser, str]:
    browser = world.browser()
    assert (await browser.login(telegram_id)).status_code == 200
    token = browser.client.cookies[COOKIE]
    return browser, token


def max_age(set_cookie: str) -> int:
    return int(set_cookie.lower().split("max-age=")[1].split(";")[0])


# --- sliding sessions ---------------------------------------------------------------------


async def test_a_new_session_lasts_90_days(world: World) -> None:
    browser = world.browser()
    response = await browser.login(OWNER)
    assert max_age(response.headers["set-cookie"]) == SESSION_TTL.total_seconds()
    assert SESSION_TTL == timedelta(days=90)
    token = browser.client.cookies[COOKIE]
    assert await expiry(world.engine, token) == NOW + SESSION_TTL


async def test_a_session_used_after_two_days_slides_and_sends_the_cookie_again(
    world: World,
) -> None:
    browser, token = await signed_in(world)
    world.clock.now = NOW + timedelta(days=2)
    response = await browser.get("/api/me")
    assert response.status_code == 200
    assert max_age(response.headers["set-cookie"]) == SESSION_TTL.total_seconds()
    lowered = response.headers["set-cookie"].lower()
    assert "httponly" in lowered and "secure" in lowered and "samesite=lax" in lowered
    assert await expiry(world.engine, token) == NOW + timedelta(days=2) + SESSION_TTL


async def test_a_session_used_within_its_first_day_is_left_alone(world: World) -> None:
    browser, token = await signed_in(world)
    world.clock.now = NOW + timedelta(hours=23)
    response = await browser.get("/api/me")
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert await expiry(world.engine, token) == NOW + SESSION_TTL


async def test_a_session_used_twice_in_an_hour_is_written_once(world: World) -> None:
    browser, token = await signed_in(world)
    world.clock.now = NOW + timedelta(days=2)
    assert "set-cookie" in (await browser.get("/api/me")).headers
    renewed = await expiry(world.engine, token)

    world.clock.now = NOW + timedelta(days=2, hours=1)
    again = await browser.get("/api/me")
    assert again.status_code == 200
    assert "set-cookie" not in again.headers
    assert await expiry(world.engine, token) == renewed


async def test_requests_at_once_renew_once(world: World) -> None:
    browser, token = await signed_in(world)
    world.clock.now = NOW + timedelta(days=3)
    answers = await asyncio.gather(*(browser.get("/api/me") for _ in range(5)))
    assert all(a.status_code == 200 for a in answers)
    assert sum("set-cookie" in a.headers for a in answers) == 1
    assert await expiry(world.engine, token) == NOW + timedelta(days=3) + SESSION_TTL


async def test_daily_use_never_ends_and_disuse_does(world: World) -> None:
    browser, _ = await signed_in(world)
    for day in range(1, 121):
        world.clock.now = NOW + timedelta(days=day)
        assert (await browser.get("/api/me")).status_code == 200
    world.clock.now += SESSION_TTL + timedelta(hours=1)
    assert (await browser.get("/api/me")).status_code == 401

    other, _ = await signed_in(world, OWNER)
    world.clock.now += SESSION_TTL + timedelta(days=1)
    assert (await other.get("/api/me")).status_code == 401


async def test_a_revoked_session_stays_revoked(world: World) -> None:
    browser, token = await signed_in(world)
    assert (await browser.send("POST", "/api/auth/logout")).status_code == 204
    before = await expiry(world.engine, token)

    world.clock.now = NOW + timedelta(days=2)
    browser.client.cookies.set(COOKIE, token)  # the cookie someone kept
    assert (await browser.get("/api/me")).status_code == 401
    assert await expiry(world.engine, token) == before


async def test_a_short_session_that_is_not_renewable_is_never_extended(world: World) -> None:
    uow = SqlUnitOfWork(world.engine)
    day = timedelta(hours=24)
    demo = await access.log_in(
        uow,
        OWNER,
        invite_token=None,
        defaults=RegisterUser(
            telegram_user_id=OWNER, telegram_chat_id=OWNER, home_currency="SGD", timezone="UTC"
        ),
        owner_telegram_id=OWNER,
        now=NOW,
        ttl=day,
        renewable=False,
    )
    assert demo.session.expires_at == NOW + day
    browser = world.browser()
    browser.client.cookies.set(COOKIE, demo.token)

    for hours in (2, 12, 23):
        world.clock.now = NOW + timedelta(hours=hours)
        answer = await browser.get("/api/me")
        assert answer.status_code == 200
        assert "set-cookie" not in answer.headers
    assert await expiry(world.engine, demo.token) == NOW + day
    world.clock.now = NOW + day
    assert (await browser.get("/api/me")).status_code == 401


async def test_a_short_session_that_is_renewable_slides_by_its_own_length(
    world: World,
) -> None:
    uow = SqlUnitOfWork(world.engine)
    short = timedelta(days=3)
    made = await access.log_in(
        uow,
        OWNER,
        invite_token=None,
        defaults=RegisterUser(
            telegram_user_id=OWNER, telegram_chat_id=OWNER, home_currency="SGD", timezone="UTC"
        ),
        owner_telegram_id=OWNER,
        now=NOW,
        ttl=short,
    )
    browser = world.browser()
    browser.client.cookies.set(COOKIE, made.token)
    world.clock.now = NOW + timedelta(days=2)
    answer = await browser.get("/api/me")
    assert answer.status_code == 200
    assert max_age(answer.headers["set-cookie"]) == short.total_seconds()
    assert await expiry(world.engine, made.token) == NOW + timedelta(days=2) + short


async def test_a_mini_app_session_does_not_slide(world: World) -> None:
    browser = world.browser()
    response = await browser.client.post(
        "/api/auth/webapp", json={"init_data": init_data(OWNER)}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    token = response.headers["set-cookie"].split("=", 1)[1].split(";")[0]
    world.clock.now = NOW + timedelta(days=5)
    answer = await browser.get("/api/me")
    assert answer.status_code == 200
    assert "set-cookie" not in answer.headers
    assert await expiry(world.engine, token) == NOW + SESSION_TTL


async def test_a_person_who_lost_web_access_does_not_renew(world: World) -> None:
    browser, token = await signed_in(world)
    async with world.engine.begin() as db:
        await db.execute(text("UPDATE users SET role = 'member', web_access_granted_at = NULL"))
    world.clock.now = NOW + timedelta(days=2)
    assert (await browser.get("/api/me")).status_code == 401
    assert await expiry(world.engine, token) == NOW + SESSION_TTL


# --- the bot's sign-in link ---------------------------------------------------------------


def update(telegram_id: int, number: int, command: str = "/web") -> dict[str, Any]:
    return {
        "update_id": number,
        "message": {
            "message_id": number,
            "from": {"id": telegram_id},
            "chat": {"id": telegram_id, "type": "private"},
            "text": command,
        },
    }


async def ask_for_link(world: World, telegram_id: int = OWNER, number: int = 1) -> str:
    await handle_update(world.app.state.telegram, update(telegram_id, number))
    return world.telegram.sent[-1].text


def link_path(reply: str) -> str:
    assert f"{ORIGIN}/login/link/" in reply
    return "/login/link/" + reply.rsplit("/login/link/", 1)[1].strip()


async def test_web_command_replies_with_a_link_that_signs_in_once(world: World) -> None:
    reply = await ask_for_link(world)
    assert "5 minutes" in reply
    # Sent without a link preview, so Telegram never fetches (and spends) it.
    assert world.telegram.no_preview == [len(world.telegram.sent) - 1]
    path = link_path(reply)

    browser = world.browser()
    first = await browser.get(path)
    assert first.status_code == 303 and first.headers["location"] == "/"
    cookie = first.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert max_age(cookie) == SESSION_TTL.total_seconds()
    assert "no-store" in first.headers["cache-control"]
    me = await browser.get("/api/me")
    assert me.status_code == 200 and me.json()["user"]["telegram_user_id"] == OWNER

    # The same session slides like any other.
    world.clock.now = NOW + timedelta(days=2)
    assert "set-cookie" in (await browser.get("/api/me")).headers

    second = await world.browser().get(path)
    assert second.status_code == 303 and second.headers["location"] == "/login?error=link"
    assert "set-cookie" not in second.headers


async def test_the_link_is_spent_by_exactly_one_of_several_requests(world: World) -> None:
    path = link_path(await ask_for_link(world))
    answers = await asyncio.gather(*(world.browser().get(path) for _ in range(5)))
    assert sorted(a.headers["location"] for a in answers) == ["/"] + ["/login?error=link"] * 4


async def test_the_link_expires_after_five_minutes(world: World) -> None:
    assert LOGIN_LINK_TTL == timedelta(minutes=5)
    path = link_path(await ask_for_link(world))
    world.clock.now = NOW + LOGIN_LINK_TTL
    late = await world.browser().get(path)
    assert late.headers["location"] == "/login?error=link"
    assert "set-cookie" not in late.headers

    world.clock.now = NOW
    path = link_path(await ask_for_link(world, number=2))
    world.clock.now = NOW + LOGIN_LINK_TTL - timedelta(seconds=1)
    assert (await world.browser().get(path)).headers["location"] == "/"


async def test_unknown_links_go_to_the_sign_in_page(world: World) -> None:
    answer = await world.browser().get("/login/link/not-a-real-token")
    assert answer.status_code == 303 and answer.headers["location"] == "/login?error=link"
    assert "set-cookie" not in answer.headers


async def test_people_without_web_access_get_no_link(world: World, engine: AsyncEngine) -> None:
    reply = await ask_for_link(world, MEMBER)  # allow-listed, never invited
    assert reply == "You need an invite to use the web app. Ask the owner for a link."
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM login_links")) == 0


async def test_a_member_with_web_access_gets_a_link(world: World) -> None:
    _, invite = await owner_and_invite(world)
    assert (await world.browser().login(MEMBER, invite=invite)).status_code == 200
    path = link_path(await ask_for_link(world, MEMBER, number=2))
    browser = world.browser()
    assert (await browser.get(path)).headers["location"] == "/"
    assert (await browser.get("/api/me")).json()["user"]["telegram_user_id"] == MEMBER


async def test_losing_web_access_voids_a_link_already_sent(world: World) -> None:
    _, invite = await owner_and_invite(world)
    await world.browser().login(MEMBER, invite=invite)
    path = link_path(await ask_for_link(world, MEMBER, number=2))
    async with world.engine.begin() as db:
        await db.execute(
            text("UPDATE users SET web_access_granted_at = NULL WHERE role = 'member'")
        )
    answer = await world.browser().get(path)
    assert answer.headers["location"] == "/login?error=link"


async def test_only_a_hash_of_the_token_is_stored(world: World, engine: AsyncEngine) -> None:
    token = link_path(await ask_for_link(world)).rsplit("/", 1)[1]
    assert len(token) >= 43  # token_urlsafe(32)
    async with engine.connect() as db:
        rows = (await db.execute(text("SELECT token_hash, used_at FROM login_links"))).all()
        everything = (
            await db.execute(text("SELECT row_to_json(l)::text FROM login_links l"))
        ).all()
    assert [r.token_hash for r in rows] == [hashlib.sha256(token.encode()).hexdigest()]
    assert token not in str(everything)
    await world.browser().get("/login/link/" + token)
    async with engine.connect() as db:
        assert await db.scalar(text("SELECT used_at FROM login_links")) == NOW
        assert token not in str(
            (await db.execute(text("SELECT row_to_json(s)::text FROM web_sessions s"))).all()
        )


async def test_a_link_preview_does_not_spend_the_link(world: World) -> None:
    path = link_path(await ask_for_link(world))
    crawler = await world.browser().get(
        path, headers={"User-Agent": "TelegramBot (like TwitterBot)"}
    )
    assert crawler.status_code == 204 and "set-cookie" not in crawler.headers
    assert (await world.browser().get(path)).headers["location"] == "/"


async def test_the_web_command_is_limited_per_user(world: World) -> None:
    allowed, _ = WEB_LINKS[0]
    for number in range(1, allowed + 1):
        assert "/login/link/" in await ask_for_link(world, number=number)
    assert await ask_for_link(world, number=allowed + 1) == WEB_LINK_TOO_OFTEN
    async with world.engine.connect() as db:
        assert await db.scalar(text("SELECT count(*) FROM login_links")) == allowed
