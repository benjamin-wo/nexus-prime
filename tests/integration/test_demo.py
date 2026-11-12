"""The public live demo through the real app: a visitor's own seeded account, its cookie, the
allowances and the shared daily spend cap, what is switched off, the limit per address,
clean-up, isolation from everyone else's data, and the owner's cost line."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import thread_id
from nexus.application import access, demo, erasure
from nexus.application import demo_seed as seed_module
from nexus.application import departments as department_cases
from nexus.application import email as email_cases
from nexus.application.clock import utcnow
from nexus.application.demo import MESSAGES
from nexus.application.users import RegisterUser, register_user
from nexus.domain.errors import Forbidden
from nexus.domain.ledger import Role, User, UserId
from nexus.infra.db import user_data
from nexus.infra.db.tables import (
    demo_costs,
    demo_starts,
    metadata,
    model_costs,
    transactions,
    users,
    web_sessions,
)
from nexus.infra.demo_store import DemoStore
from nexus.jobs import handlers as job_handlers
from nexus.main import Overrides, create_app
from nexus.settings import Settings
from tests.fakes import (
    NOW,
    FakeBucket,
    FakeEmailReader,
    FakeForwarding,
    FakeHoldings,
    FakeMailbox,
    FakeRates,
    FakeSpeech,
    FakeTelegram,
    ScriptedModel,
    models,
    say,
    scripted,
)
from tests.integration.conftest import UowFactory
from tests.integration.test_web_api import ORIGIN, OWNER, TOKEN, Browser, Clock

pytestmark = pytest.mark.integration

AUDIO = b"OggS-made-up-voice-note"
IMAGE = "aGVsbG8="  # any base64: the reader is a fake
SEEN: list[UserId] = []  # the accounts the stub seed was asked to fill


def when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


@dataclass
class Demo:
    app: Any
    clock: Clock
    model: ScriptedModel
    speech: FakeSpeech
    holdings: FakeHoldings
    telegram: FakeTelegram
    engine: AsyncEngine
    uow: UowFactory

    def browser(self, forwarded_for: str | None = None) -> Browser:
        browser = Browser(self.app, self.clock)
        if forwarded_for is not None:
            browser.client.headers["X-Forwarded-For"] = forwarded_for
        return browser

    async def visit(self, forwarded_for: str | None = None) -> Browser:
        """A visitor who opens /demo: their own browser, with a demo session."""
        browser = self.browser(forwarded_for)
        response = await browser.client.post("/api/demo", headers={"Origin": ORIGIN})
        assert response.status_code == 200, response.text
        browser.csrf = (await browser.get("/api/me")).json()["csrf_token"]
        return browser

    async def owner(self) -> Browser:
        browser = self.browser()
        assert (await browser.login(OWNER)).status_code == 200
        return browser

    async def user_of(self, browser: Browser) -> User:
        me = (await browser.get("/api/me")).json()
        async with self.uow() as tx:
            found = await tx.ledger.get_user_by_telegram_id(me["user"]["telegram_user_id"])
        assert found is not None
        return found

    async def set_used(self, user: User, **counts: int) -> None:
        async with self.engine.begin() as db:
            await db.execute(update(users).where(users.c.id == user.id).values(**counts))

    async def spend(self, user_id: UserId | None, dollars: str, day: date | None = None) -> None:
        async with self.engine.begin() as db:
            await db.execute(
                insert(model_costs).values(
                    day=day or utcnow().date(),
                    user_id=user_id,
                    feature=f"chat-{uuid4().hex[:6]}",
                    model="fake/model",
                    calls=3,
                    input_tokens=100,
                    output_tokens=10,
                    cost_usd=Decimal(dollars),
                )
            )


def make_app(url: str, clock: Clock, model: ScriptedModel, **extra: Any) -> tuple[Any, Any]:
    settings = {
        "_env_file": None,
        "database_url": url,
        "telegram_bot_token": TOKEN,
        "telegram_webhook_secret": "hook",
        "admin_telegram_chat_id": OWNER,
        "web_origin": ORIGIN,
        "default_timezone": "UTC",
        "demo_enabled": True,
        "google_client_id": "cid",
        "google_client_secret": "secret",
        "token_encryption_key": "uCnPp8WQmmsnFMBkVvmsQVoZpn7YPOkm4Hnl5mTZiH8=",
        "agentmail_api_key": "am_test",
        **extra,
    }
    speech, holdings = FakeSpeech(), FakeHoldings()
    app = create_app(
        Settings(**settings),
        Overrides(
            models=models(model),
            telegram=FakeTelegram(),
            checkpointer=InMemorySaver(),
            clock=lambda: clock.now,
            rates=FakeRates({}),
            receipt_store=FakeBucket(),
            mailbox=FakeMailbox(),
            forwarding=FakeForwarding(),
            email_reader=FakeEmailReader(),
            speech=speech,
            holdings=holdings,
        ),
    )
    return app, (speech, holdings)


@pytest.fixture(autouse=True)
def stub_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real seed is another module's; here it only notes who it was asked to fill."""
    SEEN.clear()

    async def seed(uow: Any, user: User, *, now: datetime) -> None:
        SEEN.append(user.id)

    monkeypatch.setattr(seed_module, "seed_demo", seed)
    monkeypatch.setattr("nexus.infra.demo_store.SPEND_CACHE_SECONDS", 0.0)


