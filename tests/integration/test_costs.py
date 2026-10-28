"""What the AI models cost, through the real database and app: a call is counted under its
feature and user, rows add up across flushes, a failing database never reaches the caller,
the owner (and only the owner) reads the figures, and a user's rows are exported and erased
with them. Every name, model and figure is made up."""

import json
import zipfile
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import BaseMessage
from pydantic import SecretStr
from sqlalchemy import insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nexus.agent.image_look import ImageKind, ImageLook
from nexus.agent.receipts import ReceiptDraft
from nexus.application import costs
from nexus.application.clock import utcnow
from nexus.domain.ledger import UserId
from nexus.infra.cost_store import CostStore
from nexus.infra.db.tables import model_costs, users
from nexus.jobs.runner import JobRunner
from tests.fakes import FakeImageLooker, FakeReceipts, FakeSpeech, call, say, scripted
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_agent import build, only
from tests.integration.test_jobs_budgets import Clock, enqueue
from tests.integration.test_row_security import acting
from tests.integration.test_web_api import MEMBER, OWNER, World, owner_and_invite
from tests.pdfs import make_pdf

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

D = Decimal
MODEL = "made-up/main"


@pytest.fixture
async def store(engine: AsyncEngine) -> AsyncIterator[CostStore]:
    """A store that counts every call made in the test, as the app's own does."""
    found = CostStore(engine)
    costs.set_sink(found.add)
    try:
        yield found
    finally:
        costs.set_sink(None)


@pytest.fixture
def seen() -> Iterator[list[costs.Charge]]:
    """Every call made in the test, as the sink was handed it."""
    found: list[costs.Charge] = []
    costs.set_sink(found.append)
    try:
        yield found
    finally:
        costs.set_sink(None)


async def stored(engine: AsyncEngine) -> list[dict[str, Any]]:
    async with engine.connect() as db:
        found = await db.execute(select(model_costs).order_by(model_costs.c.id))
        return [dict(r._mapping) for r in found]


def charge(text: str = "Done.") -> Callable[[list[BaseMessage]], Any]:
    """A scripted model turn that costs 0.01 (as OpenRouter would have said) and says ``text``."""

    def step(_: list[BaseMessage]) -> Any:
        costs.record("made-up/scripted", input_tokens=500, output_tokens=40, cost="0.01")
        return say(text)

    return step


# --- a call is stored under its feature and user -------------------------------------------


async def test_a_call_is_stored_with_its_feature_and_user(
    engine: AsyncEngine, store: CostStore, alice: UserId
) -> None:
    with costs.scope("chat", user=alice):
        costs.record(MODEL, input_tokens=1200, output_tokens=300, cost="0.000456")
    assert await store.flush() == 1
    [row] = await stored(engine)
    assert (row["feature"], row["user_id"], row["model"]) == ("chat", alice, MODEL)
    assert (row["calls"], row["input_tokens"], row["output_tokens"]) == (1, 1200, 300)
    assert row["cost_usd"] == D("0.000456")
    assert row["day"] == utcnow().date()
    # Numbers only: nothing in the table can hold what anyone said.
    assert {c.name for c in model_costs.c} == {
        "id", "day", "user_id", "feature", "model", "calls", "input_tokens", "output_tokens",
        "cost_usd",
    }  # fmt: skip


async def test_calls_add_up_across_flushes_in_one_row(
    engine: AsyncEngine, store: CostStore, alice: UserId, bob: UserId
) -> None:
    for _ in range(3):
        with costs.scope("chat", user=alice):
            costs.record(MODEL, input_tokens=100, output_tokens=10, cost="0.001")
    with costs.scope("chat", user=bob):
        costs.record(MODEL, cost="0.5")
    assert await store.flush() == 2  # three calls of alice's were one entry in the buffer
    with costs.scope("chat", user=alice):
        costs.record(MODEL, input_tokens=100, output_tokens=10, cost="0.001")
    assert await store.flush() == 1
    rows = {r["user_id"]: r for r in await stored(engine)}
    assert len(rows) == 2
    mine = rows[alice]
    assert (mine["calls"], mine["input_tokens"], mine["output_tokens"]) == (4, 400, 40)
    assert mine["cost_usd"] == D("0.004")
    assert rows[bob]["calls"] == 1 and rows[bob]["cost_usd"] == D("0.5")


