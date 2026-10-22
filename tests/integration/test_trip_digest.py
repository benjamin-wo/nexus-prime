"""The owner's Telegram summary of what other people changed in a shared trip: one
message per trip every 30 minutes at most, only for others' edits, only when the owner
wants it, and only what changed since the last one. Every name here is made up."""

import asyncio
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import trip_access as access_cases
from nexus.application import trips as trip_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.domain.ledger import User
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import jobs
from nexus.jobs.handlers import build_handlers
from nexus.jobs.runner import JobRunner
from tests.fakes import NOW, FakeRates, FakeTelegram
from tests.integration import test_shared_trips, test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import person
from tests.integration.test_jobs_budgets import Clock
from tests.integration.test_trips import draft

pytestmark = pytest.mark.integration

world = test_web_api.world
shared = test_shared_trips.shared

ORIGIN = "https://nexus.example.com"
DIGEST = access_cases.DIGEST_JOB
HALF_HOUR = timedelta(minutes=30)


class Trip:
    """An owner with a trip and two people on it, and a way to make them edit."""

    def __init__(self, uow: UowFactory, owner: User, sam: User, alex: User, trip_id: Any) -> None:
        self.uow = uow
        self.owner = owner
        self.sam = sam
        self.alex = alex
        self.id = trip_id

    async def edit(self, who: User, summary: str, at: Any) -> None:
        opened = await access_cases.open_trip(self.uow(), who, self.id)
        await access_cases.record(self.uow(), opened.access, summary, now=at)


@pytest.fixture
async def trip(uow: UowFactory) -> Trip:
    owner = await person(uow, 4242)
    sam = await person(uow, 4343)
    alex = await person(uow, 4444)
    made = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    async with uow() as tx:
        await tx.ledger.set_display_name(sam.id, "Sam")
        await tx.ledger.set_display_name(alex.id, "Alex T.")
        await tx.trips.add_member(owner.id, made.id, sam.id, None, NOW)
        await tx.trips.add_member(owner.id, made.id, alex.id, None, NOW)
        await tx.commit()
    return Trip(uow, owner, sam, alex, made.id)


async def rows(engine: AsyncEngine, kind: str) -> list[Any]:
    async with engine.connect() as db:
        return list(await db.execute(select(jobs).where(jobs.c.kind == kind).order_by(jobs.c.id)))


def runner(engine: AsyncEngine, uow: UowFactory, clock: Clock) -> tuple[JobRunner, FakeTelegram]:
    telegram = FakeTelegram()
    handlers = build_handlers(uow, telegram, FakeRates(), clock, origin=ORIGIN)
    return JobRunner(engine, handlers, clock=clock), telegram


# --- queuing ------------------------------------------------------------------------------


async def test_a_members_edit_queues_one_summary_half_an_hour_on(
    engine: AsyncEngine, trip: Trip
) -> None:
    await trip.edit(trip.sam, "added Dinner at Sushi Ten", NOW)
    (job,) = await rows(engine, DIGEST)
    assert job.run_at == NOW + HALF_HOUR
    assert job.payload == {"user_id": str(trip.owner.id), "trip_id": str(trip.id)}