@pytest.fixture
async def world(engine: AsyncEngine, empty_database_url: str) -> AsyncIterator[Demo]:
    clock, model = Clock(), scripted()
    app, (speech, holdings) = make_app(empty_database_url, clock, model)
    async with app.router.lifespan_context(app):
        yield Demo(
            app,
            clock,
            model,
            speech,
            holdings,
            app.state.telegram.client,
            engine,
            app.state.telegram.uow,
        )


# --- starting a demo ---------------------------------------------------------------------


async def test_a_visitor_gets_a_private_signed_in_account(world: Demo) -> None:
    visitor = world.browser()
    response = await visitor.client.post("/api/demo", headers={"Origin": ORIGIN})
    assert response.status_code == 200
    assert list(response.json()) == ["expires_at"]
    assert when(response.json()["expires_at"]) == NOW + timedelta(hours=24)

    me = (await visitor.get("/api/me")).json()
    assert me["user"]["role"] == "member"
    assert me["user"]["telegram_user_id"] < 0  # real Telegram ids are positive
    assert me["user"]["home_currency"] == "SGD"
    assert me["user"]["timezone"] == "Asia/Singapore"
    assert me["user"]["display_name"] == "Demo"
    assert when(me["demo"]["expires_at"]) == NOW + timedelta(hours=24)
    assert me["demo"]["messages_left"] == 50
    # A demo shows off which card paid, and Invest and Travel in the menu.
    assert me["preferences"] == {"track_cards": True, "show_invest": True, "show_travel": True}
    assert me["user"]["telegram_linked"] is False  # a demo has no chat

    user = await world.user_of(visitor)
    assert user.is_demo and user.telegram_chat_id is None and user.has_web_access
    assert SEEN == [user.id]  # seeded once, before the session was opened
    # The seeded account works at once: no Telegram, no invite.
    visitor.csrf = me["csrf_token"]
    assert (
        await visitor.send("POST", "/api/transactions", {"direction": "out", "amount": "3"})
    ).status_code == 201


async def test_a_real_user_has_no_demo_block(world: Demo) -> None:
    owner = await world.owner()
    assert (await owner.get("/api/me")).json()["demo"] is None


async def test_a_demo_can_switch_card_tracking_off_and_a_real_user_starts_with_it_off(
    world: Demo,
) -> None:
    owner = await world.owner()
    assert (await owner.get("/api/me")).json()["preferences"] == {
        "track_cards": False,
        "show_invest": None,
        "show_travel": None,
    }
    visitor = await world.visit()
    off = await visitor.send("PUT", "/api/settings/preferences", {"track_cards": False})
    assert off.status_code == 200 and off.json()["track_cards"] is False
    # Turning one setting off leaves the demo's menu as it was.
    preferences = (await visitor.get("/api/me")).json()["preferences"]
    assert preferences == {"track_cards": False, "show_invest": True, "show_travel": True}


async def test_the_cookie_lasts_the_demos_24_hours_not_90_days(world: Demo) -> None:
    visitor = world.browser()
    response = await visitor.client.post("/api/demo", headers={"Origin": ORIGIN})
    cookie = response.headers["set-cookie"].lower()
    assert "max-age=86400" in cookie
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    login = await world.browser().login(OWNER)  # a normal sign-in keeps its 90 days
    assert f"max-age={90 * 86400}" in login.headers["set-cookie"].lower()


