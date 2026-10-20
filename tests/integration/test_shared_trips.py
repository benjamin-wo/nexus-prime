"""Shared trips: invited people edit a trip's plan and never see its money. Covers the
database (migration 0046, who may open which trip), the invites, signing in with a trip
invite, guests being shut out of everything else, and the activity feed. Every name
and figure here is made up."""

import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.routing import APIRoute
from httpx import Response
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import bookings as booking_cases
from nexus.application import trip_access as access_cases
from nexus.application import trips as trip_cases
from nexus.application.users import RegisterUser, register_user
from nexus.channels.web import api as web_api
from nexus.channels.web import email_api, investments_api, ops_api, travel_api
from nexus.channels.web.security import authenticated, signed_in
from nexus.channels.web.telegram_login import sign_for_tests, sign_webapp_for_tests
from nexus.domain.access import token_hash
from nexus.domain.errors import Forbidden, NotFound
from nexus.domain.ledger import Role, UserId
from nexus.domain.trip_access import TripRole
from nexus.infra.db.migrations import alembic_config
from nexus.infra.db.tables import trip_invites, users
from nexus.infra.db.uow import SqlUnitOfWork
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory, upgrade
from tests.integration.test_email import person
from tests.integration.test_trips import draft
from tests.integration.test_web_api import (
    MEMBER,
    ORIGIN,
    OWNER,
    TOKEN,
    Browser,
    World,
)

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

PEER, OUTSIDER, GUEST = 811, 822, 833
MONEY_MESSAGE = "only the trip's owner can do that"
GUEST_MESSAGE = "guests can only open trips shared with them"
UNKNOWN = "00000000-0000-4000-8000-000000000000"
TRIP = {
    "destination": "Tokyo",
    "start": "2026-12-10",
    "end": "2026-12-18",
    "currency": "JPY",
    "budget": "2000",
    "set_aside": "100",
    "companions": ["Ann"],
    "planned": {"Dining Out": "600"},
    "notes": "Bring cash",
}
DINNER = {
    "kind": "activity",
    "name": "Dinner at Sushi Ten",
    "day": "2026-12-12",
    "at": "19:00",
    "reference": "R-1",
}


# --- people ---------------------------------------------------------------------------------


async def sign_in(
    world: World,
    telegram_id: int,
    *,
    first: str = "Sam",
    last: str | None = None,
    invite: str | None = None,
    trip_invite: str | None = None,
) -> tuple[Browser, Response]:
    """Signs in with Telegram, with a name and the invites given."""
    browser = world.browser()
    fields: dict[str, Any] = {
        "id": telegram_id,
        "first_name": first,
        "auth_date": int(world.clock.now.timestamp()),
    }
    if last:
        fields["last_name"] = last
    body: dict[str, Any] = {"telegram": sign_for_tests(fields, TOKEN)}
    if invite:
        body["invite"] = invite
    if trip_invite:
        body["trip_invite"] = trip_invite
    response = await browser.client.post(
        "/api/auth/telegram", json=body, headers={"Origin": ORIGIN}
    )
    if response.status_code == 200:
        browser.csrf = response.json()["csrf_token"]
    return browser, response


async def app_member(world: World, owner: Browser, telegram_id: int, first: str) -> Browser:
    """Someone the app's owner invited: an ordinary user with web access."""
    token = (await owner.send("POST", "/api/invites")).json()["url"].rsplit("/", 1)[-1]
    browser, response = await sign_in(world, telegram_id, first=first, invite=token)
    assert response.status_code == 200, response.text
    return browser


@dataclass
class Shared:
    world: World
    owner: Browser
    member: Browser  # an ordinary user, added to the trip
    outsider: Browser  # an ordinary user with no part in it
    trip: str  # the trip's id
    path: str  # /api/travel/trips/<id>

    async def invite(self) -> dict[str, Any]:
        made = await self.owner.send("POST", f"{self.path}/invites")
        assert made.status_code == 201, made.text
        body: dict[str, Any] = made.json()
        return body

    async def add_dinner(self) -> dict[str, Any]:
        made = await self.owner.send("POST", f"{self.path}/bookings", {**DINNER, "cost": "20"})
        assert made.status_code == 201, made.text
        body: dict[str, Any] = made.json()
        return body


async def make_trip(owner: Browser, **changes: Any) -> str:
    made = await owner.send("POST", "/api/travel/trips", {**TRIP, **changes})
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


@pytest.fixture
async def shared(world: World) -> Shared:
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    member = await app_member(world, owner, PEER, "Sam")
    outsider = await app_member(world, owner, OUTSIDER, "Zed")
    trip = await make_trip(owner)
    path = f"/api/travel/trips/{trip}"
    ours = Shared(world, owner, member, outsider, trip, path)
    token = (await ours.invite())["token"]
    joined = await member.send("POST", f"/api/travel/invites/{token}/accept")
    assert joined.status_code == 200 and joined.json() == {
        "trip_id": trip,
        "new": True,
        "own": False,
    }
    return ours


# --- the database ---------------------------------------------------------------------------


async def test_migration_0046_goes_up_and_down(
    engine: AsyncEngine, empty_database_url: str, uow: UowFactory
) -> None:
    owner = await person(uow, 4242)
    friend = await person(uow, 4343)
    trip = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    async with uow() as tx:
        await tx.ledger.set_display_name(friend.id, "Sam")
        await tx.trips.add_member(owner.id, trip.id, friend.id, None, NOW)
        await tx.commit()
    async with engine.connect() as db:
        assert (await db.execute(text("SELECT count(*) FROM trip_members"))).scalar_one() == 1

    # A guest account is a user with the role guest and web access.
    guest = await access_cases_guest(uow)
    await engine.dispose()
    config = alembic_config(empty_database_url)
    config.attributes["configure_logger"] = False
    await asyncio.to_thread(command.downgrade, config, "0045")
    async with engine.connect() as db:
        tables: set[str] = set(
            (await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")))
            .scalars()
            .all()
        )
        columns: set[str] = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'users'"
                    )
                )
            )
            .scalars()
            .all()
        )
        left = (
            await db.execute(
                text("SELECT role, web_access_granted_at FROM users WHERE id = :id"), {"id": guest}
            )
        ).one()
        sessions: int = (
            await db.execute(
                text("SELECT count(*) FROM web_sessions WHERE user_id = :id"), {"id": guest}
            )
        ).scalar_one()
    assert not tables & {"trip_members", "trip_invites", "trip_activity"}
    assert "display_name" not in columns
    # The guest stays as an ordinary member with no way in.
    assert (left.role, left.web_access_granted_at, sessions) == ("member", None, 0)

    await upgrade(empty_database_url)
    async with engine.connect() as db:
        assert (await db.execute(text("SELECT count(*) FROM trip_members"))).scalar_one() == 0
        assert (await db.execute(text("SELECT count(*) FROM trips"))).scalar_one() == 1
        await db.execute(text("SELECT display_name FROM users LIMIT 1"))