async def test_work_for_no_one_adds_up_in_one_row_too(
    engine: AsyncEngine, store: CostStore
) -> None:
    # NULL is never equal to NULL in a unique index; the table counts them as one user.
    for _ in range(2):
        with costs.scope("travel.photos"):
            costs.record(MODEL, cost="0.002")
        await store.flush()
    [row] = await stored(engine)
    assert row["user_id"] is None and row["calls"] == 2 and row["cost_usd"] == D("0.004")


async def test_each_feature_model_and_day_has_its_own_row(
    engine: AsyncEngine, store: CostStore, alice: UserId
) -> None:
    yesterday = utcnow() - timedelta(days=1)
    with costs.scope("chat", user=alice):
        costs.record(MODEL, cost="0.1")
        costs.record("made-up/other", cost="0.1")
        costs.record(MODEL, cost="0.1", at=yesterday)
    with costs.scope("voice", user=alice):
        costs.record(MODEL, cost="0.1")
    await store.flush()
    keys = {(r["day"], r["feature"], r["model"]) for r in await stored(engine)}
    today = utcnow().date()
    assert keys == {
        (today, "chat", MODEL),
        (today, "chat", "made-up/other"),
        (yesterday.date(), "chat", MODEL),
        (today, "voice", MODEL),
    }


# --- recording never breaks or slows a reply ---------------------------------------------------


async def test_recording_is_in_memory_only_until_the_flush(
    engine: AsyncEngine, store: CostStore, alice: UserId
) -> None:
    with costs.scope("chat", user=alice):
        costs.record(MODEL, cost="0.1")
    assert await stored(engine) == []  # nothing waits on the database


