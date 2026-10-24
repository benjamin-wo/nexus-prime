"""The time zone that follows the user, against a real Postgres: the migration, what the
phone, the chat and the trips say, the one message when the zone changes, the hourly trip
sweep, the web API and the chat tool. The made-up user lives in Singapore (UTC+8); every
place and name is made up apart from the zones."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
from alembic import command
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.graph import CORE_TOOLS, AgentDeps, AgentGraph
from nexus.agent.service import AgentService
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application import trips as trip_cases
from nexus.application import whereabouts as where
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.users import RegisterUser, register_user
from nexus.application.weather import Weather, WeatherError
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import User, ZoneSource
from nexus.domain.trips import Stop
from nexus.domain.weather import Spot
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import jobs, users
from nexus.infra.weather.open_meteo import OpenMeteo
from nexus.jobs.handlers import SCHEDULES, build_handlers
from nexus.jobs.runner import Handler, JobRunner
from tests.fakes import NOW, FakeRates, FakeTelegram, FakeWeather, call, say, scripted
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_agent import only, tool_results
from tests.integration.test_email import person
from tests.integration.test_web_api import MEMBER, OWNER, World

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

HOME = "Asia/Singapore"
MADRID = "Europe/Madrid"
TOKYO = "Asia/Tokyo"
PHONE, CHAT, TRIP, HOME_SRC = (
    ZoneSource.PHONE,
    ZoneSource.CHAT,
    ZoneSource.TRIP,
    ZoneSource.HOME,
)
SEP_28 = NOW  # 12:00 in Singapore, 06:00 in Madrid


def hours(n: float, start: datetime = NOW) -> datetime:
    return start + timedelta(hours=n)


@dataclass
class Scene:
    uow: UowFactory
    engine: AsyncEngine
    telegram: FakeTelegram
    handlers: dict[str, Handler]
    source: FakeWeather
    weather: Weather
    user: User
    clock: datetime = NOW

    async def report(
        self, zone: str | None, source: ZoneSource, at: datetime | None = None, **kw: Any
    ) -> where.Reported:
        return await where.report_zone(
            self.uow(), self.user.id, zone, source, at or self.clock, **kw
        )

    async def now(self, user: User | None = None) -> User:
        async with self.uow() as tx:
            found = await tx.ledger.get_user((user or self.user).id)
        assert found is not None
        return found

    async def sweep(self, at: datetime) -> int:
        return await where.follow_trips(self.uow, self.weather, now=at)

    async def queued(self) -> list[str]:
        async with self.engine.connect() as db:
            rows = await db.execute(
                select(jobs.c.payload).where(jobs.c.kind == TELEGRAM_SEND).order_by(jobs.c.id)
            )
            payloads: list[dict[str, Any]] = list(rows.scalars())
            return [p["text"] for p in payloads]

    async def told(self, at: datetime | None = None) -> list[str]:
        """Run every queued send, as the job runner would, and say what went out."""
        runner = JobRunner(self.engine, self.handlers, clock=lambda: at or self.clock)
        while await runner.tick():
            pass
        return [s.text for s in self.telegram.sent]


@pytest.fixture
async def scene(uow: UowFactory, engine: AsyncEngine) -> Scene:
    telegram = FakeTelegram()
    source = FakeWeather(zones={"Madrid": MADRID, "Lisbon": "Europe/Lisbon", "Spain": MADRID})
    weather = Weather(source, clock=lambda: NOW)
    user = await person(uow)
    handlers = build_handlers(uow, telegram, FakeRates(), lambda: NOW, zones=weather)
    return Scene(uow, engine, telegram, handlers, source, weather, user)


async def spain_trip(scene: Scene, *, stops: bool = True) -> None:
    """Madrid from 27 to 30 September, then Lisbon to 2 October."""
    trip = await trip_cases.create_trip(
        scene.uow(),
        scene.user,
        trip_cases.TripDraft("Spain", date(2026, 9, 27), date(2026, 10, 2), "EUR"),
        now=NOW,
    )
    if stops:
        await trip_cases.set_stops(
            scene.uow(),
            scene.user,
            trip.id,
            [
                Stop("Madrid", date(2026, 9, 27), date(2026, 9, 30)),
                Stop("Lisbon", date(2026, 9, 30), date(2026, 10, 2)),
            ],
            now=NOW,
        )


# --- the user ------------------------------------------------------------------------------


async def test_a_new_user_lives_where_they_are(scene: Scene) -> None:
    assert (scene.user.timezone, scene.user.home_timezone) == (HOME, HOME)
    assert scene.user.timezone_source is HOME_SRC and scene.user.timezone_set_at is None


# --- what the phone and the user say ---------------------------------------------------------


async def test_the_phone_moves_the_user_and_they_are_told_once(scene: Scene) -> None:
    reported = await scene.report(MADRID, PHONE)
    assert (reported.changed, reported.old, reported.new) == (True, HOME, MADRID)
    assert reported.user.timezone == MADRID
    now = await scene.now()
    assert (now.timezone, now.home_timezone, now.timezone_source) == (MADRID, HOME, PHONE)
    assert now.timezone_set_at == NOW
    assert await scene.queued() == ["🕑 Switched to Madrid time (UTC+2)."]
    # NOW is 06:00 in Madrid: quiet hours there, so the note waits for the morning. It is a
    # timezone note, never counted toward the day's cap.
    assert await scene.told() == []
    async with scene.engine.connect() as db:
        row = (await db.execute(text("SELECT kind, level, status FROM notifications"))).one()
    assert tuple(row) == ("timezone", "now", "held")


async def test_a_phone_repeating_the_zone_only_refreshes_when_it_said_so(scene: Scene) -> None:
    await scene.report(MADRID, PHONE)
    again = await scene.report(MADRID, PHONE, hours(5))
    assert again.changed is False and (again.old, again.new) == (MADRID, MADRID)
    assert (await scene.now()).timezone_set_at == hours(5)
    assert await scene.queued() == ["🕑 Switched to Madrid time (UTC+2)."]


async def test_a_phone_at_home_when_at_home_says_nothing(scene: Scene) -> None:
    reported = await scene.report(HOME, PHONE)
    assert reported.changed is False
    assert await scene.queued() == []
    assert (await scene.now()).timezone_set_at == NOW


async def test_telling_the_chat_you_are_home_goes_back_with_its_own_message(scene: Scene) -> None:
    await scene.report(MADRID, CHAT)
    assert (await scene.now()).timezone_source is CHAT
    back = await scene.report(None, ZoneSource.HOME, hours(3))
    assert (back.changed, back.new) == (True, HOME)
    now = await scene.now()
    assert (now.timezone, now.timezone_source) == (HOME, HOME_SRC)
    assert await scene.told(hours(3)) == [
        "🕑 Switched to Madrid time (UTC+2).",
        "🕑 Back on Singapore time.",
    ]


async def test_a_phone_in_the_home_zone_is_home(scene: Scene) -> None:
    await scene.report(MADRID, PHONE)
    back = await scene.report(HOME, PHONE, hours(30))
    assert back.changed is True
    assert (await scene.now()).timezone_source is HOME_SRC
    assert (await scene.queued())[-1] == "🕑 Back on Singapore time."


async def test_a_caller_whose_reply_says_it_sends_no_message(scene: Scene) -> None:
    reported = await scene.report(MADRID, CHAT, notify=False)
    assert reported.changed is True
    assert await scene.queued() == []


async def test_an_unknown_zone_is_refused_and_nothing_is_saved(scene: Scene) -> None:
    for source in (PHONE, CHAT, TRIP):
        with pytest.raises(InvalidInput, match="unknown time zone"):
            await scene.report("Mars/Olympus", source)
    now = await scene.now()
    assert (now.timezone, now.timezone_source, now.timezone_set_at) == (HOME, HOME_SRC, None)
    assert await scene.queued() == []


async def test_a_user_without_a_telegram_chat_changes_zone_without_a_message(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    registration = await register_user(
        uow(), RegisterUser(77, "SGD", telegram_chat_id=None, timezone=HOME)
    )
    reported = await where.report_zone(uow(), registration.user.id, MADRID, PHONE, NOW)
    assert reported.changed is True
    async with engine.connect() as db:
        assert (await db.execute(select(jobs))).all() == []


# --- tenant isolation -------------------------------------------------------------------------


async def test_one_users_zone_never_moves_anothers(scene: Scene, uow: UowFactory) -> None:
    other = await person(uow, 5151)
    await scene.report(MADRID, PHONE)
    assert (await scene.now(other)).timezone == HOME
    await where.report_zone(uow(), other.id, TOKYO, CHAT, NOW)
    assert (await scene.now()).timezone == MADRID
    assert (await scene.now(other)).timezone_source is CHAT
    async with uow() as tx:
        assert await tx.ledger.users_with_zone_source(TRIP) == []
        await tx.ledger.set_timezone(other.id, MADRID, TRIP, None)
        await tx.commit()
    async with uow() as tx:
        assert await tx.ledger.users_with_zone_source(TRIP) == [other.id]


async def test_a_trip_moves_only_its_own_traveller(scene: Scene, uow: UowFactory) -> None:
    other = await person(uow, 5151)
    await spain_trip(scene)
    assert await scene.sweep(NOW) == 1
    assert (await scene.now()).timezone == MADRID
    assert (await scene.now(other)).timezone == HOME


# --- the trip -------------------------------------------------------------------------------


async def test_the_trip_sweep_follows_the_stops_and_goes_home_after(scene: Scene) -> None:
    await spain_trip(scene)
    assert await scene.sweep(NOW) == 1
    now = await scene.now()
    assert (now.timezone, now.timezone_source, now.timezone_set_at) == (MADRID, TRIP, None)
    assert await scene.sweep(hours(1)) == 0  # nothing new to say

    lisbon_day = datetime(2026, 9, 30, 10, tzinfo=UTC)  # the travel day: the stop arrived at
    assert await scene.sweep(lisbon_day) == 1
    assert (await scene.now()).timezone == "Europe/Lisbon"

    after = datetime(2026, 10, 3, 10, tzinfo=UTC)
    assert await scene.sweep(after) == 1
    now = await scene.now()
    assert (now.timezone, now.timezone_source) == (HOME, HOME_SRC)
    assert await scene.sweep(hours(1, after)) == 0
    assert await scene.queued() == [
        "🕑 Switched to Madrid time (UTC+2).",
        "🕑 Switched to Lisbon time (UTC+1).",
        "🕑 Back on Singapore time.",
    ]


async def test_without_stops_the_trip_is_where_its_destination_is(scene: Scene) -> None:
    await spain_trip(scene, stops=False)
    assert await scene.sweep(NOW) == 1
    assert (await scene.now()).timezone == MADRID


async def test_a_recent_phone_signal_beats_the_trip(scene: Scene) -> None:
    await spain_trip(scene)
    await scene.report(HOME, PHONE)  # the phone says they are still at home
    assert await scene.sweep(hours(1)) == 0
    assert (await scene.now()).timezone == HOME
    assert await scene.sweep(hours(23)) == 0
    # A day on, with the phone quiet, the trip applies.
    assert await scene.sweep(hours(25)) == 1
    assert (await scene.now()).timezone == MADRID


async def test_what_the_user_said_in_chat_beats_the_trip_for_a_day(scene: Scene) -> None:
    await spain_trip(scene)
    await scene.report(TOKYO, CHAT)
    assert await scene.sweep(hours(2)) == 0
    assert (await scene.now()).timezone == TOKYO
    assert await scene.sweep(hours(26)) == 1  # tomorrow the trip's stop wins again
    assert (await scene.now()).timezone == MADRID


async def test_a_phone_in_the_trips_zone_keeps_the_user_there_when_the_trip_ends(
    scene: Scene,
) -> None:
    await spain_trip(scene)
    await scene.sweep(NOW)
    await scene.report(MADRID, PHONE, hours(2))
    assert await scene.sweep(datetime(2026, 10, 3, 10, tzinfo=UTC)) == 0
    assert (await scene.now()).timezone == MADRID


async def test_a_place_that_cannot_be_found_leaves_the_zone_alone(scene: Scene) -> None:
    await spain_trip(scene)
    await scene.sweep(NOW)
    scene.source.finding_fails = True  # the geocoder goes down mid-trip
    scene.weather = Weather(scene.source, clock=lambda: NOW)  # nothing cached
    assert await scene.sweep(datetime(2026, 9, 30, 10, tzinfo=UTC)) == 0
    now = await scene.now()
    assert (now.timezone, now.timezone_source) == (MADRID, TRIP)  # not sent home either


async def test_the_sweep_is_scheduled_hourly_and_runs_as_a_job(scene: Scene) -> None:
    assert any(s.kind == where.FOLLOW_JOB and s.every == timedelta(hours=1) for s in SCHEDULES)
    await spain_trip(scene)
    await scene.handlers[where.FOLLOW_JOB]({})
    assert (await scene.now()).timezone == MADRID


async def test_one_bad_user_does_not_stop_the_sweep(scene: Scene, uow: UowFactory) -> None:
    other = await person(uow, 5151)
    await spain_trip(scene)
    await trip_cases.create_trip(
        uow(), other,
        trip_cases.TripDraft("Spain", date(2026, 9, 27), date(2026, 10, 2), "EUR"),
        now=NOW,
    )  # fmt: skip
    async with scene.engine.begin() as db:  # a zone the system no longer knows
        await db.execute(
            text("UPDATE users SET timezone = 'Mars/Olympus' WHERE id = :id"), {"id": scene.user.id}
        )
    assert await scene.sweep(NOW) == 1
    assert (await scene.now(other)).timezone == MADRID


# --- finding a zone from a place -------------------------------------------------------------


async def test_a_places_zone_comes_from_the_weather_geocoding_and_its_cache() -> None:
    source = FakeWeather(zones={"Madrid": MADRID})
    weather = Weather(source, clock=lambda: NOW)
    assert await weather.zone_of("Madrid") == MADRID
    assert await weather.zone_of(" madrid ") == MADRID
    assert source.asked == ["find:Madrid"]  # the second ask came from the cache
    assert await weather.zone_of("Nowhere") is None
    assert await weather.zone_of("Atlantis") is None  # found, but no zone given
    assert await weather.zone_of("   ") is None


async def test_finding_a_zone_never_fails() -> None:
    source = FakeWeather(zones={"Madrid": MADRID}, finding_fails=True)
    assert await Weather(source).zone_of("Madrid") is None


async def test_finding_a_zone_gives_up_after_a_moment(monkeypatch: pytest.MonkeyPatch) -> None:
    class Slow:
        async def find(self, name: str) -> Spot | None:
            await asyncio.sleep(5)
            raise AssertionError("not reached")  # pragma: no cover

    monkeypatch.setattr("nexus.application.weather.ZONE_TIMEOUT", 0.01)
    assert await Weather(Slow()).zone_of("Madrid") is None  # type: ignore[arg-type]


async def test_the_geocoder_gives_the_zone_and_junk_is_dropped() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        name = request.url.params["name"]
        zone = {"Madrid": MADRID, "Odd": "Not/AZone"}.get(name)
        row: dict[str, Any] = {"name": name, "latitude": 40.4, "longitude": -3.7}
        if zone:
            row["timezone"] = zone
        return httpx.Response(200, json={"results": [row]})

    source = OpenMeteo(httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    madrid, odd, none = [await source.find(n) for n in ("Madrid", "Odd", "Plain")]
    assert madrid is not None and madrid.timezone == MADRID
    assert odd is not None and odd.timezone is None
    assert none is not None and none.timezone is None
    with pytest.raises(WeatherError):
        await OpenMeteo(
            httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
        ).find("Madrid")


# --- the migration ------------------------------------------------------------------------------


async def test_migration_0055_backfills_and_goes_down_again(
    engine: AsyncEngine, empty_database_url: str
) -> None:
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0054")

    async def columns() -> set[str]:
        async with engine.connect() as db:
            rows = await db.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name='users'")
            )
            return set(rows.scalars().all())

    before = await columns()
    assert not {"home_timezone", "timezone_source", "timezone_set_at"} & before
    async with engine.begin() as db:
        for n, zone in enumerate(("Asia/Singapore", "Europe/Madrid")):
            await db.execute(
                text(
                    "INSERT INTO users (id, telegram_user_id, timezone, home_currency, role) "
                    "VALUES (gen_random_uuid(), :tg, :zone, 'SGD', 'owner')"
                ),
                {"tg": 900 + n, "zone": zone},
            )
    await upgrade(empty_database_url)
    assert {"home_timezone", "timezone_source", "timezone_set_at"} <= await columns()
    async with engine.connect() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT timezone, home_timezone, timezone_source, timezone_set_at "
                    "FROM users ORDER BY telegram_user_id"
                )
            )
        ).all()
    assert [tuple(r) for r in rows] == [
        ("Asia/Singapore", "Asia/Singapore", "home", None),
        ("Europe/Madrid", "Europe/Madrid", "home", None),
    ]
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(text("UPDATE users SET timezone_source = 'teleport'"))
    with pytest.raises(IntegrityError):  # the home zone is required
        async with engine.begin() as db:
            await db.execute(text("UPDATE users SET home_timezone = NULL"))
    await engine.dispose()
    await asyncio.to_thread(command.downgrade, config, "0054")
    assert await columns() == before


# --- the chat tool --------------------------------------------------------------------------------


def chat(uow: UowFactory, model: Any, zones: Weather | None) -> AgentService:
    skills = SkillLibrary.load()

    async def health() -> str:
        return "fine"

    graph = AgentGraph(
        AgentDeps(
            uow=uow,
            tools=build_tools(skills.body),
            primary=model,
            fallbacks=(),
            skill_index=skills.index(),
            skill_tools=skills.tools(),
            health=health,
            clock=lambda: NOW,
            zones=zones,
        )
    )
    return AgentService(graph.compile(InMemorySaver()), uow, None, lambda: NOW, None)


async def test_the_chat_tool_moves_the_user_and_the_prompt_follows(
    scene: Scene, uow: UowFactory
) -> None:
    model = scripted(
        say("hi"),
        call("set_timezone", place="Madrid"),
        say("Welcome to Madrid."),
        say("Still fine."),
        call("set_timezone", home=True),
        say("Welcome back."),
    )
    agent = chat(uow, model, scene.weather)
    uid = scene.user.id
    await agent.handle_text(uid, "hello", "tg:1:1")
    assert "set_timezone" in CORE_TOOLS and "set_timezone" in model.bound[0]
    system = model.seen[0][0]
    assert isinstance(system, SystemMessage)
    assert "(Asia/Singapore)" in str(system.content) and "home:" not in str(system.content)

    reply = only(await agent.handle_text(uid, "I'm in Madrid now", "tg:1:2"))
    assert reply.text == "Welcome to Madrid."
    assert tool_results(model) == ["Now on Madrid time (UTC+2), 06:00 there."]
    now = await scene.now()
    assert (now.timezone, now.home_timezone, now.timezone_source) == (MADRID, HOME, CHAT)
    assert await scene.queued() == []  # the reply already said it

    await agent.handle_text(uid, "ok", "tg:1:3")
    prompt = str(model.seen[-1][0].content)
    assert f"Now: Monday 2026-09-28 06:00 ({MADRID}, home: {HOME})" in prompt

    await agent.handle_text(uid, "I'm back home", "tg:1:4")
    assert tool_results(model)[-1:] == ["Back on Singapore time (UTC+8), 12:00 there."]
    now = await scene.now()
    assert (now.timezone, now.timezone_source) == (HOME, HOME_SRC)


async def test_the_chat_tool_takes_zone_names_and_says_when_nothing_changed(
    scene: Scene, uow: UowFactory
) -> None:
    model = scripted(
        call("set_timezone", place="europe/madrid"),
        say("ok"),
        call("set_timezone", place="Europe/Madrid"),
        say("ok"),
    )
    agent = chat(uow, model, None)  # no geocoder needed for a zone name
    await agent.handle_text(scene.user.id, "I'm in europe/madrid", "tg:1:1")
    assert tool_results(model) == ["Now on Madrid time (UTC+2), 06:00 there."]
    await agent.handle_text(scene.user.id, "yes Europe/Madrid", "tg:1:2")
    assert tool_results(model)[-1:] == ["Already on Madrid time (UTC+2), 06:00 there."]


async def test_the_chat_tool_asks_when_it_cannot_tell_where(scene: Scene, uow: UowFactory) -> None:
    model = scripted(
        call("set_timezone", place="Atlantis"),
        call("set_timezone"),
        say("Which city?"),
    )
    agent = chat(uow, model, scene.weather)
    reply = only(await agent.handle_text(scene.user.id, "I'm in Atlantis", "tg:1:1"))
    assert reply.text == "Which city?"
    first, second = [str(m.content) for m in model.seen[-1] if m.type == "tool"]
    assert first.startswith("Error: couldn't find a time zone for 'Atlantis'")
    assert second.startswith("Error: say where the user is")
    assert (await scene.now()).timezone == HOME


async def test_the_chat_tool_cannot_move_another_user(scene: Scene, uow: UowFactory) -> None:
    other = await person(uow, 5151)
    model = scripted(call("set_timezone", place="Madrid", user_id=str(other.id)), say("ok"))
    await chat(uow, model, scene.weather).handle_text(scene.user.id, "I'm in Madrid", "tg:1:1")
    assert (await scene.now()).timezone == MADRID
    assert (await scene.now(other)).timezone == HOME


# --- the web API ------------------------------------------------------------------------------


async def owner_row(world: World, telegram_id: int = OWNER) -> Any:
    async with world.engine.connect() as db:
        return (
            await db.execute(select(users).where(users.c.telegram_user_id == telegram_id))
        ).one()


async def queued_texts(world: World) -> list[str]:
    async with world.engine.connect() as db:
        rows = await db.execute(select(jobs.c.payload).where(jobs.c.kind == TELEGRAM_SEND))
        payloads: list[dict[str, Any]] = list(rows.scalars())
        return [p["text"] for p in payloads]


async def test_me_tells_the_current_and_home_zone(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    user = (await owner.get("/api/me")).json()["user"]
    assert user["timezone"] == user["home_timezone"] == "UTC"
    assert (user["timezone_source"], user["timezone_set_at"]) == ("home", None)


async def test_the_phone_reports_its_zone(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    first = await owner.send("POST", "/api/me/timezone", {"timezone": MADRID, "source": "phone"})
    assert first.status_code == 200
    set_at = first.json()["timezone_set_at"]
    assert first.json() == {
        "timezone": MADRID,
        "home_timezone": "UTC",
        "timezone_source": "phone",
        "timezone_set_at": set_at,
        "changed": True,
    }
    assert set_at is not None
    me = (await owner.get("/api/me")).json()["user"]
    assert (me["timezone"], me["home_timezone"], me["timezone_source"]) == (MADRID, "UTC", "phone")
    assert await queued_texts(world) == ["🕑 Switched to Madrid time (UTC+2)."]

    # The same zone again refreshes the time and tells nobody.
    world.clock.now = hours(2)
    again = await owner.send("POST", "/api/me/timezone", {"timezone": MADRID, "source": "phone"})
    assert again.json()["changed"] is False and again.json()["timezone_set_at"] != set_at
    assert len(await queued_texts(world)) == 1


async def test_picking_a_zone_in_settings_counts_as_saying_so(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    picked = await owner.send("POST", "/api/me/timezone", {"timezone": TOKYO, "source": "manual"})
    assert picked.json()["timezone_source"] == "chat" and picked.json()["changed"] is True
    assert await queued_texts(world) == []  # they just did it themselves
    back = await owner.send("POST", "/api/me/timezone/home")
    assert back.status_code == 200
    assert back.json() | {"timezone_set_at": None} == {
        "timezone": "UTC",
        "home_timezone": "UTC",
        "timezone_source": "home",
        "timezone_set_at": None,
        "changed": True,
    }
    assert (await owner.send("POST", "/api/me/timezone/home")).json()["changed"] is False


async def test_a_zone_that_does_not_exist_is_422_and_changes_nothing(world: World) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    for body in (
        {"timezone": "Mars/Olympus", "source": "phone"},
        {"timezone": "", "source": "manual"},
        {"timezone": "../etc/passwd", "source": "phone"},
        {"timezone": MADRID, "source": "trip"},
        {"timezone": MADRID},
    ):
        assert (await owner.send("POST", "/api/me/timezone", body)).status_code == 422, body
    assert (await owner_row(world)).timezone == "UTC"
    assert await queued_texts(world) == []


async def test_the_zone_endpoints_need_a_signed_in_user_and_a_csrf_token(world: World) -> None:
    stranger = world.browser()
    body = {"timezone": MADRID, "source": "phone"}
    assert (await stranger.send("POST", "/api/me/timezone", body)).status_code == 401
    assert (await stranger.send("POST", "/api/me/timezone/home")).status_code == 401
    owner = world.browser()
    await owner.login(OWNER)
    bad = {"X-CSRF-Token": "no"}
    assert (await owner.send("POST", "/api/me/timezone", body, **bad)).status_code == 403
    assert (await owner.send("POST", "/api/me/timezone/home", None, **bad)).status_code == 403
    assert (await owner_row(world)).timezone == "UTC"


async def test_one_users_zone_report_never_moves_another(world: World) -> None:
    owner, member = world.browser(), world.browser()
    await owner.login(OWNER)
    invite = (await owner.send("POST", "/api/invites")).json()["url"].rsplit("/", 1)[-1]
    await member.login(MEMBER, invite)
    await owner.send("POST", "/api/me/timezone", {"timezone": MADRID, "source": "phone"})
    assert (await member.get("/api/me")).json()["user"]["timezone"] == "UTC"
    assert (await owner_row(world, MEMBER)).timezone == "UTC"
    await member.send("POST", "/api/me/timezone", {"timezone": TOKYO, "source": "manual"})
    assert (await owner.get("/api/me")).json()["user"]["timezone"] == MADRID