async def test_someone_signed_in_as_themselves_keeps_their_own_session(world: Demo) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    answer = await owner.client.post("/api/demo", headers={"Origin": ORIGIN})
    assert answer.status_code == 409 and answer.json()["detail"] == "signed_in"
    assert "set-cookie" not in answer.headers
    me = await owner.client.get("/api/me")
    assert me.status_code == 200 and me.json()["demo"] is None


async def test_a_visitor_with_a_live_demo_gets_that_one_back(world: Demo) -> None:
    visitor = await world.visit()
    first = await world.user_of(visitor)
    again = await visitor.client.post("/api/demo", headers={"Origin": ORIGIN})
    assert again.status_code == 200
    assert when(again.json()["expires_at"]) == NOW + timedelta(hours=24)
    assert await world.user_of(visitor) == first
    assert len(SEEN) == 1
    async with world.engine.connect() as db:
        made = await db.scalar(select(func.count()).where(users.c.demo_expires_at.is_not(None)))
        started = await db.scalar(select(func.sum(demo_starts.c.starts)))
    assert made == 1 and started == 1


async def test_only_our_own_origin_may_start_one(world: Demo) -> None:
    visitor = world.browser()
    # 400, not 403: the web reads a 403 from this endpoint as "demos are off".
    cross = await visitor.client.post("/api/demo", headers={"Origin": "https://evil.test"})
    assert cross.status_code == 400
    assert (await visitor.client.post("/api/demo")).status_code == 400
    assert SEEN == []


async def test_starting_a_demo_needs_no_csrf_token_but_the_session_after_it_does(
    world: Demo,
) -> None:
    visitor = world.browser()
    started = await visitor.client.post("/api/demo", headers={"Origin": ORIGIN, "X-CSRF-Token": ""})
    assert started.status_code == 200
    me = (await visitor.get("/api/me")).json()
    blind = await visitor.client.post(
        "/api/transactions",
        json={"direction": "out", "amount": "3"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": ""},
    )
    assert blind.status_code == 403
    visitor.csrf = me["csrf_token"]
    assert (
        await visitor.send("POST", "/api/transactions", {"direction": "out", "amount": "3"})
    ).status_code == 201


async def test_signing_out_ends_a_demo_session_like_any_other(world: Demo) -> None:
    visitor = await world.visit()
    assert (await visitor.send("POST", "/api/auth/logout")).status_code == 204
    assert (await visitor.get("/api/me")).status_code == 401


async def test_a_demo_that_failed_to_fill_leaves_nothing_behind(
    world: Demo, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(uow: Any, user: User, *, now: datetime) -> None:
        raise RuntimeError("the seed broke")

    monkeypatch.setattr(seed_module, "seed_demo", broken)
    visitor = world.browser()
    response = await visitor.client.post("/api/demo", headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert response.json() == {"detail": "demo_unavailable"}
    assert "set-cookie" not in response.headers
    assert (await visitor.get("/api/me")).status_code == 401
    async with world.engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(users)) == 0
        assert await db.scalar(select(func.count()).select_from(web_sessions)) == 0


async def test_demos_are_off_unless_switched_on(
    engine: AsyncEngine, empty_database_url: str
) -> None:
    clock = Clock()
    app, _ = make_app(empty_database_url, clock, scripted(), demo_enabled=False)
    async with app.router.lifespan_context(app):
        visitor = Browser(app, clock)
        response = await visitor.client.post("/api/demo", headers={"Origin": ORIGIN})
        assert response.status_code == 403
        assert response.json() == {"detail": "demo_off"}
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(users)) == 0


async def test_five_new_demos_an_hour_from_one_address(world: Demo) -> None:
    for _ in range(5):
        await world.visit("203.0.113.7")
    sixth = world.browser("203.0.113.7")
    refused = await sixth.client.post("/api/demo", headers={"Origin": ORIGIN})
    assert refused.status_code == 429
    # Another address is not held back.
    await world.visit("203.0.113.8")


async def test_an_address_made_up_by_the_visitor_does_not_help(world: Demo) -> None:
    # Our proxy appends the address it saw: what the visitor wrote further left is ignored.
    for n in range(5):
        await world.visit(f"10.0.0.{n}, 198.51.100.9")
    refused = world.browser("10.0.0.99, 198.51.100.9")
    assert (await refused.client.post("/api/demo", headers={"Origin": ORIGIN})).status_code == 429


async def test_an_expired_demo_session_is_refused(world: Demo) -> None:
    visitor = await world.visit()
    assert (await visitor.get("/api/me")).status_code == 200
    world.clock.now = NOW + timedelta(hours=24, seconds=1)
    assert (await visitor.get("/api/me")).status_code == 401


async def test_a_demo_ends_with_its_time_whatever_its_session_says(world: Demo) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    async with world.engine.begin() as db:  # a session row that would live for days
        await db.execute(update(web_sessions).values(expires_at=NOW + timedelta(days=30)))
    assert user.demo_expires_at is not None
    world.clock.now = user.demo_expires_at + timedelta(seconds=1)
    assert (await visitor.get("/api/me")).status_code == 401


async def test_a_demo_can_end_itself_by_deleting_its_data(world: Demo) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    await world.spend(user.id, "0.25")
    done = await visitor.send("POST", "/api/me/delete", {"confirm": "DELETE"})
    assert done.status_code == 204
    async with world.engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(users)) == 0
        # What it cost is not forgotten.
        assert await db.scalar(select(func.sum(demo_costs.c.cost_usd))) == Decimal("0.25")


