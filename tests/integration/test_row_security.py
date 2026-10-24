"""Row-level security: Postgres refuses another user's rows even when a query forgets the
filter. The app's connections run as ``nexus_app`` (migration 0056) and each transaction
names its user in ``app.user_id``. Every name and figure here is made up."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexus.agent.graph import AgentDeps, AgentGraph
from nexus.agent.service import AgentService
from nexus.agent.skills import SkillLibrary
from nexus.agent.tools import build_tools
from nexus.application import trips as trip_cases
from nexus.application.acting import acting_as, current_user_id
from nexus.application.transactions import NewTransaction, log_transaction
from nexus.application.user_data import NOT_EXPORTED, SHARED, owned_tables
from nexus.domain.ledger import Direction, UserId
from nexus.domain.money import Money
from nexus.infra.db.uow import SqlUnitOfWork
from tests.fakes import NOW, say, scripted
from tests.integration.conftest import APP_ROLE, UowFactory
from tests.integration.test_email import person
from tests.integration.test_shared_trips import Shared, app_member, shared, sign_in
from tests.integration.test_trips import draft
from tests.integration.test_web_api import OWNER, World, world

pytestmark = pytest.mark.integration

# Owned by a user but left without row security, each for a reason (see migration 0056 and
# docs/OPERATIONS.md "Row-level security").
EXCEPTIONS = {"jobs", "trip_invites"}
# Fixtures other test modules define (used here by name).
fixtures = (shared, world)


@asynccontextmanager
async def acting(engine: AsyncEngine, user: UserId | None) -> AsyncIterator[AsyncConnection]:
    """One transaction as the app role, naming ``user`` (or nobody), rolled back at the end."""
    async with engine.connect() as db:
        async with db.begin() as transaction:
            if user is not None:
                await db.execute(
                    text("SELECT set_config('app.user_id', :id, true)"), {"id": str(user)}
                )
            yield db
            await transaction.rollback()


async def count(db: AsyncConnection, sql: str, **params: Any) -> int:
    return int((await db.execute(text(sql), params)).scalar_one())


async def spend(uow: UowFactory, user: UserId, amount: str) -> UUID:
    tx = await log_transaction(
        uow(), user, NewTransaction(Direction.OUT, Money.of(amount, "SGD"), NOW)
    )
    return tx.id


# --- what is covered --------------------------------------------------------------------------


async def test_the_app_connects_as_the_restricted_role(
    engine: AsyncEngine, admin_engine: AsyncEngine
) -> None:
    async with engine.connect() as db:
        assert await count(db, "SELECT 1 WHERE current_user = :role", role=APP_ROLE) == 1
    async with admin_engine.connect() as db:  # what Alembic uses
        assert await count(db, "SELECT 1 WHERE current_user <> :role", role=APP_ROLE) == 1


async def test_every_user_owned_table_has_a_policy_and_nothing_else_does(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as db:
        enabled: set[str] = set(
            (
                await db.execute(
                    text(
                        "SELECT c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity"
                    )
                )
            ).scalars()
        )
        forced: list[str] = list(
            (
                await db.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity"))
            ).scalars()
        )
        policies = (
            await db.execute(
                text(
                    "SELECT tablename, cmd, qual, with_check FROM pg_policies "
                    "WHERE schemaname = 'public'"
                )
            )
        ).all()
    assert enabled == owned_tables() - EXCEPTIONS
    # One policy per table for every command, with a check as well as a filter; the few
    # tables a trip's other people may read have a read-only one besides.
    everything = [p for p in policies if p.cmd == "ALL"]
    assert sorted(p.tablename for p in everything) == sorted(enabled)
    assert all(p.qual and p.with_check for p in everything)
    reading = {p.tablename for p in policies if p.cmd == "SELECT"}
    assert reading == {"users", "trip_members", "trip_activity"}
    assert len(policies) == len(everything) + len(reading)
    assert not set(forced)  # the owner, who migrates and administers, is not held to them
    assert EXCEPTIONS <= set(NOT_EXPORTED)
    assert not set(SHARED) & enabled


async def test_the_app_role_cannot_change_the_schema_or_its_version(engine: AsyncEngine) -> None:
    async with engine.connect() as db:
        with pytest.raises(DBAPIError, match="permission denied"):
            await db.execute(text("UPDATE alembic_version SET version_num = '0001'"))
    async with engine.connect() as db:
        with pytest.raises(DBAPIError, match=r"must be owner|permission denied"):
            await db.execute(text("DROP TABLE transactions"))


# --- one user's rows --------------------------------------------------------------------------


async def test_an_unfiltered_query_returns_only_the_named_users_rows(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    mine = await spend(uow, alice, "5")
    await spend(uow, bob, "6")
    await spend(uow, bob, "7")
    async with acting(engine, alice) as db:
        rows = (await db.execute(text("SELECT id, user_id FROM transactions"))).all()
        assert [(r.id, r.user_id) for r in rows] == [(mine, alice)]
        assert set((await db.execute(text("SELECT id FROM users"))).scalars()) == {alice}
        for table in ("categories", "wallets", "salary_schedules", "chat_log"):
            sql = f"SELECT DISTINCT user_id FROM {table}"  # noqa: S608
            assert set((await db.execute(text(sql))).scalars()) <= {alice}, table
        assert await count(db, "SELECT count(*) FROM categories") > 0  # their own are there
    async with acting(engine, bob) as db:
        assert await count(db, "SELECT count(*) FROM transactions") == 2


async def test_a_row_for_another_user_is_refused_and_theirs_cannot_be_touched(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    theirs = await spend(uow, bob, "9")
    mine = await spend(uow, alice, "4")
    async with acting(engine, None) as db:
        category = (
            (await db.execute(text("SELECT id FROM categories WHERE user_id = :u"), {"u": bob}))
            .scalars()
            .first()
        )
    insert = text(
        "INSERT INTO transactions (id, user_id, direction, amount, currency, occurred_at, "
        "category_id, status, source, created_at, updated_at) VALUES (:id, :user, 'out', 1, "
        "'SGD', now(), :category, 'confirmed', 'manual', now(), now())"
    )
    async with acting(engine, alice) as db:
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(insert, {"id": uuid4(), "user": bob, "category": category})
    async with acting(engine, alice) as db:
        changed = await db.execute(
            text("UPDATE transactions SET notes = 'x' WHERE id = :t"), {"t": theirs}
        )
        assert changed.rowcount == 0
        gone = await db.execute(text("DELETE FROM transactions WHERE id = :t"), {"t": theirs})
        assert gone.rowcount == 0
    async with acting(engine, alice) as db:
        # Handing their own row to someone else is refused as well.
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.execute(
                text("UPDATE transactions SET user_id = :other WHERE id = :t"),
                {"other": bob, "t": mine},
            )


async def test_with_no_user_named_every_row_is_visible(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await spend(uow, alice, "1")
    await spend(uow, bob, "2")
    async with acting(engine, None) as db:  # a background job
        assert await count(db, "SELECT count(DISTINCT user_id) FROM transactions") == 2
        assert await count(db, "SELECT count(*) FROM users") == 2
    # A user named in one transaction is forgotten by the next on the same connection.
    async with engine.connect() as db:
        async with db.begin():
            await db.execute(
                text("SELECT set_config('app.user_id', :id, true)"), {"id": str(alice)}
            )
            assert await count(db, "SELECT count(DISTINCT user_id) FROM transactions") == 1
        async with db.begin():
            assert await count(db, "SELECT count(DISTINCT user_id) FROM transactions") == 2


async def test_a_unit_of_work_keeps_its_user_after_a_commit(
    uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    await spend(uow, alice, "1")
    await spend(uow, bob, "2")
    with acting_as(alice):
        async with uow() as tx:
            await tx.commit()
            # The next transaction still names Alice, so it never sees everyone's rows.
            seen = await tx.web._c.execute(text("SELECT count(DISTINCT user_id) FROM transactions"))
            assert seen.scalar_one() == 1


async def test_queued_jobs_are_not_held_back(
    engine: AsyncEngine, uow: UowFactory, alice: UserId, bob: UserId
) -> None:
    async with uow() as tx:
        await tx.jobs.enqueue("note", {"user_id": str(bob)}, dedupe_key="bob:1", run_at=NOW)
        await tx.commit()
    async with acting(engine, alice) as db:
        assert await count(db, "SELECT count(*) FROM jobs") == 1  # queued for someone else


# --- sessions and invites ---------------------------------------------------------------------


async def test_signing_in_with_an_invite_and_opening_a_session_work(world: World) -> None:
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    guest = await app_member(world, owner, 7101, "Pat")  # redeems an app invite
    me = await guest.get("/api/me")  # session lookup, before the user is known
    assert me.status_code == 200 and me.json()["user"]["telegram_user_id"] == 7101
    again, response = await sign_in(world, 7101, first="Pat")  # no invite needed now
    assert response.status_code == 200
    assert (await again.get("/api/me")).status_code == 200
    out = await guest.send("POST", "/api/auth/logout")
    assert out.status_code in {200, 204}
    assert (await guest.get("/api/me")).status_code == 401


async def test_a_signed_in_person_can_redeem_someone_elses_trip_invite(shared: Shared) -> None:
    other = await app_member(shared.world, shared.owner, 7202, "Kit")
    token = (await shared.invite())["token"]
    joined = await other.send("POST", f"/api/travel/invites/{token}/accept")
    assert joined.status_code == 200 and joined.json()["new"] is True
    assert (await other.get(shared.path)).status_code == 200


# --- trips shared with a member ---------------------------------------------------------------


async def refused(db: AsyncConnection, sql: str, **params: Any) -> None:
    """The statement is turned down by a policy (in a savepoint, so the transaction goes on)."""
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.begin_nested():
            await db.execute(text(sql), params)


ADD_BOOKING = (
    "INSERT INTO trip_bookings (id, user_id, trip_id, kind, title, details, created_at) "
    "VALUES (:id, :user, :trip, 'activity', 'Dinner', '{}', now())"
)
ADD_MEMBER = (
    "INSERT INTO trip_members (id, trip_id, owner_id, member_id, added_at) "
    "VALUES (:id, :trip, :owner, :member, now())"
)


async def test_a_member_sees_and_edits_the_trip_but_never_the_owners_ledger(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    owner = await person(uow, 4242)
    member = await person(uow, 4343)
    mate = await person(uow, 4545)
    outsider = await person(uow, 4444)
    trip = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    elsewhere = await trip_cases.create_trip(uow(), outsider, draft(destination="Oslo"), now=NOW)
    async with uow() as tx:
        await tx.trips.add_member(owner.id, trip.id, member.id, None, NOW)
        await tx.trips.add_member(owner.id, trip.id, mate.id, None, NOW)
        await tx.commit()
    await spend(uow, owner.id, "80")

    async with acting(engine, member.id) as db:
        assert await count(db, "SELECT count(*) FROM trips WHERE id = :t", t=trip.id) == 1
        # What the app lets a member do: change the owner's trip, add to it and say so, all
        # written with the owner's id.
        await db.execute(text(ADD_BOOKING), {"id": uuid4(), "user": owner.id, "trip": trip.id})
        assert (
            await count(db, "SELECT count(*) FROM trip_bookings WHERE trip_id = :t", t=trip.id) == 1
        )
        edited = await db.execute(
            text("UPDATE trips SET notes = 'Bring cash' WHERE id = :t"), {"t": trip.id}
        )
        assert edited.rowcount == 1
        await db.execute(
            text(
                "INSERT INTO trip_activity (id, trip_id, owner_id, actor_id, summary, at) "
                "VALUES (:id, :t, :owner, :me, 'added Dinner', now())"
            ),
            {"id": uuid4(), "t": trip.id, "owner": owner.id, "me": member.id},
        )
        # They read the owner and the others on the trip ...
        people: set[UUID] = set((await db.execute(text("SELECT id FROM users"))).scalars())
        assert people == {owner.id, member.id, mate.id}
        assert (
            await count(db, "SELECT count(*) FROM trip_members WHERE trip_id = :t", t=trip.id) == 2
        )
        assert await count(db, "SELECT count(*) FROM trip_activity") == 1
        # ... but not the owner's money, and change none of them.
        assert await count(db, "SELECT count(*) FROM transactions") == 0
        assert await count(db, "SELECT count(*) FROM wallets WHERE user_id = :o", o=owner.id) == 0
        renamed = await db.execute(
            text("UPDATE users SET display_name = 'x' WHERE id = :o"), {"o": owner.id}
        )
        assert renamed.rowcount == 0
        removed = await db.execute(
            text("DELETE FROM trip_members WHERE member_id = :m"), {"m": mate.id}
        )
        assert removed.rowcount == 0
        # Not onto a trip they are not on, and not someone else onto this one.
        await refused(db, ADD_BOOKING, id=uuid4(), user=outsider.id, trip=elsewhere.id)
        await refused(db, ADD_MEMBER, id=uuid4(), trip=trip.id, owner=owner.id, member=outsider.id)

    async with acting(engine, outsider.id) as db:
        assert await count(db, "SELECT count(*) FROM trips WHERE id = :t", t=trip.id) == 0
        assert (
            await count(db, "SELECT count(*) FROM trip_bookings WHERE trip_id = :t", t=trip.id) == 0
        )
        assert (
            await count(db, "SELECT count(*) FROM trip_members WHERE trip_id = :t", t=trip.id) == 0
        )
        assert await count(db, "SELECT count(*) FROM users") == 1
        await refused(db, ADD_BOOKING, id=uuid4(), user=owner.id, trip=trip.id)

    async with acting(engine, owner.id) as db:
        assert await count(db, "SELECT count(*) FROM trips") == 1
        assert await count(db, "SELECT count(*) FROM trip_members") == 2
        assert await count(db, "SELECT count(*) FROM transactions") == 1
        removed = await db.execute(
            text("DELETE FROM trip_members WHERE member_id = :m"), {"m": mate.id}
        )
        assert removed.rowcount == 1  # the owner takes someone off their trip


async def test_a_trips_money_tables_are_the_owners_alone(
    engine: AsyncEngine, uow: UowFactory
) -> None:
    owner = await person(uow, 4242)
    member = await person(uow, 4343)
    trip = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    async with uow() as tx:
        await tx.trips.add_member(owner.id, trip.id, member.id, None, NOW)
        await tx.commit()
    async with engine.begin() as db:  # no one named: the owner's own paid-by-others entry
        await db.execute(
            text(
                "INSERT INTO trip_paid_by_others (id, user_id, trip_id, person, amount, currency, "
                "paid_on, created_at) "
                "VALUES (:id, :o, :t, 'Ann', :amount, 'JPY', current_date, now())"
            ),
            {"id": uuid4(), "o": owner.id, "t": trip.id, "amount": Decimal("460")},
        )
    async with acting(engine, member.id) as db:
        assert await count(db, "SELECT count(*) FROM trip_paid_by_others") == 0
        assert await count(db, "SELECT count(*) FROM trip_links") == 0
    async with acting(engine, owner.id) as db:
        assert await count(db, "SELECT count(*) FROM trip_paid_by_others") == 1


# --- the app names the user -------------------------------------------------------------------


class Spy:
    """Records, for every unit of work opened, who it named to the database."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.seen: list[str] = []
        original = SqlUnitOfWork.__aenter__
        seen = self.seen

        async def entered(uow: SqlUnitOfWork) -> SqlUnitOfWork:
            await original(uow)
            connection = uow._connection
            assert connection is not None
            named = await connection.execute(text("SELECT current_setting('app.user_id', true)"))
            seen.append(named.scalar_one() or "")
            return uow

        monkeypatch.setattr(SqlUnitOfWork, "__aenter__", entered)