async def access_cases_guest(uow: UowFactory) -> UserId:
    """A guest account with a session, as signing in with a trip invite leaves one."""
    from nexus.application.users import RegisterUser, register_user
    from nexus.domain.access import Session

    registration = await register_user(
        uow(), RegisterUser(telegram_user_id=9001, home_currency="SGD", role=Role.GUEST)
    )
    guest = registration.user
    async with uow() as tx:
        await tx.ledger.grant_web_access(guest.id, NOW)
        await tx.ledger.insert_session(
            Session(token_hash("made-up-session"), guest.id, "csrf", NOW, NOW + timedelta(days=1))
        )
        await tx.commit()
    return guest.id


async def test_who_may_open_a_trip(uow: UowFactory, engine: AsyncEngine) -> None:
    owner = await person(uow, 4242)
    member = await person(uow, 4343)
    outsider = await person(uow, 4444)
    trip = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    other = await trip_cases.create_trip(uow(), outsider, draft(destination="Elsewhere"), now=NOW)
    loose = await booking_cases.add_manual(
        uow(),
        owner.id,
        trip.id,
        {"kind": "activity", "name": "Walk", "day": "2027-01-11"},
        None,
        now=NOW,
    )
    async with uow() as tx:
        assert await tx.trips.add_member(owner.id, trip.id, member.id, None, NOW)
        assert not await tx.trips.add_member(owner.id, trip.id, member.id, None, NOW)  # once
        await tx.commit()

    async with uow() as tx:
        mine = await tx.trips.trip_access(owner.id, trip.id)
        theirs = await tx.trips.trip_access(member.id, trip.id)
        assert mine is not None and mine.role is TripRole.OWNER and mine.owner_id == owner.id
        assert theirs is not None and theirs.role is TripRole.MEMBER and theirs.owner_id == owner.id
        assert await tx.trips.trip_access(outsider.id, trip.id) is None
        assert await tx.trips.trip_access(member.id, other.id) is None  # a member of one only
        assert await tx.trips.trip_access(owner.id, uuid4()) is None  # no such trip
        # A booking is reached through its trip.
        assert (await tx.trips.booking_access(member.id, loose.id)) == theirs
        assert await tx.trips.booking_access(outsider.id, loose.id) is None
        assert await tx.trips.booking_access(owner.id, uuid4()) is None
        shared = await tx.trips.list_member_trips(member.id)
        assert [t.id for t, _ in shared] == [trip.id]
        assert await tx.trips.list_member_trips(owner.id) == []  # their own aren't "shared"

    # A booking on no trip belongs to its owner alone.
    async with uow() as tx:
        await tx.trips.set_booking(owner.id, loose.id, trip_id=None, transaction_id=None)
        await tx.commit()
    async with uow() as tx:
        assert await tx.trips.booking_access(member.id, loose.id) is None
        alone = await tx.trips.booking_access(owner.id, loose.id)
        assert alone is not None and alone.is_owner and alone.trip_id is None

    # Leaving ends it at once; deleting the trip takes the membership with it.
    async with uow() as tx:
        assert await tx.trips.remove_member(owner.id, trip.id, member.id)
        assert await tx.trips.trip_access(member.id, trip.id) is None
        assert not await tx.trips.remove_member(owner.id, trip.id, member.id)
        await tx.trips.add_member(owner.id, trip.id, member.id, None, NOW)
        await tx.commit()
    await trip_cases.delete_trip(uow(), owner.id, trip.id)
    async with engine.connect() as db:
        assert (await db.execute(text("SELECT count(*) FROM trip_members"))).scalar_one() == 0


async def test_the_owner_cannot_be_their_own_member(uow: UowFactory) -> None:
    owner = await person(uow, 4242)
    trip = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    with pytest.raises(IntegrityError):
        async with uow() as tx:
            await tx.trips.add_member(owner.id, trip.id, owner.id, None, NOW)


# --- what a member sees and does ------------------------------------------------------------