# --- allowances and the daily cap -----------------------------------------------------------


async def test_the_fifty_first_message_says_the_demo_limit_is_reached(world: Demo) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    await world.set_used(user, demo_messages=MESSAGES - 1)
    world.model.script += [say("Hello again.")]
    [last] = (await visitor.send("POST", "/api/chat", {"message": "hi"})).json()
    assert last["text"] == "Hello again."
    assert (await visitor.get("/api/me")).json()["demo"]["messages_left"] == 0

    model_calls = len(world.model.seen)
    [refused] = (await visitor.send("POST", "/api/chat", {"message": "one more"})).json()
    assert "demo limit is reached" in refused["text"]
    assert "Telegram" in refused["text"]
    assert len(world.model.seen) == model_calls  # no model call was made
    assert (await world.user_of(visitor)).id == user.id
    async with world.engine.connect() as db:
        used = await db.scalar(select(users.c.demo_messages).where(users.c.id == user.id))
    assert used == MESSAGES  # the refused one was not counted


async def test_streamed_messages_count_against_the_demo_allowance_like_the_others(
    world: Demo,
) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    await world.set_used(user, demo_messages=MESSAGES - 1)
    world.model.script += [say("Hello again.")]
    streamed = await visitor.send("POST", "/api/chat/stream", {"message": "hi"})
    assert streamed.status_code == 200
    assert '"text":"Hello again."' in streamed.text
    assert (await visitor.get("/api/me")).json()["demo"]["messages_left"] == 0

    model_calls = len(world.model.seen)
    refused = await visitor.send("POST", "/api/chat/stream", {"message": "one more"})
    assert refused.status_code == 200
    assert "demo limit is reached" in refused.text and "event: replies" in refused.text
    assert len(world.model.seen) == model_calls  # no model call was made
    async with world.engine.connect() as db:
        used = await db.scalar(select(users.c.demo_messages).where(users.c.id == user.id))
    assert used == MESSAGES  # the refused one was not counted


async def test_five_voice_notes_then_the_demo_limit(world: Demo) -> None:
    visitor = await world.visit()
    await world.set_used(await world.user_of(visitor), demo_voice=4)
    world.speech.script += ["How much did I spend?"]
    world.model.script += [say("Nothing yet.")]
    note = {"audio": ("note", AUDIO, "audio/webm")}
    headers = {"Origin": ORIGIN, "X-CSRF-Token": visitor.csrf}
    fifth = await visitor.client.post("/api/chat/voice", files=note, headers=headers)
    assert fifth.json()[0]["text"] == "Nothing yet."
    sixth = await visitor.client.post("/api/chat/voice", files=note, headers=headers)
    assert sixth.status_code == 200
    assert "demo limit is reached" in sixth.json()[0]["text"]
    assert len(world.speech.heard) == 1  # the sixth was never transcribed


async def test_five_photos_then_the_demo_limit(world: Demo) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    await world.set_used(user, demo_photos=4)
    shot = {"image": IMAGE, "mime_type": "image/png"}
    fifth = await visitor.send("POST", "/api/investments/screenshot", shot)
    assert fifth.status_code == 200
    assert world.holdings.reads == 1
    sixth = await visitor.send("POST", "/api/investments/screenshot", shot)
    assert sixth.status_code == 429
    assert "demo limit is reached" in sixth.json()["detail"]
    assert world.holdings.reads == 1