async def test_a_database_that_is_down_never_raises_and_nothing_is_lost(
    engine: AsyncEngine, alice: UserId
) -> None:
    down = create_async_engine("postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    store = CostStore(down)
    costs.set_sink(store.add)
    try:
        with costs.scope("chat", user=alice):
            costs.record(MODEL, cost="0.25")
        assert await store.flush() == 0  # logged and swallowed
        with costs.scope("chat", user=alice):
            costs.record(MODEL, cost="0.25")
        assert await store.flush() == 0
    finally:
        costs.set_sink(None)
        await down.dispose()
    store._engine = engine  # the database is back: the same buffer is written
    assert await store.flush() == 1
    [row] = await stored(engine)
    assert row["calls"] == 2 and row["cost_usd"] == D("0.5")


async def test_a_user_erased_before_the_flush_costs_the_others_nothing(
    engine: AsyncEngine, store: CostStore, alice: UserId
) -> None:
    gone = UserId(uuid4())
    with costs.scope("chat", user=gone):
        costs.record(MODEL, cost="0.3")
    with costs.scope("chat", user=alice):
        costs.record(MODEL, cost="0.4")
    with costs.scope("travel.photos"):
        costs.record(MODEL, cost="0.2")
    assert await store.flush() == 2
    assert {r["user_id"] for r in await stored(engine)} == {alice, None}


async def test_the_loop_flushes_and_writes_what_is_left_when_it_stops(
    engine: AsyncEngine, store: CostStore, alice: UserId
) -> None:
    import asyncio

    stop = asyncio.Event()
    task = asyncio.create_task(store.run(stop))
    await asyncio.sleep(0.2)
    with costs.scope("chat", user=alice):
        costs.record(MODEL, cost="0.1")
    stop.set()  # before the next flush is due
    await asyncio.wait_for(task, 10)
    [row] = await stored(engine)
    assert row["calls"] == 1


async def test_thirteen_months_are_kept(engine: AsyncEngine, store: CostStore) -> None:
    today = date(2026, 10, 28)
    store._clock = lambda: datetime(2026, 10, 28, 9, tzinfo=UTC)
    days = [date(2025, 9, 30), date(2025, 10, 1), date(2026, 3, 1), today]
    async with engine.begin() as db:
        await db.execute(
            insert(model_costs),
            [{"day": d, "feature": "chat", "model": MODEL, "calls": 1} for d in days],
        )
    assert await store.prune() == 1
    assert [r["day"] for r in await stored(engine)] == days[1:]


# --- attribution at the entry points ----------------------------------------------------------


async def test_a_text_turn_is_chat_for_the_user(
    uow: UowFactory, seen: list[costs.Charge], alice: UserId
) -> None:
    agent = build(uow, scripted(charge("Hi!")))
    assert only(await agent.handle_text(alice, "hello", "tg:1:1")).text == "Hi!"
    [call] = seen
    assert (call.feature, call.user_id, call.model, call.cost) == (
        "chat", alice, "made-up/scripted", D("0.01"),
    )  # fmt: skip


async def test_a_voice_note_a_photo_and_a_pdf_have_their_own_features(
    uow: UowFactory, seen: list[costs.Charge], alice: UserId
) -> None:
    model = scripted(charge("Heard."), charge("A menu."), charge("An invoice."))
    look = ImageLook(ImageKind.OTHER, "SGD", "A noodle menu.", "Wonton Mee 8.50")
    agent = build(
        uow,
        model,
        FakeReceipts(ReceiptDraft(is_receipt=False)),
        looker=FakeImageLooker([look]),
        speech=FakeSpeech(["what is on the menu"]),
    )
    await agent.handle_voice(alice, b"made-up-audio", "audio/ogg", "tg:v1")
    await agent.handle_photo(alice, b"\xff\xd8jpeg", "image/jpeg", None, "tg:p1")
    await agent.handle_pdf(alice, make_pdf(["Amount due: 88.00"]), "bill.pdf", None, "tg:f1")
    assert [(c.feature, c.user_id) for c in seen] == [
        ("voice", alice),
        ("photo", alice),
        ("pdf", alice),
    ]


async def test_every_model_call_of_a_turn_is_counted(
    uow: UowFactory, seen: list[costs.Charge], alice: UserId
) -> None:
    # A tool call and then the reply: two model calls, both chat for the same user.
    def first(_: list[BaseMessage]) -> Any:
        costs.record("made-up/scripted", cost="0.01")
        return call("log_expense", amount="5", merchant="Kopi")

    agent = build(uow, scripted(first, charge("Logged.")))
    await agent.handle_text(alice, "kopi 5", "tg:1:1")
    assert [(c.feature, c.user_id) for c in seen] == [("chat", alice)] * 2


async def test_a_job_counts_under_its_kind_and_the_user_in_its_payload(
    engine: AsyncEngine, uow: UowFactory, store: CostStore, alice: UserId
) -> None:
    async def handler(payload: dict[str, Any]) -> None:
        costs.record(MODEL, cost="0.02")

    clock = Clock()
    await enqueue(uow, "memory.update", "m-1", clock.now, user_id=str(alice))
    await enqueue(uow, "travel.photos", "t-1", clock.now)
    await enqueue(uow, "market.summary.user", "s-1", clock.now, user_id="not-a-user")
    runner = JobRunner(
        engine,
        {"memory.update": handler, "travel.photos": handler, "market.summary.user": handler},
        clock=clock,
    )
    assert await runner.tick() == 3
    await store.flush()
    found = {(r["feature"], r["user_id"]) for r in await stored(engine)}
    assert found == {
        ("memory.update", alice),
        ("travel.photos", None),
        ("market.summary.user", None),  # a payload that names no real user
    }


async def test_a_step_of_a_research_run_counts_under_its_run_kind(
    engine: AsyncEngine, uow: UowFactory, store: CostStore, alice: UserId
) -> None:
    from nexus.application import departments as department_cases

    assert department_cases.STEP_JOB == "department.step"
    # The kind is appended inside ``advance``; the job kind is the base it is built on.
    with costs.scope(f"{department_cases.STEP_JOB}.stock_plan", user=alice):
        costs.record(MODEL, cost="0.03")
    await store.flush()
    [row] = await stored(engine)
    assert row["feature"] == "department.step.stock_plan"


# --- the owner's page ------------------------------------------------------------------------


async def user_id(engine: AsyncEngine, telegram_id: int) -> UserId:
    async with engine.connect() as db:
        found = await db.scalar(select(users.c.id).where(users.c.telegram_user_id == telegram_id))
    assert found is not None
    return UserId(found)


async def add_rows(engine: AsyncEngine, rows: list[dict[str, Any]]) -> None:
    async with engine.begin() as db:
        await db.execute(insert(model_costs), rows)


def cost_row(
    day: date, cost: str, *, user: UUID | None, feature: str = "chat", model: str = MODEL,
    calls: int = 1,
) -> dict[str, Any]:  # fmt: skip
    return {
        "day": day,
        "user_id": user,
        "feature": feature,
        "model": model,
        "calls": calls,
        "input_tokens": 1000 * calls,
        "output_tokens": 100 * calls,
        "cost_usd": D(cost),
    }


async def test_only_the_owner_or_the_ops_token_reads_the_costs(world: World) -> None:
    anyone = world.browser()
    assert (await anyone.get("/api/ops/costs")).status_code == 404
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    await member.login(MEMBER, invite)
    assert (await member.get("/api/ops/costs")).status_code == 404
    assert (await member.get("/api/ops/costs?format=md")).status_code == 404
    assert (await owner.get("/api/ops/costs")).status_code == 200

    world.app.state.settings = world.app.state.settings.model_copy(
        update={"ops_token": SecretStr("made-up-ops-token")}
    )
    script = world.browser()
    wrong = await script.get("/api/ops/costs", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 404
    right = await script.get(
        "/api/ops/costs", headers={"Authorization": "Bearer made-up-ops-token"}
    )
    assert right.status_code == 200 and right.json()["currency"] == "USD"


async def test_the_costs_page_adds_up_across_users(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    await member.login(MEMBER, invite)
    boss, guest = await user_id(world.engine, OWNER), await user_id(world.engine, MEMBER)
    async with world.engine.begin() as db:
        await db.execute(
            update(users).where(users.c.id == guest).values(display_name="Ben Example")
        )
        await db.execute(update(users).where(users.c.id == boss).values(display_name=None))
    today = utcnow().date()
    month_start = today.replace(day=1)
    await add_rows(
        world.engine,
        [
            cost_row(today, "1.5", user=boss, calls=10),
            cost_row(today, "0.5", user=guest, feature="photo", model="made-up/eyes", calls=2),
            cost_row(today, "0.25", user=None, feature="memory.update", calls=7),
            cost_row(today - timedelta(days=1), "1", user=guest, calls=4),
            cost_row(today - timedelta(days=40), "9", user=guest),  # outside any 30-day window
        ],
    )
    page = (await owner.get("/api/ops/costs?days=30")).json()

    # Days: the last 30, oldest first, zero-filled.
    assert [d["day"] for d in page["days"]] == [
        (today - timedelta(days=n)).isoformat() for n in range(29, -1, -1)
    ]
    assert page["days"][-1] == {"day": today.isoformat(), "cost": "2.2500", "calls": 19}
    assert page["days"][-2] == {
        "day": (today - timedelta(days=1)).isoformat(), "cost": "1.0000", "calls": 4,
    }  # fmt: skip
    assert page["days"][0]["cost"] == "0.0000" and page["days"][0]["calls"] == 0

    assert page["by_feature"] == [
        {"feature": "chat", "cost": "2.5000", "calls": 14, "share": 0.7692},
        {"feature": "photo", "cost": "0.5000", "calls": 2, "share": 0.1538},
        {"feature": "memory.update", "cost": "0.2500", "calls": 7, "share": 0.0769},
    ]
    assert page["by_user"] == [
        {"user_id": str(boss), "name": f"User {str(boss)[:8]}", "cost": "1.5000", "calls": 10},
        {"user_id": str(guest), "name": "Ben Example", "cost": "1.5000", "calls": 6},
        {"user_id": None, "name": "System", "cost": "0.2500", "calls": 7},
    ]  # equal costs: the one with more calls first
    assert [m["model"] for m in page["by_model"]] == [MODEL, "made-up/eyes"]
    assert page["by_model"][0] == {
        "model": MODEL, "cost": "2.7500", "calls": 21, "input_tokens": 21000,
        "output_tokens": 2100,
    }  # fmt: skip

    # The month: today and yesterday (when yesterday is still this month), projected.
    spent = D("2.25") + (D("1") if today.day > 1 else D(0))
    month = page["month"]
    assert month["start"] == month_start.isoformat()
    assert month["spent"] == f"{spent:.4f}"
    assert month["days_elapsed"] == today.day
    assert month["days_in_month"] in {28, 29, 30, 31}
    projected = (spent / today.day * month["days_in_month"]).quantize(D("0.01"), "ROUND_HALF_UP")
    assert month["projected"] == str(projected)
    mine = spent - D("0.25")  # the system's row is no one's
    expected = (mine / 2 / today.day * month["days_in_month"]).quantize(  # two users had calls
        D("0.01"), "ROUND_HALF_UP"
    )
    assert page["per_active_user_month"] == str(expected)


async def test_the_window_and_the_markdown(world: World) -> None:
    owner, _ = await owner_and_invite(world)
    boss = await user_id(world.engine, OWNER)
    today = utcnow().date()
    await add_rows(
        world.engine,
        [
            cost_row(today, "1", user=boss),
            cost_row(today - timedelta(days=5), "2", user=boss),
        ],
    )
    short = (await owner.get("/api/ops/costs?days=3")).json()
    assert len(short["days"]) == 3 and short["by_feature"][0]["cost"] == "1.0000"
    longer = (await owner.get("/api/ops/costs?days=10")).json()
    assert longer["by_feature"][0]["cost"] == "3.0000"
    for bad in ("days=0", "days=401", "days=x", "format=xml"):
        assert (await owner.get(f"/api/ops/costs?{bad}")).status_code == 422

    markdown = await owner.get("/api/ops/costs?days=3&format=md")
    assert markdown.status_code == 200 and markdown.headers["content-type"].startswith(
        "text/markdown"
    )
    assert markdown.text.startswith("# Nexus model costs") and "## By model" in markdown.text


async def test_an_empty_page_is_all_zeros(world: World) -> None:
    owner, _ = await owner_and_invite(world)
    page = (await owner.get("/api/ops/costs?days=7")).json()
    assert len(page["days"]) == 7 and {d["cost"] for d in page["days"]} == {"0.0000"}
    assert page["by_feature"] == page["by_user"] == page["by_model"] == []
    assert page["month"]["spent"] == "0.0000" and page["per_active_user_month"] == "0.00"


async def test_calls_not_yet_written_are_on_the_page(world: World) -> None:
    owner, _ = await owner_and_invite(world)
    boss = await user_id(world.engine, OWNER)
    with costs.scope("chat", user=boss):
        costs.record(MODEL, input_tokens=10, output_tokens=2, cost="0.07")
    page = (await owner.get("/api/ops/costs?days=1")).json()
    assert page["days"][0]["cost"] == "0.0700" and page["by_feature"][0]["feature"] == "chat"


async def test_a_chat_turn_through_the_app_is_counted(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    boss = await user_id(world.engine, OWNER)

    def step(_: list[BaseMessage]) -> Any:
        costs.record("made-up/scripted", input_tokens=900, output_tokens=60, cost="0.015")
        return say("Hi!")

    world.model.script += [step]
    assert (await owner.send("POST", "/api/chat", {"message": "hello"})).status_code == 200
    await world.app.state.costs.flush()
    [row] = await stored(world.engine)
    assert (row["feature"], row["user_id"], row["cost_usd"]) == ("chat", boss, D("0.015"))
    page = (await owner.get("/api/ops/costs?days=1")).json()
    assert page["by_user"][0]["user_id"] == str(boss)


# --- a user's rows ---------------------------------------------------------------------------


async def test_a_users_costs_are_exported_and_erased_with_them(world: World) -> None:
    owner, invite = await owner_and_invite(world)
    member = world.browser()
    await member.login(MEMBER, invite)
    boss, guest = await user_id(world.engine, OWNER), await user_id(world.engine, MEMBER)
    today = utcnow().date()
    await add_rows(
        world.engine,
        [
            cost_row(today, "0.75", user=guest, feature="voice"),
            cost_row(today, "0.5", user=boss),
            cost_row(today, "0.25", user=None, feature="memory.update"),
        ],
    )

    export = await member.get("/api/me/export")
    assert export.status_code == 200
    archive = zipfile.ZipFile(BytesIO(export.content))
    mine = json.loads(archive.read("costs.json"))["model_costs"]
    assert [(r["feature"], r["cost_usd"], r["input_tokens"]) for r in mine] == [
        ("voice", "0.750000", 1000)
    ]  # theirs only: not the owner's, not the system's

    assert (await member.send("POST", "/api/me/delete", {"confirm": "DELETE"})).status_code == 204
    left = await stored(world.engine)
    assert {(r["user_id"], r["feature"]) for r in left} == {(boss, "chat"), (None, "memory.update")}
    page = (await owner.get("/api/ops/costs?days=1")).json()
    assert page["month"]["spent"] == "0.7500"


async def test_row_security_shows_a_user_only_their_own_costs(
    engine: AsyncEngine, alice: UserId, bob: UserId
) -> None:
    today = utcnow().date()
    await add_rows(
        engine,
        [
            cost_row(today, "1", user=alice),
            cost_row(today, "2", user=bob),
            cost_row(today, "3", user=None, feature="memory.update"),
        ],
    )
    async with acting(engine, alice) as db:
        seen = (await db.execute(text("SELECT user_id FROM model_costs"))).scalars().all()
        assert list(seen) == [alice]
    async with acting(engine, None) as db:  # the owner's page, jobs, the writer: no one named
        assert len((await db.execute(text("SELECT 1 FROM model_costs"))).all()) == 3