async def test_a_member_edits_the_plan_and_sees_no_money(shared: Shared) -> None:
    owner, member, path = shared.owner, shared.member, shared.path
    dinner = await shared.add_dinner()
    taxi = (
        await owner.send(
            "POST", "/api/transactions",
            {"direction": "out", "amount": "30", "date": "2026-09-20", "counterparty": "Taxi"},
        )
    ).json()["id"]  # fmt: skip
    assert (await owner.send("POST", f"{path}/expenses/{taxi}")).status_code == 204
    assert (
        await owner.send("POST", f"{path}/paid-by-others", {"person": "Ann", "amount": "40"})
    ).status_code == 201

    # The owner sees all of it.
    full = (await owner.get(path)).json()
    assert full["trip"]["role"] == "owner" and full["trip"]["budget"] is not None
    assert full["spending"]["spent"]["amount"] == "30.0000" and full["paid_by_others"]

    # The member gets the plan, and not one figure of money.
    seen = await member.get(path)
    assert seen.status_code == 200
    detail = seen.json()
    assert (detail["trip"]["role"], detail["trip"]["owner_name"]) == ("member", "T")
    assert detail["trip"]["destination"] == "Tokyo" and detail["trip"]["notes"] == "Bring cash"
    assert detail["trip"]["companions"] == ["Ann"]
    assert detail["trip"]["budget"] is None and detail["trip"]["set_aside"] is None
    assert detail["trip"]["planned"] == {}
    for key in ("spending", "saving", "booked", "booked_unlogged", "to_spend"):
        assert detail[key] is None, key
    for key in ("owed", "items", "to_split", "just_mine", "paid_by_others", "balances"):
        assert detail[key] == [], key
    assert detail["ready"]["has_budget"] is False and detail["ready"]["total"] == 2
    [booking] = detail["bookings"]
    assert booking["title"] == "Dinner at Sushi Ten" and booking["reference"] == "R-1"
    assert booking["cost"] is None and booking["logged"] is False
    assert "Taxi" not in seen.text and "30.0000" not in seen.text and "20.0000" not in seen.text
    assert "2000.0000" not in seen.text and "Ann" in seen.text  # who is going is the plan's

    # The member edits the plan: days, stops, getting about, packing, notes.
    day = await member.send("PUT", f"{path}/days/2026-12-11", {"label": "Asakusa"})
    assert day.status_code == 200 and day.json()["day_labels"] == {"2026-12-11": "Asakusa"}
    assert day.json()["budget"] is None and day.json()["role"] == "member"
    stops = await member.send(
        "PUT",
        f"{path}/stops",
        {"stops": [{"name": "Asakusa", "start": "2026-12-10", "end": "2026-12-18"}]},
    )
    assert stops.status_code == 200 and stops.json()["stops"][0]["name"] == "Asakusa"
    car = await member.send("PUT", f"{path}/getting-around", {"by": "car"})
    assert car.status_code == 200 and car.json()["getting_around"] == "car"
    packing = await member.send(
        "PUT", f"{path}/packing", {"items": [{"text": "Adapter", "done": True}]}
    )
    assert packing.json()["packing"] == [{"text": "Adapter", "done": True}]
    assert (await member.send("POST", f"{path}/packing/suggest")).status_code == 200
    notes = await member.send("PUT", f"{path}/notes", {"notes": "Meet at the gate"})
    assert notes.status_code == 200 and notes.json()["notes"] == "Meet at the gate"
    assert notes.json()["budget"] is None

    # New entries, with no cost; edits keep the cost the owner gave.
    plan = {"kind": "activity", "name": "Market", "day": "2026-12-13"}
    added = await member.send("POST", f"{path}/bookings", plan)
    assert added.status_code == 201 and added.json()["cost"] is None
    assert (await member.send("POST", f"{path}/bookings", {**plan, "cost": "5"})).status_code == 403
    assert (
        await member.send("POST", f"{path}/bookings", {**plan, "currency": "JPY"})
    ).status_code == 403
    edit = await member.send(
        "PUT", f"/api/travel/bookings/{dinner['id']}", {**DINNER, "at": "20:00"}
    )
    assert edit.status_code == 200 and edit.json()["at"] == "20:00" and edit.json()["cost"] is None
    priced = await member.send(
        "PUT", f"/api/travel/bookings/{dinner['id']}", {**DINNER, "cost": "1"}
    )
    assert priced.status_code == 403
    moved = await member.send(
        "PUT", f"/api/travel/bookings/{dinner['id']}/move", {"day": "2026-12-14"}
    )
    assert (
        moved.status_code == 200
        and moved.json()["day"] == "2026-12-14"
        and moved.json()["cost"] is None
    )
    linked = await member.send(
        "PUT", f"/api/travel/bookings/{added.json()['id']}/place", {"place_id": "fakePlaceNoodle01"}
    )
    assert linked.status_code == 200
    assert (await member.get(f"{path}/places")).status_code == 200
    assert (await member.get(f"{path}/weather")).status_code == 200
    assert (await member.get(f"{path}/ideas?q=noodles")).status_code == 200
    assert (
        await member.get(f"/api/travel/places/search?q=noodles&trip_id={shared.trip}")
    ).status_code == 200
    assert (await member.get("/api/travel/places/fakePlaceNoodle01")).status_code == 200
    assert (await member.get("/api/travel/currency?place=Tokyo")).status_code == 200
    assert (await member.get(f"{path}/days/2026-12-14/hops")).status_code == 200
    deleted = await member.send("DELETE", f"/api/travel/bookings/{added.json()['id']}")
    assert deleted.status_code == 204

    # All of it is the owner's trip, and the owner's cost on the dinner is still there.
    after = (await owner.get(path)).json()
    assert after["trip"]["notes"] == "Meet at the gate"
    assert after["trip"]["budget"] == {"amount": "2000.0000", "currency": "SGD"}
    [kept] = after["bookings"]
    assert kept["at"] == "20:00" and kept["day"] == "2026-12-14"
    assert kept["cost"] == {"amount": "20.0000", "currency": "SGD"}
    assert after["spending"]["spent"]["amount"] == "30.0000"
    # Nothing reached the member's own ledger or the owner's.
    assert (await member.get("/api/transactions")).json()["total"] == 0
    assert (await owner.get("/api/transactions")).json()["total"] == 1


async def test_a_screenshot_by_a_member_drops_any_prices(shared: Shared) -> None:
    image = base64.b64encode(b"a made-up screenshot").decode()
    read = await shared.member.send(
        "POST", f"{shared.path}/screenshot", {"image": image, "mime_type": "image/png"}
    )
    assert read.status_code == 200, read.text
    body = read.json()
    hotel = next(b for b in body["added"] if b["kind"] == "hotel")
    assert hotel["cost"] is None and hotel["reference"] == "9876543210"
    assert "64500" not in body["message"]
    # The hotel is on the owner's trip without the price a member's screenshot showed.
    mine = (await shared.owner.get(shared.path)).json()
    stay = next(b for b in mine["bookings"] if b["kind"] == "hotel")
    assert stay["cost"] is None


async def test_the_trips_list_has_own_and_shared_trips(shared: Shared) -> None:
    mine = await make_trip(shared.member, destination="Kyoto")
    listed = (await shared.member.get("/api/travel/trips")).json()
    by_id = {t["id"]: t for t in listed}
    assert set(by_id) == {mine, shared.trip}
    assert by_id[mine]["role"] == "owner" and by_id[mine]["budget"] is not None
    tokyo = by_id[shared.trip]
    assert (tokyo["role"], tokyo["owner_name"]) == ("member", "T")
    assert tokyo["budget"] is None and tokyo["set_aside"] is None and tokyo["planned"] == {}
    # The owner's list holds theirs only, and the outsider's is empty.
    assert [t["id"] for t in (await shared.owner.get("/api/travel/trips")).json()] == [shared.trip]
    assert (await shared.outsider.get("/api/travel/trips")).json() == []
    # Home's "next trip" stays the person's own.
    assert (await shared.member.get("/api/travel/next")).json()["trip"]["id"] == mine