async def test_all_demos_share_a_daily_cap_of_two_dollars(world: Demo) -> None:
    first, second = await world.visit("198.51.100.1"), await world.visit("198.51.100.2")
    other = await world.user_of(second)
    await world.spend(other.id, "1.99")
    world.model.script += [say("Still fine.")]
    [fine] = (await first.send("POST", "/api/chat", {"message": "hi"})).json()
    assert fine["text"] == "Still fine."

    await world.spend(other.id, "0.01")  # the day's demo spend reaches US$2
    calls = len(world.model.seen)
    [refused] = (await first.send("POST", "/api/chat", {"message": "hi"})).json()
    assert "demo limit is reached" in refused["text"] and "Telegram" in refused["text"]
    assert len(world.model.seen) == calls
    # Other paid calls stop too, and a real user is not held back by it.
    shot = await first.send(
        "POST", "/api/investments/screenshot", {"image": IMAGE, "mime_type": "image/png"}
    )
    assert shot.status_code == 429
    owner = await world.owner()
    world.model.script += [say("Owner is fine.")]
    [ok] = (await owner.send("POST", "/api/chat", {"message": "hi"})).json()
    assert ok["text"] == "Owner is fine."


async def test_the_cap_counts_demos_already_erased_and_only_today(world: Demo) -> None:
    visitor = await world.visit()
    gone = await world.visit("198.51.100.3")
    gone_user = await world.user_of(gone)
    await world.spend(gone_user.id, "2.50")
    await gone.send("POST", "/api/me/delete", {"confirm": "DELETE"})  # its rows go; the spend stays
    [refused] = (await visitor.send("POST", "/api/chat", {"message": "hi"})).json()
    assert "demo limit is reached" in refused["text"]

    store = DemoStore(world.engine, today=lambda: utcnow().date() + timedelta(days=1))
    assert await store.spent_today() == 0  # tomorrow starts again
    store = DemoStore(world.engine)
    assert await store.spent_today() == Decimal("2.50")


async def test_what_is_spent_by_real_users_and_the_system_is_not_the_demos(world: Demo) -> None:
    owner = await world.owner()
    me = await world.user_of(owner)
    await world.spend(me.id, "5.00")
    await world.spend(None, "5.00")
    assert await DemoStore(world.engine).spent_today() == 0
    visitor = await world.visit()
    world.model.script += [say("Fine.")]
    [ok] = (await visitor.send("POST", "/api/chat", {"message": "hi"})).json()
    assert ok["text"] == "Fine."


async def test_the_spend_is_read_after_the_cost_store_has_written(world: Demo) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    from nexus.application import costs

    costs.set_sink(world.app.state.costs.add)
    with costs.scope("chat", user=user.id):
        costs.record("fake/model", input_tokens=10, output_tokens=5, cost=Decimal("2.5"))
    # Counted in memory only so far; the gate flushes first.
    [refused] = (await visitor.send("POST", "/api/chat", {"message": "hi"})).json()
    assert "demo limit is reached" in refused["text"]


# --- what is switched off ---------------------------------------------------------------------


async def test_inviting_connecting_email_and_sharing_are_refused(world: Demo) -> None:
    visitor = await world.visit()
    for method, path, body in [
        ("POST", "/api/invites", None),
        ("POST", "/api/email/link", None),
    ]:
        refused = await visitor.send(method, path, body)
        assert refused.status_code == 403, path
        assert "isn't part of the demo" in refused.json()["detail"]

    trip = await visitor.send(
        "POST",
        "/api/travel/trips",
        {"destination": "Kyoto", "start": "2026-10-10", "end": "2026-10-14", "currency": "JPY"},
    )
    assert trip.status_code == 201
    trip_id = trip.json()["id"]
    for path in (f"/api/travel/trips/{trip_id}/share", f"/api/travel/trips/{trip_id}/invites"):
        body = {"renew": False} if path.endswith("share") else None
        refused = await visitor.send("POST", path, body)
        assert refused.status_code == 403, path
        assert "isn't part of the demo" in refused.json()["detail"]


async def test_a_demo_cannot_join_someone_elses_trip_or_start_research(world: Demo) -> None:
    owner = await world.owner()
    trip = await owner.send(
        "POST",
        "/api/travel/trips",
        {"destination": "Lisbon", "start": "2026-10-10", "end": "2026-10-14", "currency": "EUR"},
    )
    link = await owner.send("POST", f"/api/travel/trips/{trip.json()['id']}/invites")
    assert link.status_code == 201
    visitor = await world.visit()
    joined = await visitor.send("POST", f"/api/travel/invites/{link.json()['token']}/accept")
    assert joined.status_code == 403
    assert (await visitor.get("/api/travel/trips")).json() == []
    # Research runs are refused before anything is looked at.
    user = await world.user_of(visitor)
    with pytest.raises(Forbidden, match="Research isn't part of the demo"):
        await department_cases.start_run(
            world.uow(), department_cases.default_registry(), user, "plan", {}, now=NOW
        )