async def test_a_web_request_names_its_user_after_its_session_is_checked(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    async with world.engine.connect() as db:  # no one named: sees every user
        me: UUID = (
            await db.execute(text("SELECT id FROM users WHERE telegram_user_id = :t"), {"t": OWNER})
        ).scalar_one()
    spy = Spy(monkeypatch)
    assert (await owner.get("/api/transactions")).status_code == 200
    assert spy.seen[0] == ""  # the session lookup happens before anyone is known
    assert spy.seen[1:] and set(spy.seen[1:]) == {str(me)}
    # Nothing carries over to the next request, or to code that runs outside any.
    assert current_user_id() is None
    spy.seen.clear()
    assert (await world.browser().get("/api/transactions")).status_code == 401
    assert spy.seen == []


async def test_a_chat_turn_names_its_user(
    uow: UowFactory, alice: UserId, bob: UserId, monkeypatch: pytest.MonkeyPatch
) -> None:
    skills = SkillLibrary.load()

    async def health() -> str:
        return "ok"

    graph = AgentGraph(
        AgentDeps(
            uow,
            build_tools(skills.body),
            scripted(say("Hi.")),
            (),
            skills.index(),
            health,
            lambda: NOW,
        )
    ).compile(InMemorySaver())
    service = AgentService(graph, uow, None, lambda: NOW)
    spy = Spy(monkeypatch)
    await service.handle_text(alice, "hello", "tg:1:1")
    assert spy.seen and set(spy.seen) == {str(alice)}
    spy.seen.clear()
    await service.handle_text(bob, "hello", "tg:1:2")
    assert spy.seen and set(spy.seen) == {str(bob)}
    assert current_user_id() is None  # the turn ended
    async with uow():  # a job on the same task names no one
        pass
    assert spy.seen[-1] == ""


def test_acting_as_puts_back_whoever_it_found() -> None:
    first, second = UserId(uuid4()), UserId(uuid4())
    assert current_user_id() is None
    with acting_as(first):
        with acting_as(second, keep=True):  # the signed-in person stays
            assert current_user_id() == first
        with acting_as(second):
            assert current_user_id() == second
        with acting_as(None):
            assert current_user_id() is None
        assert current_user_id() == first
    assert current_user_id() is None
