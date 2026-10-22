"""The notification policy in the sender, the digest, the record and the daily cap, against a
real Postgres. The made-up user lives in Singapore (UTC+8), whose quiet hours are 23:00 to
08:00; every text here is made up."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

import pytest
from alembic import command
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import messaging as message_cases
from nexus.application import notifications as notify_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.users import RegisterUser, register_user
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import User
from nexus.domain.notifications import DAILY_CAP, Frequency, Kind, Level, Status
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import jobs, notifications, users
from nexus.jobs.handlers import NOTIFY_DIGEST, NOTIFY_PRUNE, SCHEDULES, build_handlers
from nexus.jobs.runner import Handler, JobRunner
from tests.fakes import FakeRates, FakeTelegram
from tests.integration.conftest import UowFactory, upgrade

pytestmark = pytest.mark.integration


def sgt(day: int, hour: int, minute: int = 0) -> datetime:
    """A time in Singapore in October 2026."""
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC) - timedelta(hours=8)


@dataclass
class Clock:
    now: datetime = datetime(2026, 10, 20, 4, tzinfo=UTC)  # noon in Singapore

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Scene:
    uow: UowFactory
    engine: AsyncEngine
    clock: Clock
    telegram: FakeTelegram
    user: User
    send: Handler
    handlers: dict[str, Handler]

    def payload(self, text: str, **extra: Any) -> dict[str, Any]:
        return {"user_id": str(self.user.id), "text": text, "kind": "bill_reminder", **extra} | (
            {} if "level" in extra else {"level": "now"}
        )

    async def say(self, text: str, **extra: Any) -> Any:
        return await self.send(self.payload(text, **extra))

    def told(self) -> list[str]:
        return [s.text for s in self.telegram.sent]

    async def rows(self, user: User | None = None) -> list[Any]:
        who = (user or self.user).id
        async with self.engine.connect() as db:
            found = await db.execute(
                select(notifications)
                .where(notifications.c.user_id == who)
                .order_by(notifications.c.created_at, notifications.c.text)
            )
            return list(found)

    async def jobs(self, kind: str = TELEGRAM_SEND) -> list[Any]:
        async with self.engine.connect() as db:
            return list(
                await db.execute(select(jobs).where(jobs.c.kind == kind).order_by(jobs.c.id))
            )

    async def digest(self) -> int:
        return await message_cases.send_digests(self.uow, now=self.clock())

    async def run_queued(self) -> None:
        """Run every queued send that is due, as the job runner would."""
        runner = JobRunner(self.engine, self.handlers, clock=self.clock)
        while await runner.tick():
            pass


async def make_user(uow: UowFactory, telegram_id: int = 4242, chat: bool = True) -> User:
    registration = await register_user(
        uow(),
        RegisterUser(
            telegram_user_id=telegram_id,
            telegram_chat_id=telegram_id if chat else None,
            home_currency="SGD",
            timezone="Asia/Singapore",
        ),
    )
    return registration.user


@pytest.fixture
async def scene(uow: UowFactory, engine: AsyncEngine) -> Scene:
    clock, telegram = Clock(), FakeTelegram()
    handlers = build_handlers(uow, telegram, FakeRates(), clock)
    user = await make_user(uow)
    return Scene(uow, engine, clock, telegram, user, handlers[TELEGRAM_SEND], handlers)


async def set_cap(scene: Scene, cap: int) -> None:
    await notify_cases.set_market(scene.uow(), scene.user.id, now=scene.clock(), daily_cap=cap)


# --- now ----------------------------------------------------------------------------------


async def test_a_message_that_is_now_goes_at_once_and_is_kept(scene: Scene) -> None:
    assert await scene.say("Reminder: Rent is due in 3 days.", link="/accounting") is None
    assert scene.told() == ["Reminder: Rent is due in 3 days."]
    (row,) = await scene.rows()
    assert (row.kind, row.level, row.status) == ("bill_reminder", "now", "sent")
    assert (row.link, row.has_buttons, row.sent_at) == ("/accounting", False, sgt(20, 12))
    assert (row.held_until, row.digest_id) == (None, None)


async def test_a_message_from_before_levels_is_now_and_the_old_flags_still_work(
    scene: Scene,
) -> None:
    scene.clock.now = sgt(20, 23, 30)
    plain = {"user_id": str(scene.user.id), "text": "queued last week"}
    assert await scene.send(plain) is None  # held, like any message in quiet hours
    assert scene.told() == []
    assert await scene.send({**plain, "text": "stop", "urgent": True}) is None
    assert await scene.send({**plain, "text": "summary", "anytime": True}) is None
    assert scene.told() == ["stop", "summary"]
    kinds = {r.text: (r.kind, r.level, r.status) for r in await scene.rows()}
    assert kinds == {
        "queued last week": ("message", "now", "held"),
        "stop": ("message", "urgent", "sent"),
        "summary": ("daily_summary", "now", "sent"),
    }


async def test_a_message_that_is_now_waits_out_quiet_hours_for_the_morning_digest(
    scene: Scene,
) -> None:
    scene.clock.now = sgt(20, 23, 30)
    assert await scene.say("You've used 100% of Food.") is None  # not deferred: held, recorded
    assert scene.told() == []
    (row,) = await scene.rows()
    assert (row.status, row.held_until, row.sent_at) == ("held", sgt(21, 8), None)
    assert await scene.jobs() == []  # no follow-up: it has no buttons


async def test_a_message_with_buttons_held_in_quiet_hours_is_sent_alone_at_their_end(
    scene: Scene,
) -> None:
    scene.clock.now = sgt(20, 23, 30)
    buttons = [[{"label": "Mark paid", "data": "bill:paid:1"}]]
    assert await scene.say("Reminder: Rent is due tomorrow.", buttons=buttons) is None
    (row,) = await scene.rows()
    assert (row.status, row.has_buttons, row.held_until) == ("held", True, sgt(21, 8))
    (follow,) = await scene.jobs()
    assert follow.run_at == sgt(21, 8) and follow.payload["buttons"] == buttons
    assert follow.payload["notification_id"] == str(row.id)
    # The digest never takes it, however late.
    scene.clock.now = sgt(21, 8)
    assert await scene.digest() == 0 and scene.told() == []
    await scene.run_queued()
    [sent] = scene.telegram.sent
    assert sent.text == "Reminder: Rent is due tomorrow."
    assert [[b.data for b in r] for r in sent.buttons or []] == [["bill:paid:1"]]
    (row,) = await scene.rows()  # the same record, now sent
    assert (row.status, row.sent_at, row.held_until) == ("sent", sgt(21, 8), None)
    await scene.send(follow.payload)  # run again by mistake: nothing more is sent
    assert len(scene.telegram.sent) == 1 and len(await scene.rows()) == 1


async def test_urgent_ignores_quiet_hours_and_the_cap(scene: Scene) -> None:
    await set_cap(scene, 3)
    scene.clock.now = sgt(20, 23, 45)
    assert await scene.say("🛑 ACME hit your stop.", level="urgent", kind="plan_event") is None
    assert scene.told() == ["🛑 ACME hit your stop."]
    scene.clock.now = sgt(21, 9)
    for n in range(3):
        await scene.say(f"urgent {n}", level="urgent")
    for n in range(3):
        await scene.say(f"now {n}")
    assert len(scene.told()) == 7  # three urgent ones didn't count toward the cap of three
    assert {r.status for r in await scene.rows()} == {"sent"}


# --- the cap --------------------------------------------------------------------------------


async def test_the_default_cap_is_six_and_the_seventh_goes_in_the_evening_digest(
    scene: Scene,
) -> None:
    assert (await notify_cases.get_settings(scene.uow(), scene.user.id)).daily_cap == DAILY_CAP == 6
    for n in range(6):
        await scene.say(f"message {n}")
    assert len(scene.told()) == 6
    await scene.say("message 6")
    assert len(scene.told()) == 6
    last = (await scene.rows())[-1]
    assert (last.text, last.status, last.held_until) == ("message 6", "held", sgt(20, 19))


async def test_over_the_cap_a_message_with_buttons_is_still_sent_and_counted(scene: Scene) -> None:
    await set_cap(scene, 3)
    for n in range(3):
        await scene.say(f"message {n}")
    buttons = [[{"label": "Log it", "data": "email:log:1"}]]
    await scene.say("Fresh Mart, S$23.40. Log it?", buttons=buttons, kind="receipt_question")
    await scene.say("Another one?", buttons=buttons, kind="receipt_question")
    assert len(scene.told()) == 5
    await scene.say("no buttons")  # still over
    assert len(scene.told()) == 5
    sent = [r for r in await scene.rows() if r.status == "sent"]
    assert len(sent) == 5 and sum(r.has_buttons for r in sent) == 2


async def test_summaries_the_user_chose_are_not_counted_toward_the_cap(scene: Scene) -> None:
    await set_cap(scene, 3)
    await scene.say("🧾 Today", kind="daily_summary", anytime=True)
    await scene.say("📊 Portfolio +1.2%", kind="market_summary", anytime=True)
    await scene.say("🧾 Since 2pm", kind="transaction_update")
    await scene.say("🧾 Since 3pm", kind="transaction_update")
    for n in range(3):
        await scene.say(f"message {n}")
    await scene.say("message 3")  # the fourth counted one
    assert len(scene.told()) == 7 and "message 3" not in scene.told()


async def test_the_day_is_the_users_local_day(scene: Scene) -> None:
    """With no quiet hours, three messages at 23:50 fill the cap; at 00:10 it is a new day."""
    await notify_cases.set_market(
        scene.uow(),
        scene.user.id,
        now=scene.clock(),
        daily_cap=3,
        quiet_start=time(0),
        quiet_end=time(0),
    )
    scene.clock.now = sgt(20, 23, 40)
    for n in range(3):
        await scene.say(f"late {n}")
    scene.clock.now = sgt(20, 23, 59)
    await scene.say("one too many")
    assert scene.told() == ["late 0", "late 1", "late 2"]
    scene.clock.now = sgt(21, 0, 1)
    await scene.say("a new day")
    assert scene.told()[-1] == "a new day" and len(scene.told()) == 4
    # Yesterday's three don't count against today's.
    for n in range(2):
        await scene.say(f"early {n}")
    await scene.say("one too many today")
    assert len(scene.told()) == 6


async def test_each_users_cap_and_count_are_their_own(scene: Scene, uow: UowFactory) -> None:
    other = await make_user(uow, 5151)
    await set_cap(scene, 3)
    for n in range(3):
        await scene.say(f"message {n}")
    await scene.say("held")
    await scene.send({**scene.payload("for the other"), "user_id": str(other.id)})
    assert "for the other" in scene.told() and "held" not in scene.told()


# --- digest-level messages -----------------------------------------------------------------


async def test_a_digest_level_message_is_never_sent_alone(scene: Scene) -> None:
    await scene.say("📉 ACME -5.4% today", level="digest", kind="big_move")
    assert scene.told() == []
    (row,) = await scene.rows()
    assert (row.level, row.status, row.held_until) == ("digest", "held", sgt(20, 19))
    assert await scene.jobs() == []


async def test_a_digest_level_message_with_buttons_is_sent_alone_at_the_digest_time(
    scene: Scene,
) -> None:
    buttons = [
        [{"label": "Track it", "data": "sub:track:1"}, {"label": "No", "data": "sub:skip:1"}]
    ]
    await scene.say("🔁 Streamly has charged you…", level="digest", buttons=buttons)
    assert scene.told() == []
    (follow,) = await scene.jobs()
    assert follow.run_at == sgt(20, 19)
    scene.clock.now = sgt(20, 19)
    assert await scene.digest() == 0  # the digest doesn't fold it in
    await scene.run_queued()
    [sent] = scene.telegram.sent
    assert sent.text.startswith("🔁 Streamly") and len(sent.buttons or []) == 1
    (row,) = await scene.rows()
    assert (row.level, row.status, row.sent_at) == ("digest", "sent", sgt(20, 19))


# --- the digest -------------------------------------------------------------------------------


async def hold_overnight(scene: Scene) -> None:
    scene.clock.now = sgt(20, 23, 30)
    await scene.say("You've used 100% of Food.", kind="budget_alert")
    scene.clock.now = sgt(20, 23, 40)
    await scene.say("📉 ACME -5.4% today", level="digest", kind="big_move")
    scene.clock.now = sgt(21, 2)
    await scene.say("ACME plan refreshed: now Wait.", level="digest", kind="plan_refresh")


async def test_the_morning_digest_folds_the_held_messages_into_one(scene: Scene) -> None:
    await hold_overnight(scene)
    scene.clock.now = sgt(21, 7, 50)
    assert await scene.digest() == 0 and scene.told() == []  # quiet hours are not over
    scene.clock.now = sgt(21, 8)
    assert await scene.digest() == 1
    await scene.run_queued()
    assert scene.told() == [
        "While you were away:\n"
        "• You've used 100% of Food.\n"
        "• 📉 ACME -5.4% today\n"
        "• ACME plan refreshed: now Wait."
    ]
    rows = await scene.rows()
    assert {r.status for r in rows} == {"digested"}
    assert {r.sent_at for r in rows} == {sgt(21, 8)}
    assert len({r.digest_id for r in rows}) == 1 and rows[0].digest_id is not None
    assert {r.held_until for r in rows} == {None}


async def test_a_digest_is_not_made_twice(scene: Scene) -> None:
    await hold_overnight(scene)
    scene.clock.now = sgt(21, 8)
    made = await asyncio.gather(scene.digest(), scene.digest())  # two sweeps at once
    assert sorted(made) == [0, 1]
    assert await scene.digest() == 0
    scene.clock.now = sgt(21, 8, 30)
    assert await scene.digest() == 0
    await scene.run_queued()
    assert len(scene.telegram.sent) == 1
    # The digest's own job is keyed by its first item, so even a replay queues nothing more.
    (job,) = await scene.jobs()
    assert job.dedupe_key.startswith(f"digest:{scene.user.id}:")


async def test_messages_held_in_the_daytime_wait_for_the_evening_digest(scene: Scene) -> None:
    await scene.say("📉 ACME -5.4% today", level="digest", kind="big_move")
    scene.clock.now = sgt(20, 18, 59)
    assert await scene.digest() == 0
    scene.clock.now = sgt(20, 19)
    assert await scene.digest() == 1
    await scene.run_queued()
    assert scene.told() == ["While you were away:\n• 📉 ACME -5.4% today"]


async def test_a_digest_lists_twelve_and_marks_every_one_digested(scene: Scene) -> None:
    for n in range(15):
        scene.clock.now = sgt(20, 12, n)
        await scene.say(f"Thing {n}", level="digest", kind="big_move")
    scene.clock.now = sgt(20, 19)
    await scene.digest()
    await scene.run_queued()
    lines = scene.told()[0].split("\n")
    assert len(lines) == 14 and lines[-1] == "and 3 more — see Notifications on the web"
    assert {r.status for r in await scene.rows()} == {"digested"}


async def test_quiet_hours_changed_since_hold_the_digest_back(scene: Scene) -> None:
    await scene.say("📉 ACME -5.4% today", level="digest", kind="big_move")
    await notify_cases.set_market(
        scene.uow(), scene.user.id, now=scene.clock(), quiet_start=time(18), quiet_end=time(21)
    )
    scene.clock.now = sgt(20, 19)
    assert await scene.digest() == 0
    scene.clock.now = sgt(20, 21)
    assert await scene.digest() == 1


async def test_held_messages_of_someone_with_no_chat_are_dropped_not_sent(
    scene: Scene, uow: UowFactory
) -> None:
    other = await make_user(uow, 5151, chat=False)
    await scene.send({**scene.payload("nobody to tell"), "user_id": str(other.id)})
    (row,) = await scene.rows(other)
    assert (row.status, row.sent_at) == ("dropped", None) and scene.told() == []
    # Unlinked after a message was held for them.
    await scene.say("📉 ACME -5.4% today", level="digest", kind="big_move")
    async with scene.engine.begin() as db:
        await db.execute(
            update(users).where(users.c.id == scene.user.id).values(telegram_chat_id=None)
        )
    scene.clock.now = sgt(20, 19)
    assert await scene.digest() == 0
    (row,) = await scene.rows()
    assert (row.status, row.digest_id) == ("dropped", None) and scene.told() == []


async def test_the_digest_and_the_prune_run_from_the_job_schedule(scene: Scene) -> None:
    assert {s.kind for s in SCHEDULES} >= {NOTIFY_DIGEST, NOTIFY_PRUNE}
    await scene.say("📉 ACME -5.4% today", level="digest", kind="big_move")
    scene.clock.now = sgt(20, 19, 5)
    runner = JobRunner(
        scene.engine,
        scene.handlers,
        schedules=[s for s in SCHEDULES if s.kind == NOTIFY_DIGEST],
        clock=scene.clock,
    )
    while await runner.tick():
        pass
    assert scene.told() == ["While you were away:\n• 📉 ACME -5.4% today"]


# --- the record -------------------------------------------------------------------------------


async def test_the_record_is_kept_for_thirty_days(scene: Scene, uow: UowFactory) -> None:
    for days in (1, 29, 31, 45):
        scene.clock.now = sgt(20, 12) - timedelta(days=days)
        await scene.say(f"{days} days ago")
    scene.clock.now = sgt(20, 12)
    assert await message_cases.prune(uow, now=scene.clock()) == 2
    assert [r.text for r in await scene.rows()] == ["29 days ago", "1 days ago"]
    await scene.handlers[NOTIFY_PRUNE]({})
    assert len(await scene.rows()) == 2


async def test_the_users_history_is_theirs_alone_newest_first(
    scene: Scene, uow: UowFactory
) -> None:
    other = await make_user(uow, 5151)
    for n in range(3):
        scene.clock.now = sgt(20, 9 + n)
        await scene.say(f"mine {n}")
    await scene.send({**scene.payload("theirs"), "user_id": str(other.id)})
    scene.clock.now = sgt(20, 12)
    ours = await message_cases.history(uow(), scene.user.id, now=scene.clock())
    assert [n.text for n in ours] == ["mine 2", "mine 1", "mine 0"]
    assert [n.text for n in await message_cases.history(uow(), other.id, now=scene.clock())] == [
        "theirs"
    ]
    # Anything older than 30 days is out of the list even before the prune.
    scene.clock.now = sgt(20, 12) + timedelta(days=40)
    assert await message_cases.history(uow(), scene.user.id, now=scene.clock()) == []


# --- settings ---------------------------------------------------------------------------------


async def test_the_daily_cap_is_kept_and_checked(scene: Scene) -> None:
    await set_cap(scene, 12)
    assert (await notify_cases.get_settings(scene.uow(), scene.user.id)).daily_cap == 12
    await notify_cases.set_frequency(
        scene.uow(), scene.user.id, Frequency.HOURLY, now=scene.clock()
    )
    for bad in (2, 21, 0, 4.5, "lots"):
        with pytest.raises(InvalidInput):
            await set_cap(scene, bad)  # type: ignore[arg-type]
    assert (await notify_cases.get_settings(scene.uow(), scene.user.id)).daily_cap == 12


async def test_the_database_refuses_a_cap_outside_3_to_20(scene: Scene) -> None:
    await set_cap(scene, 5)
    for bad in (2, 21):
        with pytest.raises(Exception, match="daily_cap"):
            async with scene.engine.begin() as db:
                await db.execute(
                    text("UPDATE notification_settings SET daily_cap = :bad"), {"bad": bad}
                )


# --- the migration ------------------------------------------------------------------------------


async def test_migration_0053_keeps_settings_and_goes_down_and_up_again(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    user = await make_user(uow)
    await notify_cases.set_market(uow(), user.id, now=sgt(20, 12), quiet_start=time(22))
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0052")
    async with engine.connect() as db:
        tables: set[str] = set(
            (await db.execute(text("SELECT tablename FROM pg_tables"))).scalars()
        )
        columns: set[str] = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'notification_settings'"
                    )
                )
            ).scalars()
        )
    assert "notifications" not in tables and "daily_cap" not in columns
    await upgrade(empty_database_url)
    settings = await notify_cases.get_settings(uow(), user.id)
    assert settings.daily_cap == DAILY_CAP and settings.quiet_start == time(22)
    async with uow() as tx:  # the table is back and works
        assert await tx.notifications.recent(user.id, sgt(1, 0)) == []


def test_every_kind_and_level_the_record_allows_is_named() -> None:
    assert {level.value for level in Level} == {"urgent", "now", "digest"}
    assert {status.value for status in Status} == {"sent", "held", "digested", "dropped"}
    assert Kind.MESSAGE.value == "message" and len({k.value for k in Kind}) == len(Kind)