async def test_several_edits_within_the_half_hour_make_one_message(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    await trip.edit(trip.sam, "added Dinner at Sushi Ten", NOW)
    await trip.edit(trip.alex, "moved Senso-ji to Day 2", NOW + timedelta(minutes=10))
    await trip.edit(trip.sam, "changed the notes", NOW + timedelta(minutes=29))
    assert len(await rows(engine, DIGEST)) == 1

    clock = Clock(NOW + HALF_HOUR)
    jobs_runner, telegram = runner(engine, uow, clock)
    await jobs_runner.tick()  # the summary job queues the message
    await jobs_runner.tick()  # which goes out
    (sent,) = telegram.sent
    assert sent.chat_id == 4242
    assert sent.text == (
        "Sam and Alex T. changed Tokyo: added Dinner at Sushi Ten, moved Senso-ji to Day 2, "
        "changed the notes"
    )
    (row,) = sent.buttons or []
    assert [(b.label, b.data) for b in row] == [
        ("Open the trip", f"url:{ORIGIN}/travel/trips/{trip.id}")
    ]
    assert len(await rows(engine, TELEGRAM_SEND)) == 1


async def test_the_owners_own_edits_tell_no_one(engine: AsyncEngine, trip: Trip) -> None:
    await trip.edit(trip.owner, "added Dinner at Sushi Ten", NOW)
    assert await rows(engine, DIGEST) == []
    # ...but they are still in the trip's activity.
    feed = await access_cases.activity(trip.uow(), trip.owner, trip.id)
    assert [a.summary for a in feed] == ["added Dinner at Sushi Ten"]


async def test_the_owners_edits_are_not_in_a_summary_of_others(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    await trip.edit(trip.owner, "changed the packing list", NOW)
    await trip.edit(trip.sam, "added Lunch", NOW + timedelta(minutes=1))
    clock = Clock(NOW + HALF_HOUR + timedelta(minutes=1))
    jobs_runner, telegram = runner(engine, uow, clock)
    await jobs_runner.tick()
    await jobs_runner.tick()
    assert [s.text for s in telegram.sent] == ["Sam changed Tokyo: added Lunch"]


async def test_a_trip_nobody_shares_queues_nothing(engine: AsyncEngine, uow: UowFactory) -> None:
    owner = await person(uow, 4242)
    made = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    opened = await access_cases.open_trip(uow(), owner, made.id)
    await access_cases.record(uow(), opened.access, "added Lunch", now=NOW)
    assert await rows(engine, DIGEST) == []


# --- the job ------------------------------------------------------------------------------


async def test_the_setting_off_sends_nothing(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    async with uow() as tx:
        await tx.ledger.set_trip_activity_alerts(trip.owner.id, False)
        await tx.commit()
    await trip.edit(trip.sam, "added Lunch", NOW)
    clock = Clock(NOW + HALF_HOUR)
    jobs_runner, telegram = runner(engine, uow, clock)
    await jobs_runner.tick()
    await jobs_runner.tick()
    assert telegram.sent == [] and await rows(engine, TELEGRAM_SEND) == []

    # Turning it on later doesn't bring that edit back.
    async with uow() as tx:
        await tx.ledger.set_trip_activity_alerts(trip.owner.id, True)
        await tx.commit()
    clock.now = NOW + timedelta(hours=2)
    await trip.edit(trip.alex, "added Walk", clock.now)
    clock.now += HALF_HOUR
    await jobs_runner.tick()
    await jobs_runner.tick()
    assert [s.text for s in telegram.sent] == ["Alex T. changed Tokyo: added Walk"]


async def test_an_owner_with_no_telegram_chat_is_not_messaged(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    from nexus.application.users import RegisterUser, register_user

    owner = (
        await register_user(uow(), RegisterUser(telegram_user_id=5151, home_currency="SGD"))
    ).user
    assert owner.telegram_chat_id is None
    sam = await person(uow, 4343)
    made = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    async with uow() as tx:
        await tx.trips.add_member(owner.id, made.id, sam.id, None, NOW)
        await tx.commit()
    opened = await access_cases.open_trip(uow(), sam, made.id)
    await access_cases.record(uow(), opened.access, "added Lunch", now=NOW)
    clock = Clock(NOW + HALF_HOUR)
    jobs_runner, telegram = runner(engine, uow, clock)
    await jobs_runner.tick()
    await jobs_runner.tick()
    assert telegram.sent == [] and await rows(engine, TELEGRAM_SEND) == []


async def test_a_summary_covers_only_what_changed_since_the_last(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    clock = Clock(NOW)
    jobs_runner, telegram = runner(engine, uow, clock)
    await trip.edit(trip.sam, "added Lunch", NOW)
    clock.now = NOW + HALF_HOUR
    await jobs_runner.tick()
    await jobs_runner.tick()

    clock.now = NOW + timedelta(minutes=45)
    await trip.edit(trip.alex, "added Walk", clock.now)
    assert len(await rows(engine, DIGEST)) == 2  # a new window, a new job
    clock.now = NOW + timedelta(minutes=75)
    await jobs_runner.tick()
    await jobs_runner.tick()
    assert [s.text for s in telegram.sent] == [
        "Sam changed Tokyo: added Lunch",
        "Alex T. changed Tokyo: added Walk",
    ]
    # At least half an hour between the two messages.
    sends = await rows(engine, TELEGRAM_SEND)
    assert sends[1].run_at - sends[0].run_at >= HALF_HOUR


async def test_running_a_summary_twice_sends_it_once(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    await trip.edit(trip.sam, "added Lunch", NOW)
    later = NOW + HALF_HOUR
    first = await access_cases.send_digest(uow, trip.owner.id, trip.id, now=later, origin=None)
    again = await access_cases.send_digest(uow, trip.owner.id, trip.id, now=later, origin=None)
    assert (first, again) == (True, False)
    (send,) = await rows(engine, TELEGRAM_SEND)
    assert "buttons" not in send.payload  # no web address, no button
    assert (send.payload["kind"], send.payload["level"]) == ("trip_activity", "now")
    assert send.payload["link"] == f"/travel/trips/{trip.id}"


async def test_an_edit_during_the_job_starts_the_next_summary(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    await trip.edit(trip.sam, "added Lunch", NOW)
    ran = NOW + HALF_HOUR
    # Stamped a moment after the job's clock, as a slow request would be.
    await trip.edit(trip.alex, "added Walk", ran + timedelta(seconds=1))
    await access_cases.send_digest(uow, trip.owner.id, trip.id, now=ran, origin=None)
    texts = [r.payload["text"] for r in await rows(engine, TELEGRAM_SEND)]
    assert texts == ["Sam changed Tokyo: added Lunch"]
    (_, follow) = await rows(engine, DIGEST)
    assert follow.run_at == ran + HALF_HOUR
    await access_cases.send_digest(uow, trip.owner.id, trip.id, now=follow.run_at, origin=None)
    texts = [r.payload["text"] for r in await rows(engine, TELEGRAM_SEND)]
    assert texts[1] == "Alex T. changed Tokyo: added Walk"


async def test_a_trip_deleted_meanwhile_is_nothing_to_do(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    await trip.edit(trip.sam, "added Lunch", NOW)
    await trip_cases.delete_trip(uow(), trip.owner.id, trip.id)
    clock = Clock(NOW + HALF_HOUR)
    jobs_runner, telegram = runner(engine, uow, clock)
    await jobs_runner.tick()
    (job,) = await rows(engine, DIGEST)
    assert job.status == "done"
    assert telegram.sent == [] and await rows(engine, TELEGRAM_SEND) == []
    assert not await access_cases.send_digest(
        uow, trip.owner.id, uuid4(), now=NOW, origin=None
    )  # and one that never was


async def test_someone_removed_meanwhile_is_still_reported(
    engine: AsyncEngine, uow: UowFactory, trip: Trip
) -> None:
    await trip.edit(trip.sam, "added Lunch", NOW)
    await access_cases.remove_member(uow(), trip.owner, trip.id, trip.sam.id)
    clock = Clock(NOW + HALF_HOUR)
    jobs_runner, telegram = runner(engine, uow, clock)
    await jobs_runner.tick()
    await jobs_runner.tick()
    assert [s.text for s in telegram.sent] == ["Sam changed Tokyo: added Lunch"]


async def test_a_member_with_no_name_shows_as_someone(engine: AsyncEngine, uow: UowFactory) -> None:
    owner = await person(uow, 4242)
    nameless = await person(uow, 4343)
    made = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    async with uow() as tx:
        await tx.trips.add_member(owner.id, made.id, nameless.id, None, NOW)
        await tx.commit()
    opened = await access_cases.open_trip(uow(), nameless, made.id)
    await access_cases.record(uow(), opened.access, "changed the notes", now=NOW)
    await access_cases.send_digest(uow, owner.id, made.id, now=NOW + HALF_HOUR, origin=None)
    (send,) = await rows(engine, TELEGRAM_SEND)
    assert send.payload["text"] == "Someone changed Tokyo: changed the notes"


# --- the web ------------------------------------------------------------------------------


async def test_the_setting_is_on_by_default_and_can_be_changed(
    shared: test_shared_trips.Shared,
) -> None:
    owner = shared.owner
    assert (await owner.get("/api/trip-alerts")).json() == {"enabled": True}
    off = await owner.send("PUT", "/api/trip-alerts", {"enabled": False})
    assert off.status_code == 200 and off.json() == {"enabled": False}
    assert (await owner.get("/api/trip-alerts")).json() == {"enabled": False}
    # It is each person's own.
    assert (await shared.member.get("/api/trip-alerts")).json() == {"enabled": True}
    back = await owner.send("PUT", "/api/trip-alerts", {"enabled": True})
    assert back.json() == {"enabled": True}
    assert (await owner.send("PUT", "/api/trip-alerts", {})).status_code == 422
    assert (
        await shared.outsider.send("PUT", "/api/trip-alerts", {"enabled": False})
    ).status_code == 200


async def test_a_members_edit_on_the_web_queues_a_summary_and_the_owners_does_not(
    shared: test_shared_trips.Shared,
) -> None:
    async def digests() -> int:
        async with shared.world.engine.connect() as db:
            return len(list(await db.execute(select(jobs).where(jobs.c.kind == DIGEST))))

    notes = f"{shared.path}/notes"
    assert (await shared.owner.send("PUT", notes, {"notes": "Mine"})).status_code == 200
    assert await digests() == 0
    assert (await shared.member.send("PUT", notes, {"notes": "Theirs"})).status_code == 200
    assert (await shared.member.send("PUT", notes, {"notes": "Theirs again"})).status_code == 200
    assert await digests() == 1


# --- the migration ------------------------------------------------------------------------


async def test_migration_0047_goes_up_and_down(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    owner = await person(uow, 4242)
    made = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    assert owner.trip_activity_alerts
    async with engine.begin() as db:
        await db.execute(
            text("UPDATE users SET trip_activity_alerts = false WHERE id = :id"),
            {"id": owner.id},
        )
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0046")

    async def columns(table: str) -> set[str]:
        async with engine.connect() as db:
            return set(
                (
                    await db.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = :t"
                        ),
                        {"t": table},
                    )
                )
                .scalars()
                .all()
            )

    assert "trip_activity_alerts" not in await columns("users")
    assert "activity_digest_at" not in await columns("trips")

    await upgrade(empty_database_url)
    async with engine.connect() as db:
        # Back on, for everyone, and the trip is still there with no summary yet.
        on: bool = (await db.execute(text("SELECT trip_activity_alerts FROM users"))).scalar_one()
        digest: object = (
            await db.execute(
                text("SELECT activity_digest_at FROM trips WHERE id = :id"), {"id": made.id}
            )
        ).scalar_one()
    assert on is True and digest is None