OWNER_ONLY: list[tuple[str, str, Any]] = [
    ("DELETE", "{t}", None),
    ("PUT", "{t}", TRIP),
    ("POST", "{t}/photo", {"choice": "off"}),
    ("GET", "{t}/share", None),
    ("POST", "{t}/share", {}),
    ("DELETE", "{t}/share", None),
    ("PUT", "{t}/split-evenly", {"on": False}),
    ("POST", "{t}/split", {"all": True}),
    ("POST", "{t}/keep-mine", {"transaction_ids": [UNKNOWN]}),
    ("POST", "{t}/paid-by-others", {"person": "Ann", "amount": "10"}),
    ("PUT", "{t}/paid-by-others/" + UNKNOWN, {"person": "Ann", "amount": "10"}),
    ("DELETE", "{t}/paid-by-others/" + UNKNOWN, None),
    ("POST", "{t}/settle", {"person": "Ann"}),
    ("POST", "{t}/expenses/" + UNKNOWN, None),
    ("DELETE", "{t}/expenses/" + UNKNOWN, None),
    ("POST", "{t}/invites", None),
    ("GET", "{t}/invites", None),
    ("DELETE", "{t}/invites/" + UNKNOWN, None),
    ("PUT", "/api/travel/bookings/{b}/trip", {"trip_id": None}),
    (
        "POST",
        "/api/travel/research/" + UNKNOWN + "/ideas",
        {"trip_id": "{id}", "areas": ["Asakusa"]},
    ),
]


def _fill(value: Any, shared: Shared, booking: str) -> Any:
    if isinstance(value, str):
        return (
            value.replace("{t}", shared.path).replace("{b}", booking).replace("{id}", shared.trip)
        )
    if isinstance(value, dict):
        return {k: _fill(v, shared, booking) for k, v in value.items()}
    return value


async def test_a_member_is_refused_what_only_the_owner_may_do(shared: Shared) -> None:
    booking = (await shared.add_dinner())["id"]
    for method, template, body in OWNER_ONLY:
        path = _fill(template, shared, booking)
        refused = await shared.member.send(method, path, _fill(body, shared, booking))
        assert (refused.status_code, refused.json()["detail"]) == (403, MONEY_MESSAGE), (
            method,
            path,
        )
    # Nothing changed: no link, no invite, the trip and its booking are all there.
    assert (await shared.owner.get(f"{shared.path}/share")).json()["token"] is None
    assert (await shared.owner.get(f"{shared.path}/invites")).json() == []
    detail = (await shared.owner.get(shared.path)).json()
    assert detail["trip"]["budget"] is not None and [b["id"] for b in detail["bookings"]] == [
        booking
    ]
    assert detail["trip"]["split_evenly"] is True


async def test_an_outsider_finds_no_trip_at_all(shared: Shared) -> None:
    booking = (await shared.add_dinner())["id"]
    missing = await shared.outsider.get(f"/api/travel/trips/{UNKNOWN}")
    assert missing.status_code == 404
    reads = [
        ("GET", "{t}", None),
        ("PUT", "{t}/days/2026-12-11", {"label": "No"}),
        ("PUT", "{t}/stops", {"stops": []}),
        ("PUT", "{t}/getting-around", {"by": "car"}),
        ("PUT", "{t}/packing", {"items": []}),
        ("POST", "{t}/packing/suggest", None),
        ("PUT", "{t}/notes", {"notes": "hi"}),
        ("POST", "{t}/bookings", {"kind": "activity", "name": "Market"}),
        ("GET", "{t}/places", None),
        ("GET", "{t}/weather", None),
        ("GET", "{t}/ideas?q=ramen", None),
        ("GET", "{t}/days/2026-12-12/hops", None),
        ("GET", "{t}/activity", None),
        ("GET", "{t}/members", None),
        ("GET", "/api/travel/places/search?q=noodles&trip_id={id}", None),
        ("PUT", "/api/travel/bookings/{b}", DINNER),
        ("PUT", "/api/travel/bookings/{b}/move", {"day": None}),
        ("PUT", "/api/travel/bookings/{b}/place", {"place_id": None}),
        ("DELETE", "/api/travel/bookings/{b}", None),
        *OWNER_ONLY,
    ]
    for method, template, body in reads:
        path = _fill(template, shared, booking)
        got = await shared.outsider.send(method, path, _fill(body, shared, booking))
        assert got.status_code == 404, (method, path, got.text)
    # The same answer as a trip that isn't there, so nothing says which exist.
    theirs = await shared.outsider.get(shared.path)
    assert theirs.json() == missing.json() == {"detail": "no trip with that id"}
    # And nothing was touched.
    detail = (await shared.owner.get(shared.path)).json()
    assert [b["id"] for b in detail["bookings"]] == [booking] and detail["trip"][
        "notes"
    ] == "Bring cash"


# --- invites --------------------------------------------------------------------------------