async def test_nothing_connects_a_demo_to_telegram_or_a_mailbox(world: Demo) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    with pytest.raises(Forbidden, match="isn't part of the demo"):
        await email_cases.create_link(world.uow(), user, now=NOW)
    assert world.app.state.web.email is not None
    forwarding = world.app.state.web.email
    with pytest.raises(Forbidden, match="isn't part of the demo"):
        await email_cases.set_up_forwarding(
            world.uow, forwarding.forwarding, forwarding.cipher, user, now=NOW
        )
    # No chat, and a negative id no Telegram account has: the bot can never reach it.
    assert user.telegram_chat_id is None and user.telegram_user_id < 0
    async with world.engine.begin() as db:
        with pytest.raises(IntegrityError):  # the database refuses a demo with a real-looking id
            await db.execute(
                update(users).where(users.c.id == user.id).values(telegram_user_id=12345)
            )


async def test_the_owners_pages_are_not_there_for_a_demo(world: Demo) -> None:
    visitor = await world.visit()
    for method, path in [
        ("GET", "/api/ops/report"),
        ("GET", "/api/ops/costs"),
        ("POST", "/api/ops/tickets"),
    ]:
        assert (await visitor.send(method, path)).status_code == 404, path
    owner = await world.owner()
    assert (await owner.get("/api/ops/costs")).status_code == 200


# --- background jobs --------------------------------------------------------------------------


async def test_sweeps_leave_demo_accounts_alone(world: Demo) -> None:
    trip = {"destination": "Kyoto", "start": "2026-09-30", "end": "2026-10-03", "currency": "JPY"}
    visitor = await world.visit()
    demo_user = await world.user_of(visitor)
    owner = await world.owner()
    real = await world.user_of(owner)
    for browser in (visitor, owner):
        assert (await browser.send("POST", "/api/travel/trips", trip)).status_code == 201
    async with world.engine.begin() as db:  # a chat to message, as if it had been linked
        await db.execute(
            update(users).where(users.c.id == demo_user.id).values(telegram_chat_id=-5)
        )
    async with world.uow() as tx:
        assert await tx.trips.travellers(NOW.date()) == [real.id]
        assert await tx.planning.users_to_notify() == [real.id]
        due = await tx.trips.trips_needing_photos(NOW.date(), NOW + timedelta(days=1), limit=10)
        assert {t.user_id for t in due} == {real.id}
        assert demo_user.id not in await tx.ledger.users_with_zone_source(demo_user.timezone_source)


async def test_the_payday_budget_bill_and_travel_jobs_never_look_at_a_demo(
    world: Demo, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip = {"destination": "Kyoto", "start": "2026-09-30", "end": "2026-10-03", "currency": "JPY"}
    visitor = await world.visit()
    demo_user = await world.user_of(visitor)
    owner = await world.owner()
    real = await world.user_of(owner)
    for browser in (visitor, owner):
        assert (await browser.send("POST", "/api/travel/trips", trip)).status_code == 201
        pay = {"rule": "monthly_day", "day": 25}
        assert (await browser.send("PUT", "/api/salary", pay)).status_code == 204
        budget = {"amount": "500"}
        assert (await browser.send("PUT", "/api/budgets", budget)).status_code == 204
        bill = {"name": "Rent", "due": "2026-10-01", "cadence": "monthly"}
        assert (await browser.send("POST", "/api/bills", bill)).status_code == 201

    called: dict[str, list[UserId]] = {}

    def spy(name: str) -> Any:
        async def seen(*args: Any, **kwargs: Any) -> int:
            user = next(a for a in (*args, *kwargs.values()) if isinstance(a, User))
            called.setdefault(name, []).append(user.id)
            return 0

        return seen

    monkeypatch.setattr("nexus.application.salary.payday_checkin", spy("payday"))
    monkeypatch.setattr("nexus.application.bills.send_reminders", spy("bills"))
    monkeypatch.setattr("nexus.application.budgets.check_budgets", spy("budgets"))
    monkeypatch.setattr("nexus.application.bookings.remind", spy("trips.remind"))
    monkeypatch.setattr("nexus.application.subscriptions.check", spy("subscriptions"))
    async with world.engine.begin() as db:  # as if it had been given a chat
        await db.execute(
            update(users).where(users.c.id == demo_user.id).values(telegram_chat_id=-5)
        )
    handlers = job_handlers.build_handlers(
        world.uow, world.telegram, FakeRates({}), lambda: world.clock.now, FakeBucket()
    )
    for kind in (
        job_handlers.PAYDAY_SWEEP,
        job_handlers.BILLS_SWEEP,
        job_handlers.BUDGETS_SWEEP,
        job_handlers.SUBSCRIPTIONS_SWEEP,
        "trips.remind",
    ):
        await handlers[kind]({})
    # Each sweep reached the real user (so the test sees them work) and never the demo.
    assert called["payday"] == called["bills"] == called["budgets"] == [real.id]
    assert called["trips.remind"] == called["subscriptions"] == [real.id]
    assert demo_user.id not in [u for users_ in called.values() for u in users_]


async def test_the_purge_job_erases_expired_demos_and_nothing_else(world: Demo) -> None:
    old = await world.visit("198.51.100.1")
    old_user = await world.user_of(old)
    await old.send("POST", "/api/transactions", {"direction": "out", "amount": "9.50"})
    world.model.script += [say("Noted.")]
    await old.send("POST", "/api/chat", {"message": "hello"})
    await world.spend(old_user.id, "0.40")
    world.clock.now = NOW + timedelta(hours=10)
    young = await world.visit("198.51.100.2")
    young_user = await world.user_of(young)
    await young.send("POST", "/api/transactions", {"direction": "out", "amount": "4"})
    owner = await world.owner()
    await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "7"})
    real = await world.user_of(owner)

    handlers = job_handlers.build_handlers(
        world.uow, world.telegram, FakeRates({}), lambda: world.clock.now, FakeBucket()
    )
    schedules = {s.kind: s.every for s in job_handlers.SCHEDULES}
    assert schedules[job_handlers.DEMO_PURGE] == timedelta(hours=1)

    await handlers[job_handlers.DEMO_PURGE]({})  # nobody has expired yet
    async with world.engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(users)) == 3

    world.clock.now = NOW + timedelta(hours=24, minutes=1)  # the first has run out
    await handlers[job_handlers.DEMO_PURGE]({})
    async with world.engine.connect() as db:
        assert (await db.execute(select(users.c.id))).scalars().all().__len__() == 2
        left = {
            name: await db.scalar(
                select(func.count())
                .select_from(metadata.tables[name])
                .where(user_data._where(name, old_user.id))
            )
            for name in user_data.ERASE_ORDER
        }
        assert not any(left.values()), {k: v for k, v in left.items() if v}
        assert (
            await db.scalar(
                select(func.count())
                .select_from(web_sessions)
                .where(web_sessions.c.user_id == old_user.id)
            )
            == 0
        )
        # Its cost is kept as a demo total.
        assert await db.scalar(select(func.sum(demo_costs.c.cost_usd))) == Decimal("0.40")
        # Nobody else lost a thing.
        mine = await db.scalar(
            select(func.count())
            .select_from(transactions)
            .where(transactions.c.user_id == young_user.id)
        )
        theirs = await db.scalar(
            select(func.count()).select_from(transactions).where(transactions.c.user_id == real.id)
        )
    assert mine == 1 and theirs == 1
    assert (await young.get("/api/me")).status_code == 200
    assert (await old.get("/api/me")).status_code == 401


async def test_the_purge_finishes_what_it_can_when_one_fails(world: Demo) -> None:
    await world.visit("198.51.100.1")
    await world.visit("198.51.100.2")
    erased: list[UserId] = []
    failed: list[UserId] = []

    async def erase(user: User) -> None:
        if not failed:
            failed.append(user.id)
            raise RuntimeError("one account failed")
        erased.append(user.id)
        await erasure.delete_user_data(
            world.uow, user, chat_thread=thread_id(user.id), store=None, email=None
        )

    later = NOW + timedelta(days=2)
    assert await demo.purge_expired(world.uow, now=later, erase=erase) == 1
    assert await demo.purge_expired(world.uow, now=later, erase=erase) == 1  # the other, now
    async with world.engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(users)) == 0


# --- isolation -----------------------------------------------------------------------------------