async def test_invites_are_single_use_expire_and_can_be_cancelled(shared: Shared) -> None:
    world, owner, outsider = shared.world, shared.owner, shared.outsider
    made = await shared.invite()
    token = made["token"]
    assert made["url"].endswith(f"/trip-invite/{token}") and len(token) >= 40
    assert made["expires_at"].startswith("2026-10-05")  # seven days on

    # Only a hash is kept, and the list never shows the link.
    async with world.engine.connect() as db:
        hashes: list[str] = list(
            (await db.execute(select(trip_invites.c.token_hash))).scalars().all()
        )
    assert token_hash(token) in hashes and token not in hashes
    listed = (await owner.get(f"{shared.path}/invites")).json()
    assert [set(i) for i in listed] == [{"id", "created_at", "expires_at"}]
    assert token not in (await owner.get(f"{shared.path}/invites")).text

    # The owner can't join their own trip; they get it back to open, and the link is kept.
    own = await owner.send("POST", f"/api/travel/invites/{token}/accept")
    assert own.status_code == 200
    assert own.json() == {"trip_id": shared.trip, "new": False, "own": True}
    joined = await outsider.send("POST", f"/api/travel/invites/{token}/accept")
    assert joined.status_code == 200 and joined.json()["new"] is True
    # Spent: the same person opening it again is fine, anyone else is told it is used.
    again = await outsider.send("POST", f"/api/travel/invites/{token}/accept")
    assert again.status_code == 200 and again.json() == {
        "trip_id": shared.trip,
        "new": False,
        "own": False,
    }
    third = await app_member(world, owner, 844, "Kim")
    used = await third.send("POST", f"/api/travel/invites/{token}/accept")
    assert used.status_code == 404 and "invalid, used or expired" in used.json()["detail"]
    assert (await third.get(shared.path)).status_code == 404
    assert (await owner.get(f"{shared.path}/invites")).json() == []

    # Expired.
    old = (await shared.invite())["token"]
    world.clock.now = NOW + timedelta(days=7, seconds=1)
    gone = await third.send("POST", f"/api/travel/invites/{old}/accept")
    assert gone.status_code == 404 and "invalid, used or expired" in gone.json()["detail"]
    assert (await owner.get(f"{shared.path}/invites")).json() == []
    world.clock.now = NOW

    # Cancelled.
    fresh = await shared.invite()
    assert (await owner.send("DELETE", f"{shared.path}/invites/{fresh['id']}")).status_code == 204
    cancelled = await third.send("POST", f"/api/travel/invites/{fresh['token']}/accept")
    assert cancelled.status_code == 404
    assert (await owner.send("DELETE", f"{shared.path}/invites/{fresh['id']}")).status_code == 404
    # Not a link at all.
    assert (await third.send("POST", "/api/travel/invites/nonsense/accept")).status_code == 404
    assert (await third.get(shared.path)).status_code == 404


async def test_a_trip_has_a_limited_number_of_open_invites(shared: Shared) -> None:
    for _ in range(10):
        await shared.invite()
    over = await shared.owner.send("POST", f"{shared.path}/invites")
    assert over.status_code == 422 and "open invites" in over.json()["detail"]


# --- signing in with a trip invite ----------------------------------------------------------