async def test_a_demo_cannot_see_or_reach_anyone_elses_rows(world: Demo) -> None:
    owner = await world.owner()
    made = await owner.send("POST", "/api/transactions", {"direction": "out", "amount": "123.45"})
    secret_id = made.json()["id"]
    world.model.script += [say("Hello.")]
    await owner.send("POST", "/api/chat", {"message": "hello"})

    visitor = await world.visit()
    await visitor.send("POST", "/api/transactions", {"direction": "out", "amount": "1.10"})
    listed = (await visitor.get("/api/transactions")).json()
    assert [Decimal(t["amount"]["amount"]) for t in listed["items"]] == [Decimal("1.10")]
    assert (await visitor.get(f"/api/transactions/{secret_id}")).status_code == 404
    assert (await visitor.send("DELETE", f"/api/transactions/{secret_id}")).status_code == 404
    assert (await visitor.get("/api/chat/history")).json()["lines"] == []

    # The database itself, as the demo: only its own rows, even with no filter.
    user = await world.user_of(visitor)
    async with world.engine.connect() as db:
        async with db.begin() as transaction:
            await db.execute(
                text("SELECT set_config('app.user_id', :id, true)"), {"id": str(user.id)}
            )
            seen: set[Any] = set((await db.execute(select(transactions.c.user_id))).scalars())
            people: set[Any] = set((await db.execute(select(users.c.id))).scalars())
            await transaction.rollback()
    assert seen == {user.id}
    assert people == {user.id}


async def test_a_demo_is_an_ordinary_member_never_the_owner(world: Demo) -> None:
    visitor = await world.visit()
    user = await world.user_of(visitor)
    assert user.role is Role.MEMBER
    assert (await visitor.send("POST", "/api/invites")).status_code == 403


# --- the owner's cost page --------------------------------------------------------------------


async def test_all_demos_are_one_line_in_the_cost_report(world: Demo) -> None:
    a = await world.visit("198.51.100.1")
    b = await world.visit("198.51.100.2")
    ua, ub = await world.user_of(a), await world.user_of(b)
    owner = await world.owner()
    real = await world.user_of(owner)
    await world.spend(ua.id, "0.30")
    await world.spend(ub.id, "0.20")
    await world.spend(real.id, "1.00")
    await b.send("POST", "/api/me/delete", {"confirm": "DELETE"})  # one is erased: still counted

    async with world.engine.begin() as db:  # the test clock is not today's date
        await db.execute(update(demo_starts).values(day=utcnow().date()))
    report = (await owner.get("/api/ops/costs")).json()
    assert report["demo"] == {"cost": "0.5000", "calls": 6, "starts": 2}
    lines = {u["name"]: u for u in report["by_user"]}
    assert lines["Demo visitors"]["cost"] == "0.5000"
    assert lines["Demo visitors"]["user_id"] == "demo"
    assert sum(1 for u in report["by_user"] if u["name"] == "Demo visitors") == 1
    assert "Demo" not in {u["name"] for u in report["by_user"] if u["name"] != "Demo visitors"}
    assert report["month"]["spent"] == "1.5000"  # demo money is real money
    assert report["per_active_user_month"]  # demos are not counted as active users
    md = (await owner.get("/api/ops/costs", params={"format": "md"})).text
    assert "Demo visitors" in md and "2 demos started" in md


async def test_a_report_without_demos_says_so(world: Demo) -> None:
    owner = await world.owner()
    report = (await owner.get("/api/ops/costs")).json()
    assert report["demo"] == {"cost": "0.0000", "calls": 0, "starts": 0}


# --- smaller pieces -----------------------------------------------------------------------------


async def test_a_demo_user_made_by_hand_still_needs_a_negative_id(uow: UowFactory) -> None:
    with pytest.raises(IntegrityError):
        await register_user(
            uow(),
            RegisterUser(
                telegram_user_id=4242,
                home_currency="SGD",
                demo_expires_at=NOW + timedelta(hours=1),
            ),
        )


async def test_the_real_session_check_of_an_unknown_token_is_still_none(uow: UowFactory) -> None:
    assert await access.resolve_session(uow(), "nope", now=NOW) is None


async def test_the_cap_only_ever_reads_a_users_demo_rows(world: Demo) -> None:
    # A UserId alone is not enough to be counted: the account must be a demo account.
    owner = await world.owner()
    me = await world.user_of(owner)
    await world.spend(me.id, "9.00")
    assert await DemoStore(world.engine).spent_today() == 0
    assert await DemoStore(world.engine).usage(me.id) is None
    assert await DemoStore(world.engine).use(me.id, demo.Use.MESSAGE) is None