async def test_a_trip_invite_from_the_app_owner_makes_a_guest(shared: Shared) -> None:
    world = shared.world
    invite = await shared.invite()
    world.clock.now = NOW + timedelta(minutes=5)  # after Sam joined
    browser, response = await sign_in(
        world, GUEST, first="Gus", last="Lim", trip_invite=invite["token"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["role"] == "guest" and body["joined_trip"] == shared.trip

    # The guest opens the trip, as a member of it, with no money.
    detail = await browser.get(shared.path)
    assert detail.status_code == 200 and detail.json()["trip"]["role"] == "member"
    assert detail.json()["spending"] is None
    assert (
        await browser.send("PUT", f"{shared.path}/notes", {"notes": "From a guest"})
    ).status_code == 200
    members = (await browser.get(f"{shared.path}/members")).json()
    assert [(m["name"], m["role"], m["you"]) for m in members] == [
        ("T", "owner", False), ("Sam", "member", False), ("Gus L.", "member", True),
    ]  # fmt: skip

    # The link is spent, the guest keeps their way in, and the role is theirs for good.
    _, again = await sign_in(world, GUEST, first="Gus", last="Lim")
    assert again.status_code == 200 and again.json()["user"]["role"] == "guest"
    _, reused = await sign_in(world, 855, trip_invite=invite["token"])
    assert reused.status_code == 403 and "invalid, used or expired" in reused.json()["detail"]


async def test_a_trip_invite_does_not_make_a_guest_unless_the_app_owner_made_it(
    shared: Shared,
) -> None:
    world = shared.world
    # An ordinary user's trip invite cannot bring in someone with no account.
    mine = await make_trip(shared.member, destination="Kyoto")
    made = await shared.member.send("POST", f"/api/travel/trips/{mine}/invites")
    assert made.status_code == 201
    stranger, response = await sign_in(world, 866, trip_invite=made.json()["token"])
    assert response.status_code == 403 and "ask the trip's owner for an app invite" in response.text
    assert (await stranger.get("/api/me")).status_code == 401
    async with world.engine.connect() as db:
        assert await db.scalar(select(users.c.id).where(users.c.telegram_user_id == 866)) is None
    # Nor can an invalid one.
    _, bogus = await sign_in(world, 866, trip_invite="not-a-real-invite")
    assert bogus.status_code == 403


async def test_a_trip_invite_never_changes_an_existing_account(shared: Shared) -> None:
    world = shared.world
    # Someone with web access signs in and is added to the trip, keeping their role.
    invite = await shared.invite()
    # (OUTSIDER already has web access as an ordinary member.)
    browser, response = await sign_in(world, OUTSIDER, first="Zed", trip_invite=invite["token"])
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "member"
    assert response.json()["joined_trip"] == shared.trip
    assert (await browser.get("/api/transactions")).status_code == 200  # still a full user

    # Someone who has an account but no web access (the bot knows them) is not promoted
    # by it, even from the app owner's invite: they need an app invite.
    await register_user(
        SqlUnitOfWork(world.engine), RegisterUser(telegram_user_id=MEMBER, home_currency="SGD")
    )
    second = await shared.invite()
    _, refused = await sign_in(world, MEMBER, trip_invite=second["token"])
    assert refused.status_code == 403 and "app invite" in refused.json()["detail"]
    async with world.engine.connect() as db:
        row = (
            await db.execute(
                select(users.c.role, users.c.web_access_granted_at).where(
                    users.c.telegram_user_id == MEMBER
                )
            )
        ).one()
    assert (row.role, row.web_access_granted_at) == ("member", None)

    # A link that can't be used doesn't stop someone who may sign in anyway.
    _, plain = await sign_in(world, PEER, trip_invite="not-a-real-invite")
    assert plain.status_code == 200 and plain.json()["joined_trip"] is None
    # The owner signing in with their own trip's invite is a plain sign-in.
    third = await shared.invite()
    owner, same = await sign_in(world, OWNER, first="T", trip_invite=third["token"])
    assert same.status_code == 200 and same.json()["joined_trip"] is None
    # The invites that weren't spent are still open: the one the allow-listed user was
    # refused with, and this one.
    assert len((await owner.get(f"{shared.path}/invites")).json()) == 2


async def sign_in_webapp(
    world: World,
    telegram_id: int,
    *,
    first: str = "Sam",
    last: str | None = None,
    trip_invite: str | None = None,
) -> tuple[Browser, Response]:
    """Signs in from inside Telegram (the Mini App), with a trip invite if given."""
    user: dict[str, Any] = {"id": telegram_id, "first_name": first}
    if last:
        user["last_name"] = last
    fields = {
        "query_id": "AAH",
        "user": json.dumps(user),
        "auth_date": str(int(world.clock.now.timestamp())),
    }
    body: dict[str, Any] = {"init_data": sign_webapp_for_tests(fields, TOKEN)}
    if trip_invite:
        body["trip_invite"] = trip_invite
    browser = world.browser()
    response = await browser.client.post("/api/auth/webapp", json=body, headers={"Origin": ORIGIN})
    if response.status_code == 200:
        browser.csrf = response.json()["csrf_token"]
    return browser, response


async def test_the_mini_app_signs_in_with_a_trip_invite_as_the_widget_does(
    shared: Shared,
) -> None:
    world = shared.world
    invite = await shared.invite()
    world.clock.now = NOW + timedelta(minutes=5)  # after Sam joined
    # The app owner's invite makes a guest of someone with no account, and joins them.
    browser, response = await sign_in_webapp(
        world, GUEST, first="Gus", last="Lim", trip_invite=invite["token"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["role"] == "guest" and body["joined_trip"] == shared.trip
    assert body["user"]["display_name"] == "Gus L."
    detail = await browser.get(shared.path)
    assert detail.status_code == 200 and detail.json()["trip"]["role"] == "member"
    me = (await browser.get("/api/me")).json()
    assert me["user"]["role"] == "guest" and me["user"]["display_name"]
    # The link is spent; the guest signs in again without it, and nobody else can use it.
    _, again = await sign_in_webapp(world, GUEST, first="Gus", last="Lim")
    assert again.status_code == 200 and again.json()["joined_trip"] is None
    _, reused = await sign_in_webapp(world, 855, trip_invite=invite["token"])
    assert reused.status_code == 403 and "invalid, used or expired" in reused.json()["detail"]


async def test_the_mini_app_follows_the_same_rules_for_everyone_else(shared: Shared) -> None:
    world = shared.world
    # Someone who may sign in anyway is added to the trip, keeping their role.
    invite = await shared.invite()
    browser, response = await sign_in_webapp(
        world, OUTSIDER, first="Zed", trip_invite=invite["token"]
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "member"
    assert response.json()["joined_trip"] == shared.trip
    assert (await browser.get("/api/transactions")).status_code == 200

    # An ordinary user's invite can't bring in someone with no account, and makes none.
    mine = await make_trip(shared.member, destination="Kyoto")
    made = await shared.member.send("POST", f"/api/travel/trips/{mine}/invites")
    stranger, refused = await sign_in_webapp(world, 866, trip_invite=made.json()["token"])
    assert refused.status_code == 403 and "ask the trip's owner for an app invite" in refused.text
    assert (await stranger.get("/api/me")).status_code == 401
    async with world.engine.connect() as db:
        assert await db.scalar(select(users.c.id).where(users.c.telegram_user_id == 866)) is None
    _, bogus = await sign_in_webapp(world, 866, trip_invite="not-a-real-invite")
    assert bogus.status_code == 403

    # A link that can't be used doesn't stop someone who may sign in anyway, and the owner
    # signing in with their own trip's invite is a plain sign-in.
    _, plain = await sign_in_webapp(world, PEER, trip_invite="not-a-real-invite")
    assert plain.status_code == 200 and plain.json()["joined_trip"] is None
    own = await shared.invite()
    owner, same = await sign_in_webapp(world, OWNER, first="T", trip_invite=own["token"])
    assert same.status_code == 200 and same.json()["joined_trip"] is None
    assert len((await owner.get(f"{shared.path}/invites")).json()) == 1


async def test_me_has_the_display_name_for_the_guest_header(shared: Shared) -> None:
    me = (await shared.member.get("/api/me")).json()
    assert me["user"]["display_name"] == "Sam"
    assert (await shared.owner.get("/api/me")).json()["user"]["display_name"] == "T"


async def test_the_widget_redirect_takes_a_new_member_to_the_trip(shared: Shared) -> None:
    invite = await shared.invite()
    world = shared.world
    fields = {"id": GUEST, "first_name": "Gus", "auth_date": int(world.clock.now.timestamp())}
    params = {**sign_for_tests(fields, TOKEN), "trip_invite": invite["token"]}
    browser = world.browser()
    response = await browser.client.get("/api/auth/telegram/callback", params=params)
    assert (
        response.status_code == 303
        and response.headers["location"] == f"/travel/trips/{shared.trip}"
    )
    assert (await browser.get(shared.path)).status_code == 200


async def test_the_name_others_see_is_refreshed_at_each_sign_in(shared: Shared) -> None:
    owner = shared.owner

    def names(members: list[dict[str, str]]) -> list[str]:
        return [m["name"] for m in members]

    assert names((await owner.get(f"{shared.path}/members")).json()) == ["T", "Sam"]
    await sign_in(shared.world, PEER, first="Samuel", last="Ng")
    assert names((await owner.get(f"{shared.path}/members")).json()) == ["T", "Samuel N."]
    # No name from Telegram keeps the one we had.
    browser = shared.world.browser()
    plain = sign_for_tests(
        {"id": PEER, "auth_date": int(shared.world.clock.now.timestamp())}, TOKEN
    )
    await browser.client.post(
        "/api/auth/telegram", json={"telegram": plain}, headers={"Origin": ORIGIN}
    )
    assert names((await owner.get(f"{shared.path}/members")).json()) == ["T", "Samuel N."]


# --- guests get in nowhere else -------------------------------------------------------------


async def make_guest(shared: Shared) -> Browser:
    invite = await shared.invite()
    browser, response = await sign_in(shared.world, GUEST, trip_invite=invite["token"])
    assert response.status_code == 200, response.text
    return browser


async def test_a_guest_is_refused_by_ordinary_routes_and_allowed_on_the_trip(
    shared: Shared,
) -> None:
    guest = await make_guest(shared)
    for method, path, body in [
        ("GET", "/api/home", None),
        ("GET", "/api/transactions", None),
        ("GET", "/api/summary", None),
        ("GET", "/api/categories", None),
        ("GET", "/api/wallets", None),
        ("POST", "/api/transactions", {"direction": "out", "amount": "3"}),
        ("POST", "/api/invites", None),
        ("POST", "/api/chat", {"text": "hi"}),
        ("GET", "/api/travel/next", None),
        ("GET", "/api/travel/bookings", None),
        ("POST", "/api/travel/trips", TRIP),
        ("GET", "/api/email", None),
        ("GET", "/api/investments", None),
        ("DELETE", shared.path, None),
        ("GET", f"{shared.path}/share", None),
    ]:
        refused = await guest.send(method, path, body)
        assert (refused.status_code, refused.text) == (403, f'{{"detail":"{GUEST_MESSAGE}"}}'), (
            method,
            path,
        )

    assert (await guest.get("/api/me")).json()["user"]["role"] == "guest"
    assert (await guest.get(shared.path)).status_code == 200
    assert [t["id"] for t in (await guest.get("/api/travel/trips")).json()] == [shared.trip]
    assert (await guest.get(f"{shared.path}/activity")).status_code == 200
    # Another trip is not theirs.
    other = await make_trip(shared.owner, destination="Osaka")
    assert (await guest.get(f"/api/travel/trips/{other}")).status_code == 404
    assert (await guest.send("POST", "/api/auth/logout")).status_code == 204
    assert (await guest.get("/api/me")).status_code == 401


def _guards(route: APIRoute) -> set[str]:
    found: set[str] = set()

    def walk(dependant: Any) -> None:
        for sub in dependant.dependencies:
            if sub.call is authenticated:
                found.add("auth")
            elif sub.call is signed_in:
                found.add("trip")
            walk(sub)

    walk(route.dependant)
    return found


def test_only_the_routes_a_guest_needs_let_a_guest_in() -> None:
    open_to_guests: set[tuple[str, str]] = set()
    unguarded: set[tuple[str, str]] = set()
    for router in (
        web_api.router,
        travel_api.router,
        travel_api.shared_router,
        email_api.router,
        investments_api.router,
        ops_api.router,
    ):
        for route in router.routes:
            assert isinstance(route, APIRoute)
            guards = _guards(route)
            for method in (route.methods or set()) - {"HEAD", "OPTIONS"}:
                if "trip" in guards:
                    open_to_guests.add((method, route.path))
                elif not guards:
                    unguarded.add((method, route.path))
    t = "/api/travel/trips/{trip_id}"
    assert open_to_guests == {
        ("GET", "/api/me"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/travel/trips"),
        ("GET", t),
        ("GET", "/api/travel/photos/{photo_id}"),
        ("PUT", f"{t}/days/{{day}}"),
        ("PUT", f"{t}/stops"),
        ("PUT", f"{t}/getting-around"),
        ("PUT", f"{t}/notes"),
        ("PUT", f"{t}/packing"),
        ("POST", f"{t}/packing/suggest"),
        ("PUT", f"{t}/todos"),
        ("POST", f"{t}/prep/dismiss"),
        ("DELETE", f"{t}/prep/dismiss/{{key}}"),
        ("POST", f"{t}/covers"),
        ("PUT", f"{t}/covers/{{cover_id}}"),
        ("DELETE", f"{t}/covers/{{cover_id}}"),
        ("GET", f"{t}/weather"),
        ("GET", f"{t}/ideas"),
        ("GET", f"{t}/places"),
        ("GET", f"{t}/days/{{day}}/hops"),
        ("GET", f"{t}/days/{{day}}/hops/{{start_id}}/{{end_id}}"),
        ("POST", f"{t}/bookings"),
        ("POST", f"{t}/screenshot"),
        ("PUT", "/api/travel/bookings/{booking_id}"),
        ("DELETE", "/api/travel/bookings/{booking_id}"),
        ("PUT", "/api/travel/bookings/{booking_id}/move"),
        ("PUT", "/api/travel/bookings/{booking_id}/place"),
        ("GET", "/api/travel/places/search"),
        ("GET", "/api/travel/places/{place_id}"),
        ("GET", "/api/travel/places/{place_id}/photo"),
        ("GET", "/api/travel/currency"),
        ("GET", f"{t}/activity"),
        ("GET", f"{t}/members"),
        ("DELETE", f"{t}/members/{{member_id}}"),
        ("POST", "/api/travel/invites/{token}/accept"),
    }
    # Everything else is closed to guests, either by ``Auth`` or by being a route that needs
    # no session: sign-in itself, the read-only trip link, the config the sign-in page
    # needs, the Gmail connect pages (a one-time link, made by a signed-in owner or member),
    # and the ops routes, which call ``authenticated`` themselves.
    assert {path for _, path in unguarded} == {
        "/api/config",
        "/api/auth/telegram",
        "/api/auth/webapp",
        "/api/auth/telegram/callback",
        "/api/shared/trips/{token}",
        "/api/shared/trips/{token}/photo",
        "/api/email/link",
        "/api/email/gmail/start",
        "/api/email/gmail/callback",
        "/api/ops/tickets",
        "/api/ops/report",
    }


# --- coming and going, and what was changed ------------------------------------------------


async def test_removing_a_member_ends_their_access_at_once(shared: Shared) -> None:
    owner, member, path = shared.owner, shared.member, shared.path
    members = (await owner.get(f"{path}/members")).json()
    assert [(m["name"], m["role"]) for m in members] == [("T", "owner"), ("Sam", "member")]
    sam = next(m["id"] for m in members if m["role"] == "member")
    owner_id = next(m["id"] for m in members if m["role"] == "owner")
    assert (await member.get(path)).status_code == 200

    # A member can't remove anyone else (or the owner), only themselves.
    third = await app_member(shared.world, owner, 877, "Kim")
    token = (await shared.invite())["token"]
    await third.send("POST", f"/api/travel/invites/{token}/accept")
    kim = next(m["id"] for m in (await third.get(f"{path}/members")).json() if m["you"])
    for target in (kim, owner_id):
        refused = await member.send("DELETE", f"{path}/members/{target}")
        assert (refused.status_code, refused.json()["detail"]) == (403, MONEY_MESSAGE)

    assert (await owner.send("DELETE", f"{path}/members/{sam}")).status_code == 204
    gone = await member.get(path)
    assert gone.status_code == 404 and gone.json() == {"detail": "no trip with that id"}
    assert (await member.send("PUT", f"{path}/notes", {"notes": "still here?"})).status_code == 404
    assert shared.trip not in [t["id"] for t in (await member.get("/api/travel/trips")).json()]
    assert (await owner.send("DELETE", f"{path}/members/{sam}")).status_code == 404

    # Leaving is a member removing themselves.
    assert (await third.send("DELETE", f"{path}/members/{kim}")).status_code == 204
    assert (await third.get(path)).status_code == 404
    assert (await owner.get(f"{path}/members")).json()[1:] == []
    assert (await owner.get(path)).status_code == 200


async def test_edits_on_a_shared_trip_are_listed_newest_first(shared: Shared) -> None:
    owner, member, path = shared.owner, shared.member, shared.path
    assert (await owner.get(f"{path}/activity")).json() == []
    world = shared.world

    async def later(minutes: int) -> None:
        world.clock.now = NOW + timedelta(minutes=minutes)

    await later(1)
    dinner = await member.send("POST", f"{path}/bookings", DINNER)
    await later(2)
    await member.send(
        "PUT", f"/api/travel/bookings/{dinner.json()['id']}/move", {"day": "2026-12-14"}
    )
    await later(3)
    await owner.send("PUT", f"{path}/packing", {"items": [{"text": "Adapter"}]})
    await later(4)
    await member.send("PUT", f"{path}/notes", {"notes": "Meet at the gate"})
    await later(5)
    await owner.send("DELETE", f"/api/travel/bookings/{dinner.json()['id']}")
    # Reading changes nothing in the feed.
    await member.get(path)
    await member.get(f"{path}/places")

    feed = (await member.get(f"{path}/activity")).json()
    assert [(a["actor"], a["summary"]) for a in feed] == [
        ("T", "removed Dinner at Sushi Ten"),
        ("Sam", "changed the notes"),
        ("T", "changed the packing list"),
        ("Sam", "moved Dinner at Sushi Ten to Day 5"),
        ("Sam", "added Dinner at Sushi Ten"),
    ]
    assert set(feed[0]) == {"actor", "summary", "at"}
    assert (await owner.get(f"{path}/activity")).json() == feed
    assert (await shared.outsider.get(f"{path}/activity")).status_code == 404

    # At most the latest 20.
    for n in range(25):
        await later(10 + n)
        await owner.send("PUT", f"{path}/days/2026-12-11", {"label": f"Stop {n}"})
    feed = (await owner.get(f"{path}/activity")).json()
    assert len(feed) == 20 and feed[0]["summary"] == 'named Day 2 "Stop 24"'


async def test_a_trip_nobody_shares_keeps_no_activity(world: World, uow: UowFactory) -> None:
    owner = world.browser()
    await owner.login(OWNER)
    trip = await make_trip(owner)
    path = f"/api/travel/trips/{trip}"
    await owner.send("PUT", f"{path}/notes", {"notes": "Just me"})
    await owner.send("POST", f"{path}/bookings", DINNER)
    assert (await owner.get(f"{path}/activity")).json() == []
    async with world.engine.connect() as db:
        assert (await db.execute(text("SELECT count(*) FROM trip_activity"))).scalar_one() == 0


async def test_an_actor_with_no_name_shows_as_someone(uow: UowFactory) -> None:
    owner = await person(uow, 4242)
    friend = await person(uow, 4343)  # signed in never, so no name
    trip = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    async with uow() as tx:
        await tx.trips.add_member(owner.id, trip.id, friend.id, None, NOW)
        await tx.commit()
    access = await access_cases.open_trip(uow(), friend, trip.id)
    await access_cases.record(uow(), access.access, "changed the notes", now=NOW)
    found = await access_cases.activity(uow(), friend, trip.id)
    assert [(a.actor, a.summary) for a in found] == [("Someone", "changed the notes")]
    members = await access_cases.list_members(uow(), owner, trip.id)
    assert [m.name for m in members] == ["Someone", "Someone"]


async def test_the_use_cases_refuse_a_member_the_owners_work(uow: UowFactory) -> None:
    owner = await person(uow, 4242)
    friend = await person(uow, 4343)
    stranger = await person(uow, 4444)
    trip = await trip_cases.create_trip(uow(), owner, draft(), now=NOW)
    async with uow() as tx:
        await tx.trips.add_member(owner.id, trip.id, friend.id, None, NOW)
        await tx.commit()
    opened = await access_cases.open_trip(uow(), friend, trip.id)
    assert opened.owner.id == owner.id and not opened.access.is_owner
    with pytest.raises(Forbidden):
        await access_cases.open_trip(uow(), friend, trip.id, owner_only=True)
    with pytest.raises(Forbidden):
        await access_cases.create_invite(uow(), friend, trip.id, now=NOW)
    with pytest.raises(NotFound):
        await access_cases.open_trip(uow(), stranger, trip.id)
    with pytest.raises(NotFound):
        await access_cases.create_invite(uow(), stranger, trip.id, now=NOW)
    with pytest.raises(NotFound):
        await access_cases.open_booking(uow(), friend, uuid4())
    # The owner can't take their own invite: they get their trip back, joined to nothing.
    issued = await access_cases.create_invite(uow(), owner, trip.id, now=NOW)
    own = await access_cases.accept_invite(uow(), owner, issued.token, now=NOW)
    assert (own.trip_id, own.new, own.own) == (trip.id, False, True)
    # A member's plan view has no money in it and needs no ledger.
    view = await access_cases.plan_view(uow(), owner.id, trip.id, friend, now=NOW)
    assert view.trip.budget is None and view.ready.has_budget is False
