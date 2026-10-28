"""Shared trips, attacked. An independent, systematic try at breaking the access rules:
every trip route is called by people who have no business on the trip, guests are shut
out of the whole app, members are kept away from the owner's money and ledger, and the
invites, sign-in and names are abused. Every name and figure here is made up.

The two route sweeps are generated from the running app's routes, so a route added later
fails them until it is classified here."""

import asyncio
import base64
import logging
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application.clock import utcnow
from nexus.application.users import RegisterUser, register_user
from nexus.channels.web.security import authenticated, signed_in
from nexus.domain.access import token_hash
from nexus.domain.ledger import UserId
from nexus.domain.prep import Cover, CoverDraft, CoverKind
from nexus.infra.db.tables import trip_invites, users
from nexus.infra.db.uow import SqlUnitOfWork
from tests.fakes import NOW
from tests.integration import test_web_api
from tests.integration.test_research_ideas import finished_research
from tests.integration.test_shared_trips import (
    DINNER,
    GUEST_MESSAGE,
    MONEY_MESSAGE,
    TRIP,
    UNKNOWN,
    app_member,
    make_trip,
    sign_in,
)
from tests.integration.test_web_api import ORIGIN, OWNER, Browser, World

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

# Telegram ids of the people in the scene.
MEMBER_ID, OUTSIDER_ID, PEER_B_ID, EX_ID, GUEST_A_ID, GUEST_B_ID = 811, 822, 833, 844, 855, 866

# The owner's money, in figures nobody would type by accident. None of them may ever
# reach anyone but the owner.
BUDGET, SET_ASIDE, PLANNED = "4321.09", "1234.56", "777.77"
DINNER_COST, TAXI, PAID_FOR_ME, B_COST = "987.65", "555.43", "321.09", "111.11"
COVER_COST = "246.81"  # what the trip's insurance cost
# The app writes amounts to people with thousands separators ("4,321.09 SGD"), so a leak
# in chat text would show that way, not as stored.
SECRETS = (
    BUDGET, SET_ASIDE, PLANNED, DINNER_COST, TAXI, PAID_FOR_ME, B_COST, COVER_COST,
    "4,321.09", "1,234.56",
)  # fmt: skip
COVER = {
    "kind": "insurance", "name": "Harbour Cover", "reference": "TX-4471", "phone": "+65 6123 4567",
}  # fmt: skip
TRIP_A = {**TRIP, "budget": BUDGET, "set_aside": SET_ASIDE, "planned": {"Dining Out": PLANNED}}
IMAGE = base64.b64encode(b"a made-up screenshot").decode()
OWNER_NOTE = "Owner-only: pay the deposit"  # in the owner's expenses, not on the trip


# --- the scene --------------------------------------------------------------------------------


@dataclass
class Scene:
    """The app owner's two trips and everyone around them.

    Trip A (Tokyo) is full of money. Trip B (Osaka) is the same owner's other trip.
    ``member`` is on A; ``peer_b`` and ``guest_b`` are on B only; ``ex`` was on A and was
    taken off it; ``guest_a`` is a guest on A; ``outsider`` is on nothing."""

    world: World
    owner: Browser
    member: Browser
    outsider: Browser
    peer_b: Browser
    ex: Browser
    guest_a: Browser
    guest_b: Browser
    trip_a: str
    trip_b: str
    dinner: str = ""  # a booking on A with a cost, logged as an expense
    lunch: str = ""  # a booking on A with no cost
    b_booking: str = ""  # a booking on B with a cost
    taxi: str = ""  # the owner's expense on A
    payment: str = ""  # something a friend paid for, on A
    cover: str = ""  # the insurance on A, with a cost
    invite: str = ""  # an open invite to A (its id)
    owner_id: str = ""  # the app owner's user id
    ids: dict[str, str] = field(default_factory=dict)  # name -> user id, on trip A

    @property
    def a(self) -> str:
        return f"/api/travel/trips/{self.trip_a}"

    @property
    def b(self) -> str:
        return f"/api/travel/trips/{self.trip_b}"

    @property
    def engine(self) -> AsyncEngine:
        return self.world.engine

    def uow(self) -> SqlUnitOfWork:
        return SqlUnitOfWork(self.world.engine)

    async def invite_to(self, trip_path: str) -> dict[str, Any]:
        made = await self.owner.send("POST", f"{trip_path}/invites")
        assert made.status_code == 201, made.text
        body: dict[str, Any] = made.json()
        return body

    async def join(self, who: Browser, trip_path: str) -> None:
        token = (await self.invite_to(trip_path))["token"]
        joined = await who.send("POST", f"/api/travel/invites/{token}/accept")
        assert joined.status_code == 200, joined.text


async def build_scene(world: World) -> Scene:
    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    member = await app_member(world, owner, MEMBER_ID, "Sam")
    outsider = await app_member(world, owner, OUTSIDER_ID, "Zed")
    peer_b = await app_member(world, owner, PEER_B_ID, "Pia")
    ex = await app_member(world, owner, EX_ID, "Eve")
    trip_a = await make_trip(owner, **{k: v for k, v in TRIP_A.items() if k != "destination"})
    trip_b = await make_trip(owner, destination="Osaka", budget="9999.99")
    blank = world.browser()
    scene = Scene(world, owner, member, outsider, peer_b, ex, blank, blank, trip_a, trip_b)

    # What the owner keeps on A: bookings with costs, an expense, a bill a friend paid.
    made = await owner.send("POST", f"{scene.a}/bookings", {**DINNER, "cost": DINNER_COST})
    scene.dinner = made.json()["id"]
    lunch = {"kind": "activity", "name": "Lunch at Udon Ya", "day": "2026-12-12", "at": "12:00"}
    scene.lunch = (await owner.send("POST", f"{scene.a}/bookings", lunch)).json()["id"]
    for booking, place in ((scene.lunch, "fakePlaceTemple01"), (scene.dinner, "fakePlaceNoodle01")):
        linked = await owner.send(  # on a map, so the day has a hop
            "PUT", f"/api/travel/bookings/{booking}/place", {"place_id": place}
        )
        assert linked.status_code == 200, linked.text
    other = {"kind": "activity", "name": "Castle", "day": "2026-12-14", "cost": B_COST}
    scene.b_booking = (await owner.send("POST", f"{scene.b}/bookings", other)).json()["id"]
    txn = await owner.send(
        "POST", "/api/transactions",
        {"direction": "out", "amount": TAXI, "date": "2026-09-20", "counterparty": "Taxi"},
    )  # fmt: skip
    scene.taxi = txn.json()["id"]
    assert (await owner.send("POST", f"{scene.a}/expenses/{scene.taxi}")).status_code == 204
    paid = await owner.send(
        "POST", f"{scene.a}/paid-by-others", {"person": "Ann", "amount": PAID_FOR_ME}
    )
    assert paid.status_code == 201, paid.text
    scene.payment = paid.json()["id"]
    made_cover = await owner.send(
        "POST", f"{scene.a}/covers", {**COVER, "cost": COVER_COST, "currency": "SGD"}
    )
    assert made_cover.status_code == 201, made_cover.text
    scene.cover = made_cover.json()["id"]
    todo = {"todos": [{"text": "Get yen", "due": "2026-12-08"}]}
    assert (await owner.send("PUT", f"{scene.a}/todos", todo)).status_code == 200
    split = await owner.send("POST", f"{scene.a}/split", {"all": True})
    assert split.status_code == 200 and split.json()["done"], split.text
    scene.owner_id = next(m["id"] for m in (await owner.get(f"{scene.a}/members")).json())
    async with scene.uow() as tx:  # the dinner was logged as that expense
        await tx.trips.set_booking(
            UserId(UUID(scene.owner_id)), UUID(scene.dinner), trip_id=UUID(scene.trip_a),
            transaction_id=UUID(scene.taxi),
        )  # fmt: skip
        await tx.commit()

    # The people.
    await scene.join(member, scene.a)
    await scene.join(ex, scene.a)
    gone = [m["id"] for m in (await owner.get(f"{scene.a}/members")).json() if m["name"] == "Eve"]
    assert (await owner.send("DELETE", f"{scene.a}/members/{gone[0]}")).status_code == 204
    await scene.join(peer_b, scene.b)
    invite_b = (await scene.invite_to(scene.b))["token"]
    scene.guest_b, made_b = await sign_in(world, GUEST_B_ID, first="Gil", trip_invite=invite_b)
    assert made_b.status_code == 200 and made_b.json()["user"]["role"] == "guest"
    invite_a = (await scene.invite_to(scene.a))["token"]
    scene.guest_a, made_a = await sign_in(world, GUEST_A_ID, first="Gus", trip_invite=invite_a)
    assert made_a.status_code == 200 and made_a.json()["joined_trip"] == scene.trip_a
    scene.invite = (await scene.invite_to(scene.a))["id"]
    scene.ids = {m["name"]: m["id"] for m in (await owner.get(f"{scene.a}/members")).json()} | {
        "Eve": gone[0]
    }
    return scene


@pytest.fixture
async def scene(world: World) -> Scene:
    return await build_scene(world)


# --- looking at the database --------------------------------------------------------------------

# What a trip request could touch, one table at a time.
TRIP_TABLES = (
    "trips", "trip_bookings", "trip_members", "trip_invites", "trip_activity", "trip_links",
    "trip_paid_by_others", "trip_covers", "trip_shares", "transactions", "splits", "settlements",
    "transaction_revisions", "transaction_sources", "categories", "wallets", "users",
    "budgets", "chat_log", "memories", "plans", "department_runs",
)  # fmt: skip
# Tables that change just by being used: sessions, caches, traces and the job queue.
NOISE = {
    "web_sessions", "ops_events", "inbound_events", "jobs", "web_cache", "web_credits",
    "fx_rates", "alembic_version",
}  # fmt: skip
Snapshot = dict[str, list[str]]


async def column(engine: AsyncEngine, query: Any, **params: Any) -> list[Any]:
    """The first column of every row a query returns."""
    async with engine.connect() as db:
        result = await db.execute(text(query) if isinstance(query, str) else query, params)
        found: list[Any] = list(result.scalars().all())
    return found


async def one(engine: AsyncEngine, query: Any, **params: Any) -> Any:
    """The first column of the first row, or None."""
    found = await column(engine, query, **params)
    return found[0] if found else None


async def snapshot(engine: AsyncEngine, tables: tuple[str, ...] | None = None) -> Snapshot:
    """Every row of the given tables (default: all but the noisy ones), as JSON text."""
    if tables is None:
        found = await column(engine, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
        tables = tuple(sorted(set(found) - NOISE))
    shot: Snapshot = {}
    for name in tables:
        query = f"SELECT row_to_json(x)::text FROM {name} x"  # noqa: S608 - fixed names
        shot[name] = sorted(await column(engine, query))
    return shot


def changed(before: Snapshot, after: Snapshot) -> dict[str, tuple[int, int]]:
    return {
        name: (len(before[name]), len(after[name]))
        for name in before
        if before[name] != after[name]
    }


async def raw_secret_in_database(engine: AsyncEngine, secret: str) -> list[str]:
    """The tables (any column) that hold ``secret`` as written."""
    names = await column(engine, "SELECT tablename FROM pg_tables WHERE schemaname='public'")
    found: list[str] = []
    for name in names:
        query = f"SELECT count(*) FROM {name} x WHERE row_to_json(x)::text LIKE :s"  # noqa: S608
        if await one(engine, query, s=f"%{secret}%"):
            found.append(name)
    return found


# --- reading responses ---------------------------------------------------------------------------

_MONEY_WORDS = re.compile(
    r"amount|cost|budget|spen[dt]|saving|saved|set_aside|owed|balance|transaction|planned"
    r"|split|paid"
)
_MONEY_TOKENS = {"home", "net"}
# What a member's page keeps for a setting whose real value is hidden.
_NEUTRAL = {"split_evenly": True}


def money_keys(node: Any, where: str = "$") -> Iterator[str]:
    """The paths of keys that sound like money and hold something (not null, false, zero,
    empty), at any depth. A hidden setting's neutral default is not a leak."""
    if isinstance(node, dict):
        for key, value in node.items():
            low = str(key).lower()
            sounds = _MONEY_WORDS.search(low) or _MONEY_TOKENS & set(low.split("_"))
            if low in _NEUTRAL:
                leaks = value != _NEUTRAL[low]
            else:
                leaks = bool(sounds) and value not in (None, False, 0, "", [], {})
            if leaks:
                yield f"{where}.{key}"
            yield from money_keys(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from money_keys(value, f"{where}[{i}]")


def assert_no_money(response: Any, what: str, *, keys: bool = True) -> None:
    """Nothing of the owner's money in a response a member got: no money-like key holding
    a value (unless ``keys`` is off, for the viewer's own profile), and none of the real
    figures anywhere in its text."""
    if response.status_code == 204 or not response.content:
        return
    for secret in SECRETS:
        assert secret not in response.text, (what, secret)
    if keys and "json" in response.headers.get("content-type", ""):
        assert list(money_keys(response.json())) == [], (what, response.text[:300])


def guards_of(route: APIRoute) -> set[str]:
    """``auth``: closed to guests (``Auth``); ``trip``: open to them (``TripAuth``)."""
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


def _flat(routes: Any) -> Iterator[Any]:
    """The app's routes with included routers opened up (FastAPI keeps them nested)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is None:
            yield route
            continue
        assert not route.include_context.prefix, "a router included under a prefix needs handling"
        yield from _flat(inner.routes)


def api_routes(app: Any, *prefixes: str) -> list[APIRoute]:
    routes = [r for r in _flat(app.routes) if getattr(r, "path", "").startswith(prefixes)]
    odd = [r for r in routes if not isinstance(r, APIRoute)]
    assert not odd, f"routes that are not plain API routes need a place here: {odd}"
    return [r for r in routes if isinstance(r, APIRoute)]


def methods_of(route: APIRoute) -> list[str]:
    return sorted((route.methods or set()) - {"HEAD", "OPTIONS"})


# --- the calls -------------------------------------------------------------------------------

type Call = tuple[str, Any]  # a query string and a JSON body
T = "/api/travel/trips/{trip_id}"
B = "/api/travel/bookings/{booking_id}"
PLAN = {"kind": "activity", "name": "Market", "day": "2026-12-13"}
PACKING = {"items": [{"text": "Adapter", "done": True}]}
# One valid-looking call for every route that is about one trip or booking. A route added
# without an entry here fails ``test_every_trip_route_is_in_the_matrix``.
CALLS: dict[tuple[str, str], Call] = {
    ("GET", T): ("", None),
    ("PUT", T): ("", TRIP),
    ("DELETE", T): ("", None),
    ("PUT", f"{T}/notes"): ("", {"notes": "Hello"}),
    ("PUT", f"{T}/days/{{day}}"): ("", {"label": "Asakusa"}),
    ("PUT", f"{T}/stops"): ("", {"stops": []}),
    ("PUT", f"{T}/getting-around"): ("", {"by": "car"}),
    ("POST", f"{T}/expenses/{{transaction_id}}"): ("", None),
    ("DELETE", f"{T}/expenses/{{transaction_id}}"): ("", None),
    ("PUT", f"{T}/split-evenly"): ("", {"on": False}),
    ("POST", f"{T}/split"): ("", {"all": True}),
    ("POST", f"{T}/keep-mine"): ("", {"transaction_ids": ["{transaction_id}"]}),
    ("POST", f"{T}/paid-by-others"): ("", {"person": "Ann", "amount": "10"}),
    ("PUT", f"{T}/paid-by-others/{{payment_id}}"): ("", {"person": "Ann", "amount": "10"}),
    ("DELETE", f"{T}/paid-by-others/{{payment_id}}"): ("", None),
    ("POST", f"{T}/settle"): ("", {"person": "Ann"}),
    ("PUT", f"{B}/trip"): ("", {"trip_id": "{other_trip}"}),
    ("DELETE", B): ("", None),
    ("POST", f"{T}/bookings"): ("", PLAN),
    ("PUT", B): ("", {**DINNER, "at": "20:30"}),
    ("PUT", f"{B}/move"): ("", {"day": "2026-12-14"}),
    ("POST", f"{T}/screenshot"): ("", {"image": IMAGE, "mime_type": "image/png"}),
    ("GET", "/api/travel/places/search"): ("?q=noodles&trip_id={trip_id}", None),
    ("GET", f"{T}/ideas"): ("?q=ramen", None),
    ("GET", f"{T}/places"): ("", None),
    ("GET", f"{T}/days/{{day}}/hops"): ("", None),
    ("GET", f"{T}/days/{{day}}/hops/{{start_id}}/{{end_id}}"): ("?mode=walk", None),
    ("PUT", f"{B}/place"): ("", {"place_id": "fakePlaceNoodle01"}),
    ("POST", f"{T}/photo"): ("", {"choice": "off"}),
    ("PUT", f"{T}/packing"): ("", PACKING),
    ("POST", f"{T}/packing/suggest"): ("", None),
    ("PUT", f"{T}/todos"): ("", {"todos": [{"text": "Get yen", "due": "2026-12-08"}]}),
    ("POST", f"{T}/prep/dismiss"): ("", {"key": "money"}),
    ("DELETE", f"{T}/prep/dismiss/{{key}}"): ("", None),
    ("POST", f"{T}/covers"): ("", COVER),
    ("PUT", f"{T}/covers/{{cover_id}}"): ("", COVER),
    ("DELETE", f"{T}/covers/{{cover_id}}"): ("", None),
    ("POST", f"{T}/covers/{{cover_id}}/log"): ("", None),
    ("GET", f"{T}/weather"): ("", None),
    ("GET", f"{T}/share"): ("", None),
    ("POST", f"{T}/share"): ("", {}),
    ("DELETE", f"{T}/share"): ("", None),
    ("POST", f"{T}/invites"): ("", None),
    ("GET", f"{T}/invites"): ("", None),
    ("DELETE", f"{T}/invites/{{invite_id}}"): ("", None),
    ("GET", f"{T}/members"): ("", None),
    ("DELETE", f"{T}/members/{{member_id}}"): ("", None),
    ("GET", f"{T}/activity"): ("", None),
    ("POST", "/api/travel/research/{run_id}/ideas"): (
        "",
        {"trip_id": "{trip_id}", "areas": ["Asakusa"]},
    ),
}
# Routes that are not about one trip or booking: the person's own, or open by design.
# They get their own tests (guests, invites, the shared link) rather than the matrix.
NOT_ABOUT_A_TRIP = {
    ("GET", "/api/travel/trips"),
    ("POST", "/api/travel/trips"),
    ("GET", "/api/travel/next"),
    ("GET", "/api/travel/bookings"),
    ("GET", "/api/travel/photos/{photo_id}"),
    ("GET", "/api/travel/research/{run_id}"),
    ("POST", "/api/travel/research/{run_id}/trip"),
    ("GET", "/api/travel/places/{place_id}"),
    ("GET", "/api/travel/places/{place_id}/photo"),
    ("GET", "/api/travel/currency"),
    ("POST", "/api/travel/invites/{token}/accept"),
    ("GET", "/api/shared/trips/{token}"),
    ("GET", "/api/shared/trips/{token}/photo"),
}
# Calls for the routes above that a member or guest may make, for the money sweep.
OWN_CALLS: dict[tuple[str, str], Call] = {
    ("GET", "/api/travel/trips"): ("", None),
    ("GET", "/api/travel/photos/{photo_id}"): ("", None),
    ("GET", "/api/travel/places/{place_id}"): ("", None),
    ("GET", "/api/travel/places/{place_id}/photo"): ("", None),
    ("GET", "/api/travel/currency"): ("?place=Tokyo", None),
    ("GET", "/api/me"): ("", None),
}


def scope_of(route: APIRoute, method: str) -> str | None:
    """What a route is about: its ``trip`` or ``booking`` path parameter, a ``trip-query``
    or a ``trip-body`` that names one, else None."""
    dep = route.dependant
    paths = {p.name for p in dep.path_params}
    if "trip_id" in paths:
        return "trip"
    if "booking_id" in paths:
        return "booking"
    if "trip_id" in {q.name for q in dep.query_params}:
        return "trip-query"
    for body in dep.body_params:
        if "trip_id" in getattr(body.field_info.annotation, "model_fields", {}):
            return "trip-body"
    return None


def fill(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        for name, found in ids.items():
            value = value.replace("{" + name + "}", found)
        return value
    if isinstance(value, dict):
        return {k: fill(v, ids) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, ids) for v in value]
    return value


def ids_of(scene: Scene, **changes: str) -> dict[str, str]:
    """What each path parameter stands for: real things on trip A, so a request that got
    through would do real damage."""
    return {
        "trip_id": scene.trip_a,
        "other_trip": scene.trip_b,
        "booking_id": scene.dinner,
        "day": "2026-12-12",
        "transaction_id": scene.taxi,
        "payment_id": scene.payment,
        "cover_id": scene.cover,
        "key": "money",
        "invite_id": scene.invite,
        "member_id": scene.ids["Sam"],
        "start_id": scene.lunch,
        "end_id": scene.dinner,
        "run_id": UNKNOWN,
        "photo_id": UNKNOWN,
        "place_id": "fakePlaceNoodle01",
        "token": "not-a-token",
    } | changes


async def call(who: Browser, scene: Scene, method: str, template: str, **changes: str) -> Any:
    query, body = CALLS.get((method, template)) or OWN_CALLS[(method, template)]
    ids = ids_of(scene, **changes)
    return await who.send(method, fill(template, ids) + fill(query, ids), fill(body, ids))


def classified(scene: Scene) -> list[tuple[APIRoute, str, str, str]]:
    """(route, method, template, scope) for every trip or booking route of the app. Fails
    for one the matrix does not know."""
    found = []
    unknown = []
    for route in api_routes(scene.world.app, "/api/travel", "/api/shared"):
        for method in methods_of(route):
            key = (method, route.path)
            scope = scope_of(route, method)
            if scope is None:
                if key not in NOT_ABOUT_A_TRIP:
                    unknown.append(f"{method} {route.path}: not in NOT_ABOUT_A_TRIP")
                continue
            if key not in CALLS:
                unknown.append(f"{method} {route.path}: ({scope}) has no entry in CALLS")
            found.append((route, method, route.path, scope))
    assert not unknown, "routes the security matrix does not know:\n" + "\n".join(unknown)
    return found


def test_the_call_tables_hold_no_stale_routes() -> None:
    """The reverse: a route removed or renamed leaves nothing behind in the tables."""
    stale = [k for k in {*CALLS, *NOT_ABOUT_A_TRIP} if not k[1].startswith("/api/")]
    assert stale == []


async def test_every_trip_route_is_in_the_matrix(scene: Scene) -> None:
    routes = classified(scene)
    seen = {(m, p) for _, m, p, _ in routes}
    assert seen == set(CALLS), "CALLS names a route the app no longer has"
    # The sweep really covers the trip and booking routes (and their several kinds).
    assert {s for *_, s in routes} == {"trip", "booking", "trip-query", "trip-body"}
    assert len(routes) >= 40


# --- 1. the route matrix ---------------------------------------------------------------------


@dataclass
class Outcome:
    method: str
    path: str
    status: int
    body: Any


async def sweep(scene: Scene, who: Browser, **changes: str) -> list[Outcome]:
    """Every trip and booking route, called by ``who``, each with the database checked
    afterwards when the call could write."""
    out = []
    for _, method, template, _ in classified(scene):
        before = await snapshot(scene.engine, TRIP_TABLES) if method != "GET" else None
        got = await call(who, scene, method, template, **changes)
        if before is not None:
            assert changed(before, await snapshot(scene.engine, TRIP_TABLES)) == {}, (
                method,
                template,
            )
        body = (
            got.json()
            if got.headers.get("content-type", "").startswith("application/json")
            else None
        )
        out.append(Outcome(method, template, got.status_code, body))
    return out


def owner_only_routes(scene: Scene) -> set[tuple[str, str]]:
    return {
        (method, template)
        for route, method, template, _ in classified(scene)
        if "auth" in guards_of(route)
    }


@pytest.mark.parametrize("who", ["outsider", "peer_b", "ex"])
async def test_the_matrix_outsiders_find_no_trip_and_change_nothing(scene: Scene, who: str) -> None:
    """An outsider, a member of the same owner's other trip, and someone taken off the
    trip: 404 on every route that names the trip or a booking on it, the same 404 as for
    a trip that is not there, and not one row changed anywhere."""
    person: Browser = getattr(scene, who)
    before = await snapshot(scene.engine)
    real = await sweep(scene, person)
    ghost = await sweep(scene, person, trip_id=str(uuid4()), booking_id=str(uuid4()))
    assert changed(before, await snapshot(scene.engine)) == {}
    for one, nothing in zip(real, ghost, strict=True):
        where = (who, one.method, one.path)
        assert one.status == 404, (where, one.body)
        # Nothing tells a trip that exists from one that does not.
        assert (one.status, one.body) == (nothing.status, nothing.body), where


async def test_the_matrix_a_guest_of_another_trip_finds_nothing_either(scene: Scene) -> None:
    """A guest on trip B only: the guest rule shuts the owner-only routes (403, the same
    for any id), every other route is the same 404 an outsider gets."""
    before = await snapshot(scene.engine)
    guest = scene.guest_b
    real = await sweep(scene, guest)
    ghost = await sweep(scene, guest, trip_id=str(uuid4()), booking_id=str(uuid4()))
    assert changed(before, await snapshot(scene.engine)) == {}
    closed = owner_only_routes(scene)
    assert closed  # the owner-only routes exist
    for one, nothing in zip(real, ghost, strict=True):
        where = (one.method, one.path)
        if where in closed:
            assert (one.status, one.body) == (403, {"detail": GUEST_MESSAGE}), where
        else:
            assert one.status == 404, (where, one.body)
        assert (one.status, one.body) == (nothing.status, nothing.body), where


async def test_the_matrix_members_are_refused_exactly_the_owners_routes(scene: Scene) -> None:
    """A member of the trip: 403 on every route only the owner may use, changing nothing;
    and none of the routes a member may use says "not found" about a real trip."""
    before = await snapshot(scene.engine)
    closed = owner_only_routes(scene)
    for who in (scene.member, scene.guest_a):
        guest = who is scene.guest_a
        for _, method, template, _ in classified(scene):
            if (method, template) not in closed:
                continue
            got = await call(who, scene, method, template)
            want = GUEST_MESSAGE if guest else MONEY_MESSAGE
            assert (got.status_code, got.json()["detail"]) == (403, want), (guest, method, template)
    assert changed(before, await snapshot(scene.engine)) == {}


async def test_the_matrix_control_the_owner_gets_through_every_route(scene: Scene) -> None:
    """Without this the refusals above could be bad calls. The owner makes the very same
    calls and none is stopped by the access check or by the request's shape."""
    ordered = sorted(
        classified(scene),
        key=lambda r: (
            r[1] == "DELETE",
            r[2] == f"{T}",
            r[2].endswith("/members/{member_id}"),
            # The owner's edit of the insurance sends no cost, so log it first.
            (r[1], r[2]) == ("PUT", f"{T}/covers/{{cover_id}}"),
        ),
    )
    for _, method, template, _ in ordered:
        got = await call(scene.owner, scene, method, template)
        detail = got.json().get("detail", "") if got.status_code >= 400 else ""
        assert got.status_code != 422, (method, template, detail)
        assert detail not in ("no trip with that id", "no booking with that id"), (method, template)


# --- 2. guests are shut out of the whole app --------------------------------------------------

# The only routes a guest may use, written out here on purpose rather than read from the
# code: seeing who they are, signing out, and opening the trips shared with them.
GUEST_MAY = {
    ("GET", "/api/me"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/travel/trips"),
    ("POST", "/api/travel/invites/{token}/accept"),
    ("GET", "/api/travel/photos/{photo_id}"),
    ("GET", "/api/travel/places/search"),
    ("GET", "/api/travel/places/{place_id}"),
    ("GET", "/api/travel/places/{place_id}/photo"),
    ("GET", "/api/travel/currency"),
    ("GET", T),
    ("PUT", f"{T}/notes"),
    ("PUT", f"{T}/days/{{day}}"),
    ("PUT", f"{T}/stops"),
    ("PUT", f"{T}/getting-around"),
    ("PUT", f"{T}/packing"),
    ("POST", f"{T}/packing/suggest"),
    ("PUT", f"{T}/todos"),
    ("POST", f"{T}/prep/dismiss"),
    ("DELETE", f"{T}/prep/dismiss/{{key}}"),
    ("POST", f"{T}/covers"),
    ("PUT", f"{T}/covers/{{cover_id}}"),
    ("DELETE", f"{T}/covers/{{cover_id}}"),
    ("GET", f"{T}/weather"),
    ("GET", f"{T}/ideas"),
    ("GET", f"{T}/places"),
    ("GET", f"{T}/days/{{day}}/hops"),
    ("GET", f"{T}/days/{{day}}/hops/{{start_id}}/{{end_id}}"),
    ("POST", f"{T}/bookings"),
    ("POST", f"{T}/screenshot"),
    ("PUT", B),
    ("DELETE", B),
    ("PUT", f"{B}/move"),
    ("PUT", f"{B}/place"),
    ("GET", f"{T}/members"),
    ("DELETE", f"{T}/members/{{member_id}}"),
    ("GET", f"{T}/activity"),
}
# Routes that need no session: sign-in itself, what the sign-in page needs, the one-time
# links (Gmail, the read-only trip link) and the health check.
PUBLIC = {
    ("GET", "/api/config"),
    ("POST", "/api/auth/telegram"),
    ("POST", "/api/auth/webapp"),
    ("GET", "/api/auth/telegram/callback"),
    ("GET", "/api/shared/trips/{token}"),
    ("GET", "/api/shared/trips/{token}/photo"),
    ("GET", "/api/email/link"),
    ("GET", "/api/email/gmail/start"),
    ("GET", "/api/email/gmail/callback"),
}
# Checked by the owner's token or session themselves, and a stranger sees "not found".
HIDDEN = {("GET", "/api/ops/report"), ("GET", "/api/ops/costs"), ("POST", "/api/ops/tickets")}
VERBS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def blank_path(template: str) -> str:
    return re.sub(r"\{[^}]+\}", UNKNOWN, template)


async def test_a_guest_gets_nothing_outside_the_trips_shared_with_them(scene: Scene) -> None:
    """Every /api route, every verb. The routes a guest may use are the list above; any
    other is 403 with the guest message (404 for the hidden ops routes, 405 for a verb the
    path does not take), whether it reads or writes, with a good session and CSRF token."""
    guest = scene.guest_b
    app = scene.world.app
    anon = scene.world.browser()
    # Signing out ends the session, so it is tried last.
    routes = sorted(api_routes(app, "/api"), key=lambda r: r.path == "/api/auth/logout")
    before = await snapshot(scene.engine)
    served: set[tuple[str, str]] = set()
    public: set[tuple[str, str]] = set()
    for route in routes:
        path = blank_path(route.path)
        for verb in VERBS:
            key = (verb, route.path)
            sent: dict[str, Any] | None = {} if verb in {"POST", "PUT", "PATCH"} else None
            got = await guest.client.request(
                verb,
                path,
                headers={"Origin": ORIGIN, "X-CSRF-Token": guest.csrf},
                json=sent,
            )
            if verb not in methods_of(route):
                # The wrong verb for this path (another route may take it).
                continue
            if key in GUEST_MAY:
                served.add(key)
                assert got.status_code != 403 or got.json()["detail"] != GUEST_MESSAGE, key
                continue
            nobody = await anon.client.request(verb, path, headers={"Origin": ORIGIN}, json=sent)
            if key in PUBLIC:
                public.add(key)
                # No better and no worse than anyone not signed in.
                assert got.status_code == nobody.status_code, (key, got.status_code)
                continue
            if key in HIDDEN:
                assert (got.status_code, nobody.status_code) == (404, 404), key
                continue
            assert nobody.status_code == 401, (key, "is open to anyone", nobody.status_code)
            assert (got.status_code, got.json()) == (403, {"detail": GUEST_MESSAGE}), key
    assert served == GUEST_MAY, "GUEST_MAY names a route that is gone"
    assert public == PUBLIC, "PUBLIC names a route that is gone"
    assert changed(before, await snapshot(scene.engine)) == {}


async def test_a_guest_cannot_reach_a_route_with_the_wrong_verb(scene: Scene) -> None:
    """The verbs a path does not take never answer a guest with data."""
    guest = scene.guest_b
    taken: dict[str, set[str]] = {}
    for route in api_routes(scene.world.app, "/api"):
        taken.setdefault(route.path, set()).update(methods_of(route))
    for path, verbs in taken.items():
        for verb in set(VERBS) - verbs:
            got = await guest.client.request(
                verb,
                blank_path(path),
                headers={"Origin": ORIGIN, "X-CSRF-Token": guest.csrf},
            )
            assert got.status_code in {403, 404, 405}, (verb, path, got.status_code)


async def test_a_guest_cannot_find_a_route_the_app_does_not_list(scene: Scene) -> None:
    guest = scene.guest_b
    for path in ("/api/", "/api/admin", "/api/travel", "/api/travel/trips/", "/api/users/me"):
        got = await guest.get(path)
        assert got.status_code in {307, 308, 403, 404, 405}, (path, got.status_code)
        assert "Tokyo" not in got.text and "Osaka" not in got.text


async def test_a_guest_keeps_their_session_only_until_it_ends(scene: Scene) -> None:
    """Signing out ends a guest's session for good, and a stolen cookie is no better."""
    guest = scene.guest_a
    cookie = guest.client.cookies.get("nexus_session")
    assert cookie
    assert (await guest.send("POST", "/api/auth/logout")).status_code == 204
    thief = scene.world.browser()
    thief.client.cookies.set("nexus_session", cookie)
    assert (await thief.get("/api/me")).status_code == 401
    assert (await thief.get(scene.a)).status_code == 401


# --- 3. money never reaches a member ------------------------------------------------------------


SESSION_ROUTES = {("POST", "/api/auth/logout"), ("POST", "/api/travel/invites/{token}/accept")}


async def owners_money(scene: Scene) -> Any:
    """What only the owner sees on trip A: budget, spending, who owes what, costs."""
    page = (await scene.owner.get(scene.a)).json()
    assert page["trip"]["budget"]["amount"].startswith(BUDGET)
    assert next(b for b in page["bookings"] if b["id"] == scene.dinner)["cost"] is not None
    assert page["paid_by_others"] and page["spending"]["spent"]
    assert next(c for c in page["covers"] if c["id"] == scene.cover)["cost"] is not None
    return {
        key: page[key]
        for key in ("spending", "saving", "owed", "items", "paid_by_others", "balances", "to_split")
    } | {
        "budget": page["trip"]["budget"],
        "cover": [c for c in page["covers"] if c["id"] == scene.cover],
        "costs": {
            b["id"]: b["cost"] for b in page["bookings"] if b["id"] in (scene.dinner, scene.lunch)
        },
    }


def trip_auth_routes(scene: Scene) -> list[tuple[APIRoute, str]]:
    return [
        (route, method)
        for route in api_routes(scene.world.app, "/api")
        for method in methods_of(route)
        if "trip" in guards_of(route)
    ]


def test_the_money_check_itself_catches_money() -> None:
    """The recursive check is not blind: it flags what it should and passes what it should."""
    leaky = {
        "trip": {"budget": {"amount": "1"}, "planned": {"Dining": "1"}, "notes": "x"},
        "bookings": [{"cost": {"amount": "2"}, "logged": False}],
        "spending": {"spent": 3},
        "deep": [[{"set_aside": "4"}]],
        "home": "5",
        "net": 6,
        "a_split": ["x"],
    }
    assert sorted(money_keys(leaky)) == sorted(
        [
            "$.trip.budget", "$.trip.budget.amount", "$.trip.planned",
            "$.bookings[0].cost", "$.bookings[0].cost.amount", "$.spending", "$.spending.spent",
            "$.deep[0][0].set_aside", "$.home", "$.net", "$.a_split",
        ]
    )  # fmt: skip
    clean: dict[str, Any] = {
        "budget": None, "cost": None, "planned": {}, "owed": [], "has_budget": False,
        "split_evenly": True, "internet": "x", "logged": False, "title": "Tokyo",
    }  # fmt: skip
    assert list(money_keys(clean)) == []
    assert list(money_keys({"split_evenly": False})) == ["$.split_evenly"]


async def test_nothing_a_member_can_read_or_write_carries_the_owners_money(scene: Scene) -> None:
    """Every route a member (or guest) may use, GET and write alike, with the owner's
    real figures everywhere on the trip: no money-like key holds anything, and none of the
    figures is in any response."""
    routes = trip_auth_routes(scene)
    owner_money = await owners_money(scene)
    # Signing out and joining by invite have their own tests.
    keys = {(method, route.path) for route, method in routes} - SESSION_ROUTES
    assert keys <= {*CALLS, *OWN_CALLS}, keys - {*CALLS, *OWN_CALLS}
    for who in (scene.member, scene.guest_a):
        back = await scene.owner.send(  # the last one moved the dinner off the day
            "PUT",
            f"/api/travel/bookings/{scene.dinner}/move",
            {"day": "2026-12-12", "after": scene.lunch},
        )
        assert back.status_code == 200
        fresh = (await who.send("POST", f"{scene.a}/bookings", PLAN)).json()["id"]
        fresh_cover = (await who.send("POST", f"{scene.a}/covers", COVER)).json()["id"]
        # Reads first, then the writes, then leaving the trip.
        order = sorted(keys, key=lambda k: (k[0] != "GET", k[0] == "DELETE", "members" in k[1]))
        for method, template in order:
            changes = {"booking_id": fresh} if (method, template) == ("DELETE", B) else {}
            if (method, template) == ("DELETE", f"{T}/covers/{{cover_id}}"):
                changes = {"cover_id": fresh_cover}
            if template.endswith("/members/{member_id}"):
                break  # leaving is tried last, below
            if template == "/api/travel/photos/{photo_id}":
                continue  # a photo is a picture, not a page: see the next test
            got = await call(who, scene, method, template, **changes)
            assert got.status_code < 400 or got.status_code == 502, (
                method, template, got.status_code, got.text[:200],
            )  # fmt: skip
            # /api/me is the viewer's own profile: their home currency is theirs.
            assert_no_money(got, f"{method} {template}", keys=template != "/api/me")
        # The page itself, after all those writes, still shows none of it.
        for url in (scene.a, "/api/travel/trips", f"{scene.a}/members", f"{scene.a}/activity"):
            assert_no_money(await who.get(url), url)
    # And the owner's own figures were never touched by any of it.
    assert await owners_money(scene) == owner_money


async def test_a_members_page_has_the_plan_and_no_trace_of_the_money(scene: Scene) -> None:
    got = await scene.member.get(scene.a)
    assert got.status_code == 200
    page = got.json()
    for key in ("spending", "saving", "booked", "booked_unlogged", "to_spend"):
        assert page[key] is None, key
    for key in ("owed", "items", "to_split", "just_mine", "paid_by_others", "balances"):
        assert page[key] == [], key
    assert_no_money(got, "trip page")
    # Not even the rest of the owner's account is on it: other trips, the expense's
    # counterparty, what the friend paid for.
    for word in ("Osaka", "Taxi", "Ann", OWNER_NOTE, "9999.99", "9,999.99", "SGD"):
        if word != "Ann":  # a companion is part of the plan
            assert word not in got.text, word
    listed = await scene.member.get("/api/travel/trips")
    assert [t["destination"] for t in listed.json()] == ["Tokyo"]
    assert "Osaka" not in listed.text and "9999.99" not in listed.text
    assert "9,999.99" not in listed.text
    # The Prep tab is the plan's: to-dos and cover are there, the cover's cost is not.
    assert [(t["text"], t["due"]) for t in page["todos"]] == [("Get yen", "2026-12-08")]
    [cover] = page["covers"]
    assert (cover["name"], cover["reference"], cover["phone"]) == (
        "Harbour Cover", "TX-4471", "+65 6123 4567",
    )  # fmt: skip
    assert (cover["cost"], cover["logged"]) == (None, False)
    assert page["prep_suggestions"]


async def cover_cost_in_database(scene: Scene) -> Any:
    return await one(
        scene.engine, "SELECT cost_amount FROM trip_covers WHERE id = :id", id=UUID(scene.cover)
    )


async def test_other_people_cannot_read_or_change_the_trips_to_dos_and_cover(scene: Scene) -> None:
    """Someone with no part in trip A (an outsider, a member of the owner's other trip,
    someone taken off, a guest of the other trip) finds no to-dos or cover, whatever they
    send, and not one row moves. The owner's own other trip is no way in either."""
    a, b = scene.a, scene.b
    before = await snapshot(scene.engine)
    cost = await cover_cost_in_database(scene)
    for who in (scene.outsider, scene.peer_b, scene.ex, scene.guest_b):
        page = await who.get(a)
        assert (page.status_code, page.json()) == (404, {"detail": "no trip with that id"})
        for method, path, body in [
            ("PUT", f"{a}/todos", {"todos": [{"text": "Hacked"}]}),
            ("POST", f"{a}/covers", COVER),
            ("PUT", f"{a}/covers/{scene.cover}", {**COVER, "name": "Hacked"}),
            ("DELETE", f"{a}/covers/{scene.cover}", None),
            ("POST", f"{a}/covers/{scene.cover}/log", None),
            ("POST", f"{a}/prep/dismiss", {"key": "money"}),
            ("DELETE", f"{a}/prep/dismiss/money", None),
        ]:
            got = await who.send(method, path, body)
            want = {403, 404} if who is scene.guest_b else {404}
            assert got.status_code in want, (who, method, path, got.status_code)
            assert (
                "Harbour" not in got.text and COVER_COST not in got.text and "yen" not in got.text
            )
    # A trip they ARE on is no way to the cover of trip A, nor is the owner's other trip.
    for who, path in ((scene.peer_b, b), (scene.owner, b)):
        for method, tail, body in [
            ("PUT", f"/covers/{scene.cover}", COVER),
            ("DELETE", f"/covers/{scene.cover}", None),
        ]:
            got = await who.send(method, path + tail, body)
            assert got.status_code == 404, (who, method, tail)
    assert (await scene.owner.send("POST", f"{b}/covers/{scene.cover}/log")).status_code == 404
    assert changed(before, await snapshot(scene.engine)) == {}
    assert await cover_cost_in_database(scene) == cost
    page = (await scene.owner.get(a)).json()
    assert [c["name"] for c in page["covers"]] == ["Harbour Cover"]
    assert [t["text"] for t in page["todos"]] == ["Get yen"]
    assert (await scene.owner.get(b)).json()["covers"] == []

    # The database itself refuses a cover on someone else's trip.
    stranger = await one(
        scene.engine, "SELECT id FROM users WHERE telegram_user_id = :t", t=OUTSIDER_ID
    )
    with pytest.raises(IntegrityError):
        async with scene.uow() as tx:
            await tx.trips.insert_cover(
                Cover(
                    uuid4(),
                    UserId(stranger),
                    UUID(scene.trip_a),
                    CoverDraft(CoverKind.OTHER, "Planted"),
                    None,
                    NOW,
                    NOW,
                )
            )


async def test_a_member_and_a_guest_edit_the_to_dos_and_never_see_a_cover_cost(
    scene: Scene,
) -> None:
    """To-dos and cover are the plan's, so a member or a guest reads and edits them like
    packing. What a cover cost, and the expense it was logged as, are the owner's: they
    are never in what they read, can't be set by them, and survive their edits."""
    a = scene.a
    cost = await cover_cost_in_database(scene)
    for who, name in ((scene.member, "Sam"), (scene.guest_a, "Gus")):
        put = await who.send("PUT", f"{a}/todos", {"todos": [{"text": f"{name}'s to-do"}]})
        assert put.status_code == 200, put.text
        assert [t["text"] for t in put.json()["todos"]] == [f"{name}'s to-do"]
        assert_no_money(put, "PUT todos")
        mine = await who.send("POST", f"{a}/covers", {"kind": "visa", "name": f"{name}'s visa"})
        assert mine.status_code == 201 and mine.json()["cost"] is None
        edit = await who.send(
            "PUT", f"{a}/covers/{scene.cover}", {**COVER, "phone": "+65 6000 0000"}
        )
        assert edit.status_code == 200, edit.text
        assert (edit.json()["cost"], edit.json()["logged"]) == (None, False)
        assert_no_money(edit, "PUT cover")
        page = await who.get(a)
        assert_no_money(page, "trip page")
        seen = next(c for c in page.json()["covers"] if c["id"] == scene.cover)
        assert (seen["cost"], seen["logged"], seen["phone"]) == (None, False, "+65 6000 0000")
        # Not to set, not to log, whatever the spelling.
        for body in ({**COVER, "cost": "1"}, {**COVER, "currency": "USD"}, {**COVER, "cost": " "}):
            if body.get("cost") == " ":
                assert (await who.send("POST", f"{a}/covers", body)).status_code == 201
                continue
            assert (await who.send("POST", f"{a}/covers", body)).status_code == 403
            assert (await who.send("PUT", f"{a}/covers/{scene.cover}", body)).status_code == 403
        logged = await who.send("POST", f"{a}/covers/{scene.cover}/log")
        assert logged.status_code == 403
        assert logged.json()["detail"] == (GUEST_MESSAGE if who is scene.guest_a else MONEY_MESSAGE)
    # The owner's cost is as they left it, nothing was logged, and the ledger is untouched.
    assert await cover_cost_in_database(scene) == cost
    assert (
        await one(
            scene.engine,
            "SELECT logged_transaction_id FROM trip_covers WHERE id = :id",
            id=UUID(scene.cover),
        )
        is None
    )
    page = (await scene.owner.get(a)).json()
    mine = next(c for c in page["covers"] if c["id"] == scene.cover)
    assert mine["cost"]["amount"].startswith(COVER_COST) and mine["logged"] is False
    # What they changed is in the activity, without a figure.
    feed = (await scene.owner.get(f"{a}/activity")).text
    assert "to-do list" in feed and "cover and documents" in feed
    for secret in SECRETS:
        assert secret not in feed


# --- 4. the owner's ledger stays the owner's ----------------------------------------------------

LEDGER = (
    "transactions", "splits", "settlements", "transaction_revisions", "transaction_sources",
    "trip_links", "trip_paid_by_others", "budgets", "categories", "wallets", "category_rules",
    "bills", "subscriptions", "memories", "chat_log",
)  # fmt: skip


async def test_a_member_cannot_make_the_owners_ledger_change(scene: Scene) -> None:
    """Every way a member could try to put money into, or take it out of, the owner's
    ledger or their own, through the trip. Each is refused, and not one row moves."""
    member = scene.member
    own = await make_trip(member, destination="Kyoto")  # the member's own trip, for tricks
    mine = (
        await member.send(
            "POST", "/api/transactions",
            {"direction": "out", "amount": "12.34", "date": "2026-09-21", "counterparty": "Bus"},
        )
    ).json()["id"]  # fmt: skip
    run = await finished_research(
        lambda: scene.uow(), UserId(UUID((await member.get(f"{scene.a}/members")).json()[1]["id"]))
    )
    before = await snapshot(scene.engine)
    a = scene.a
    price = {"cost": "5.55"}
    attempts: list[tuple[str, str, Any, set[int]]] = [
        # a price on a new or edited entry, in a currency or not
        ("POST", f"{a}/bookings", {**PLAN, **price}, {403}),
        ("POST", f"{a}/bookings", {**PLAN, "currency": "USD"}, {403}),
        ("POST", f"{a}/bookings", {**PLAN, "cost": " 7 ", "currency": "JPY"}, {403}),
        ("POST", f"{a}/bookings", {**PLAN, "cost": "0"}, {403}),
        ("PUT", f"/api/travel/bookings/{scene.dinner}", {**DINNER, **price}, {403}),
        ("PUT", f"/api/travel/bookings/{scene.dinner}", {**DINNER, "currency": "EUR"}, {403}),
        ("PUT", f"/api/travel/bookings/{scene.lunch}", {**PLAN, "cost": "1"}, {403}),
        # smuggled fields: the ledger and the trip are not in a booking's shape
        ("POST", f"{a}/bookings", {**PLAN, "transaction_id": scene.taxi}, {422}),
        ("PUT", f"/api/travel/bookings/{scene.dinner}", {**DINNER, "transaction_id": None}, {422}),
        ("PUT", f"/api/travel/bookings/{scene.dinner}", {**DINNER, "user_id": UNKNOWN}, {422}),
        ("PUT", f"{a}/notes", {"notes": "x", "budget": "1"}, {422}),
        ("PUT", f"{a}/packing", {**PACKING, "set_aside": "1"}, {422}),
        ("PUT", f"{a}/days/2026-12-11", {"label": "x", "planned": {"Food": "1"}}, {422}),
        ("PUT", f"{a}/stops", {"stops": [], "budget": "1"}, {422}),
        ("PUT", f"{a}/getting-around", {"by": "car", "split_evenly": False}, {422}),
        # the trip's own settings
        ("PUT", a, {**TRIP, "budget": "1.11"}, {403}),
        ("PUT", f"{a}/split-evenly", {"on": False}, {403}),
        ("POST", f"{a}/photo", {"choice": "off"}, {403}),
        # research ideas into the owner's trip, from the member's own research
        ("POST", f"/api/travel/research/{run}/ideas", {"trip_id": scene.trip_a, "areas": ["Asakusa"]}, {403}),  # noqa: E501
        # expenses linked or unlinked, the member's own or the owner's
        ("POST", f"{a}/expenses/{mine}", None, {403}),
        ("POST", f"{a}/expenses/{scene.taxi}", None, {403}),
        ("DELETE", f"{a}/expenses/{scene.taxi}", None, {403}),
        ("POST", f"/api/travel/trips/{own}/expenses/{scene.taxi}", None, {404}),
        ("DELETE", f"/api/travel/trips/{own}/expenses/{scene.taxi}", None, {404}),
        # splitting, settling and what others paid
        ("POST", f"{a}/split", {"all": True}, {403}),
        ("POST", f"{a}/split", {"transaction_ids": [mine]}, {403}),
        ("POST", f"/api/travel/trips/{own}/split", {"transaction_ids": [scene.taxi]}, {200, 404, 422}),  # noqa: E501
        ("POST", f"{a}/keep-mine", {"transaction_ids": [scene.taxi]}, {403}),
        ("POST", f"{a}/settle", {"person": "Ann"}, {403}),
        ("POST", f"{a}/settle", {"person": "Ann", "log": False}, {403}),
        ("POST", f"{a}/paid-by-others", {"person": "Ann", "amount": "99"}, {403}),
        ("PUT", f"{a}/paid-by-others/{scene.payment}", {"person": "Ann", "amount": "1"}, {403}),
        ("DELETE", f"{a}/paid-by-others/{scene.payment}", None, {403}),
        # the owner's payment, through the member's own trip
        ("PUT", f"/api/travel/trips/{own}/paid-by-others/{scene.payment}", {"person": "Ann", "amount": "1"}, {404, 422}),  # noqa: E501
        ("DELETE", f"/api/travel/trips/{own}/paid-by-others/{scene.payment}", None, {404}),
        # sharing and inviting
        ("POST", f"{a}/share", {}, {403}),
        ("POST", f"{a}/invites", None, {403}),
    ]  # fmt: skip
    for method, path, body, want in attempts:
        got = await member.send(method, path, body)
        assert got.status_code in want, (method, path, got.status_code, got.text[:200])
        if got.status_code == 200:  # "skipped: not an expense on this trip", nothing done
            assert got.json()["done"] == [], (method, path)
    assert changed(before, await snapshot(scene.engine)) == {}


async def logged_booking(scene: Scene, name: str) -> str:
    """An entry the owner priced and logged as an expense (the taxi)."""
    made = await scene.owner.send(
        "POST", f"{scene.a}/bookings", {**PLAN, "name": name, "cost": "42.42"}
    )
    async with scene.uow() as tx:
        await tx.trips.set_booking(
            UserId(UUID(scene.owner_id)), UUID(made.json()["id"]),
            trip_id=UUID(scene.trip_a), transaction_id=UUID(scene.taxi),
        )  # fmt: skip
        await tx.commit()
    return str(made.json()["id"])


async def test_what_a_member_may_do_to_the_plan_leaves_the_ledger_alone(scene: Scene) -> None:
    """The things a member may do, even the ones next to money (an entry that was logged
    as an expense, a screenshot full of prices, deleting an entry): the plan changes, the
    ledger, the splits, what is owed and the costs the owner set do not."""
    ledger = await snapshot(scene.engine, LEDGER)
    owner_money = await owners_money(scene)
    for who in (scene.member, scene.guest_a):
        a = scene.a
        edited = await who.send(
            "PUT", f"/api/travel/bookings/{scene.dinner}", {**DINNER, "at": "21:00", "note": "x"}
        )
        assert edited.status_code == 200
        moved = await who.send(
            "PUT", f"/api/travel/bookings/{scene.dinner}/move", {"day": "2026-12-15"}
        )
        assert moved.status_code == 200
        shot = await who.send("POST", f"{a}/screenshot", {"image": IMAGE, "mime_type": "image/png"})
        assert shot.status_code == 200, shot.text
        assert all(b["cost"] is None and b["logged"] is False for b in shot.json()["added"])
        assert "64,500" not in shot.text and "64500" not in shot.text
        # Deleting an entry the owner priced and logged leaves the expense in the ledger.
        priced = await logged_booking(scene, f"Tour {who is scene.guest_a}")
        assert (await who.send("DELETE", f"/api/travel/bookings/{priced}")).status_code == 204
    assert changed(ledger, await snapshot(scene.engine, LEDGER)) == {}
    assert await owners_money(scene) == owner_money
    # Every entry with a price is one the owner priced; what the screenshots added has none.
    priced_rows = await column(
        scene.engine, "SELECT title FROM trip_bookings WHERE amount IS NOT NULL"
    )
    assert sorted(priced_rows) == ["Castle", "Dinner at Sushi Ten"]
    added = await one(
        scene.engine, "SELECT count(*) FROM trip_bookings WHERE title LIKE 'Hotel Kumo%'"
    )
    assert added >= 1


# --- 5. tricks across trips ---------------------------------------------------------------------


async def test_a_member_cannot_move_or_reach_entries_across_trips(scene: Scene) -> None:
    """A member of trip A, who has a trip of their own, tries to move A's entries into the
    owner's trip B or their own trip, to move entries after another trip's entries, and to
    edit, delete, link or attach B's entries. Everything is refused; nothing changes."""
    member = scene.member
    own = await make_trip(member, destination="Kyoto")
    mine = (
        await member.send(
            "POST", f"/api/travel/trips/{own}/bookings",
            {"kind": "activity", "name": "Shrine", "day": "2026-12-12"},
        )
    ).json()["id"]  # fmt: skip
    before = await snapshot(scene.engine)
    day = {"day": "2026-12-14"}
    base = "/api/travel/bookings"
    attempts: list[tuple[str, str, Any, set[int]]] = [
        # moving A's entry "after" an entry of another trip, to land in that trip
        ("PUT", f"{base}/{scene.dinner}/move", {"day": "2026-12-14", "after": scene.b_booking}, {404}),  # noqa: E501
        ("PUT", f"{base}/{scene.dinner}/move", {"day": "2026-12-12", "after": mine}, {404}),
        ("PUT", f"{base}/{mine}/move", {"day": "2026-12-12", "after": scene.dinner}, {404}),
        ("PUT", f"{base}/{mine}/move", {"day": "2026-12-14", "after": scene.b_booking}, {404}),
        # B's entries, by id
        ("PUT", f"{base}/{scene.b_booking}/move", day, {404}),
        ("PUT", f"{base}/{scene.b_booking}", {"kind": "activity", "name": "Hacked"}, {404}),
        ("PUT", f"{base}/{scene.b_booking}/place", {"place_id": "fakePlaceNoodle01"}, {404}),
        ("DELETE", f"{base}/{scene.b_booking}", None, {404}),
        ("PUT", f"{base}/{scene.b_booking}/trip", {"trip_id": scene.trip_a}, {404}),
        ("PUT", f"{base}/{scene.b_booking}/trip", {"trip_id": own}, {404}),
        ("PUT", f"{base}/{scene.b_booking}/trip", {"trip_id": None}, {404}),
        # A's entries cannot be attached, detached or handed to another trip: owner only
        ("PUT", f"{base}/{scene.dinner}/trip", {"trip_id": scene.trip_b}, {403}),
        ("PUT", f"{base}/{scene.dinner}/trip", {"trip_id": own}, {403}),
        ("PUT", f"{base}/{scene.dinner}/trip", {"trip_id": None}, {403}),
        # the member's own entry into the owner's trip, or onto a trip it is not on
        ("PUT", f"{base}/{mine}/trip", {"trip_id": scene.trip_a}, {404}),
        ("PUT", f"{base}/{mine}/trip", {"trip_id": scene.trip_b}, {404}),
        # a trip id in an entry's body is not a field
        ("POST", f"{scene.a}/bookings", {**PLAN, "trip_id": scene.trip_b}, {422}),
        ("PUT", f"{base}/{scene.dinner}", {**DINNER, "trip_id": scene.trip_b}, {422}),
        # B's trip
        ("POST", f"{scene.b}/bookings", PLAN, {404}),
        ("POST", f"{scene.b}/screenshot", {"image": IMAGE, "mime_type": "image/png"}, {404}),
        ("GET", f"/api/travel/places/search?q=noodles&trip_id={scene.trip_b}", None, {404}),
        ("PUT", f"{scene.b}/notes", {"notes": "Hacked"}, {404}),
        # hops, naming B's entries under A's trip (and A's under B's)
        ("GET", f"{scene.a}/days/2026-12-14/hops/{scene.b_booking}/{scene.dinner}?mode=walk", None, {404}),  # noqa: E501
        ("GET", f"{scene.a}/days/2026-12-14/hops/{scene.dinner}/{scene.b_booking}?mode=walk", None, {404}),  # noqa: E501
        ("GET", f"{scene.b}/days/2026-12-14/hops/{scene.dinner}/{scene.lunch}?mode=walk", None, {404}),  # noqa: E501
    ]  # fmt: skip
    for method, path, body, want in attempts:
        got = await member.send(method, path, body)
        assert got.status_code in want, (method, path, got.status_code, got.text[:200])
        assert "Castle" not in got.text and B_COST not in got.text, (method, path)
    assert changed(before, await snapshot(scene.engine)) == {}
    # B's entry is exactly as the owner left it.
    page = (await scene.owner.get(scene.b)).json()
    [castle] = page["bookings"]
    assert (castle["id"], castle["title"], castle["day"]) == (
        scene.b_booking,
        "Castle",
        "2026-12-14",
    )
    assert castle["cost"]["amount"].startswith(B_COST)


async def test_a_member_cannot_use_the_trip_to_spy_on_the_owners_other_trips(scene: Scene) -> None:
    """A screenshot read onto trip A must not say what is on the owner's other trips:
    an entry the owner already has on trip B is not "already on the itinerary" for A."""
    shot = {"image": IMAGE, "mime_type": "image/png"}
    # The owner reads the same screenshot onto trip B first.
    first = await scene.owner.send("POST", f"{scene.b}/screenshot", shot)
    assert first.status_code == 200 and first.json()["added"], first.text
    for who in (scene.member,):
        got = await who.send("POST", f"{scene.a}/screenshot", shot)
        assert got.status_code == 200, got.text
        # What B holds is not A's business: nothing is "repeated", the entries go on A.
        assert got.json()["repeated"] == 0, got.json()["message"]
        assert "already on the itinerary" not in got.json()["message"]
        assert {b["trip_id"] for b in got.json()["added"]} == {scene.trip_a}
    # Within trip A the same screenshot is still only added once.
    again = await scene.member.send("POST", f"{scene.a}/screenshot", shot)
    assert again.json()["added"] == [] and again.json()["repeated"] == 4


# --- 6. invites ---------------------------------------------------------------------------------


async def test_a_spent_expired_or_cancelled_invite_adds_nobody_else(scene: Scene) -> None:
    world, owner = scene.world, scene.owner
    accept = "/api/travel/invites/{}/accept"
    token = (await scene.invite_to(scene.a))["token"]
    first = await scene.outsider.send("POST", accept.format(token))
    assert first.status_code == 200 and first.json()["new"] is True

    # Reuse by someone else after it was redeemed: the same words as for a bad link.
    before = await snapshot(scene.engine)
    for who in (scene.peer_b, scene.ex, scene.guest_b):
        used = await who.send("POST", accept.format(token))
        assert (used.status_code, used.json()) == (
            404,
            {"detail": "this invite is invalid, used or expired"},
        )
    nonsense = await scene.peer_b.send("POST", accept.format("x" * 43))
    assert nonsense.json() == used.json()
    assert changed(before, await snapshot(scene.engine)) == {}
    for who in (scene.peer_b, scene.ex, scene.guest_b):
        assert (await who.get(scene.a)).status_code == 404

    # Expired: seven days and a second on.
    old = (await scene.invite_to(scene.a))["token"]
    world.clock.now = NOW + timedelta(days=7, seconds=1)
    gone = await scene.ex.send("POST", accept.format(old))
    assert (gone.status_code, gone.json()) == (404, used.json())
    # ... and a guest cannot be made with it either.
    _, via_login = await sign_in(world, 977, trip_invite=old)
    assert via_login.status_code == 403
    world.clock.now = NOW
    assert (await scene.ex.get(scene.a)).status_code == 404

    # Cancelled before anyone used it.
    fresh = await scene.invite_to(scene.a)
    assert (await owner.send("DELETE", f"{scene.a}/invites/{fresh['id']}")).status_code == 204
    cancelled = await scene.ex.send("POST", accept.format(fresh["token"]))
    assert (cancelled.status_code, cancelled.json()) == (404, used.json())
    _, via_login = await sign_in(world, 977, trip_invite=fresh["token"])
    assert via_login.status_code == 403
    assert (await scene.ex.get(scene.a)).status_code == 404
    assert await role_of(scene, 977) is None


async def test_guessing_invite_links_is_rate_limited(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Twenty tries in ten minutes, then 429, whatever is tried, even a good link. Another
    person's tries are their own count. The window lets go after ten minutes."""
    accept = "/api/travel/invites/{}/accept"
    guesser = scene.outsider
    for n in range(20):
        got = await guesser.send("POST", accept.format(f"guess-{n}-{uuid4().hex}"))
        assert got.status_code == 404, n
    blocked = await guesser.send("POST", accept.format(f"guess-{uuid4().hex}"))
    assert blocked.status_code == 429
    good = (await scene.invite_to(scene.a))["token"]
    assert (await guesser.send("POST", accept.format(good))).status_code == 429
    assert (await guesser.get(scene.a)).status_code == 404  # not even a member by luck
    # A different person is not held up by it.
    assert (await scene.peer_b.send("POST", accept.format("guess"))).status_code == 404
    # The limiter keeps real time; let ten minutes go by.
    limits = scene.world.app.state.web.limits
    monkeypatch.setattr(limits, "_clock", lambda: utcnow() + timedelta(minutes=10, seconds=1))
    assert (await guesser.send("POST", accept.format(good))).status_code == 200


async def test_an_invite_for_one_trip_adds_nobody_to_another(scene: Scene) -> None:
    token_a = (await scene.invite_to(scene.a))["token"]
    joined = await scene.outsider.send("POST", f"/api/travel/invites/{token_a}/accept")
    assert joined.json() == {"trip_id": scene.trip_a, "new": True, "own": False}
    assert (await scene.outsider.get(scene.b)).status_code == 404
    assert (await scene.outsider.get(scene.a)).status_code == 200
    # The same through sign-in: a new guest gets trip A and nothing else.
    token_a2 = (await scene.invite_to(scene.a))["token"]
    guest, made = await sign_in(scene.world, 978, trip_invite=token_a2)
    assert made.json()["joined_trip"] == scene.trip_a
    assert [t["id"] for t in (await guest.get("/api/travel/trips")).json()] == [scene.trip_a]
    assert (await guest.get(scene.b)).status_code == 404
    # An invite from one of the owner's trips never carries the id of another trip.
    trips_of_invites = await column(scene.engine, select(trip_invites.c.trip_id))
    assert {str(t) for t in trips_of_invites} <= {scene.trip_a, scene.trip_b}


async def test_only_the_owner_makes_lists_and_cancels_invites(scene: Scene) -> None:
    before = await snapshot(scene.engine)
    for who, message in ((scene.member, MONEY_MESSAGE), (scene.guest_a, GUEST_MESSAGE)):
        for method, path in (
            ("POST", f"{scene.a}/invites"),
            ("GET", f"{scene.a}/invites"),
            ("DELETE", f"{scene.a}/invites/{scene.invite}"),
        ):
            got = await who.send(method, path)
            assert (got.status_code, got.json()["detail"]) == (403, message), (method, path)
    # Outsiders cannot even tell the trip is there.
    for who in (scene.outsider, scene.peer_b, scene.ex, scene.guest_b):
        for method, path in (
            ("POST", f"{scene.a}/invites"),
            ("GET", f"{scene.a}/invites"),
            ("DELETE", f"{scene.a}/invites/{scene.invite}"),
        ):
            assert (await who.send(method, path)).status_code in {403, 404}, (method, path)
    # The trip's owner cannot cancel an invite through another of their trips.
    wrong = await scene.owner.send("DELETE", f"{scene.b}/invites/{scene.invite}")
    assert wrong.status_code == 404
    # A member's own trip's invites are theirs only, and are not a way onto A.
    assert changed(before, await snapshot(scene.engine)) == {}
    own = await make_trip(scene.member, destination="Kyoto")
    made = await scene.member.send("POST", f"/api/travel/trips/{own}/invites")
    assert made.status_code == 201
    other = await scene.outsider.send("POST", f"/api/travel/invites/{made.json()['token']}/accept")
    assert other.json()["trip_id"] == own
    assert (await scene.outsider.get(scene.a)).status_code == 404


async def test_only_the_app_owners_invites_make_guests(scene: Scene) -> None:
    """The flag that lets a link create an account is set from who made the link, and
    nothing a client sends can set it."""
    own = await make_trip(scene.member, destination="Kyoto")
    theirs = (await scene.member.send("POST", f"/api/travel/trips/{own}/invites")).json()
    stranger, refused = await sign_in(scene.world, 979, trip_invite=theirs["token"])
    assert refused.status_code == 403
    assert (await stranger.get("/api/me")).status_code == 401
    assert await role_of(scene, 979) is None
    assert await may_create_guest(scene, theirs["id"]) is False
    assert await may_create_guest(scene, scene.invite) is True
    # The invite request takes no body: a flag sent along is ignored (not stored).
    sneaky = await scene.member.send(
        "POST", f"/api/travel/trips/{own}/invites", {"may_create_guest": True}
    )
    assert sneaky.status_code == 201
    assert await may_create_guest(scene, sneaky.json()["id"]) is False
    # The guest the owner's invite made cannot make invites at all.
    assert (await scene.guest_a.send("POST", f"{scene.a}/invites")).status_code == 403


async def test_the_owner_cannot_use_their_own_invite(scene: Scene) -> None:
    token = (await scene.invite_to(scene.a))["token"]
    own = await scene.owner.send("POST", f"/api/travel/invites/{token}/accept")
    assert own.status_code == 200
    assert own.json() == {"trip_id": scene.trip_a, "new": False, "own": True}
    members = await column(scene.engine, "SELECT member_id FROM trip_members")
    assert scene.owner_id not in {str(m) for m in members}
    # The link is not spent by it: someone else can still use it.
    assert (
        await scene.outsider.send("POST", f"/api/travel/invites/{token}/accept")
    ).status_code == 200


async def test_invite_links_are_never_stored_or_shown_whole(
    scene: Scene, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    made = await scene.invite_to(scene.a)
    token = made["token"]
    assert len(token) >= 40
    listed = await scene.owner.get(f"{scene.a}/invites")
    assert token not in listed.text
    assert all(set(i) == {"id", "created_at", "expires_at"} for i in listed.json())
    # Only a hash is kept: the link is in no column of any table.
    stored = await column(scene.engine, select(trip_invites.c.token_hash))
    assert token_hash(token) in stored and token not in stored
    assert await raw_secret_in_database(scene.engine, token) == []
    # Using it, signing in with it and failing with it write it nowhere either.
    await scene.outsider.send("POST", f"/api/travel/invites/{token}/accept")
    await scene.outsider.send("POST", f"/api/travel/invites/{token}/accept")
    await scene.peer_b.send("POST", f"/api/travel/invites/{token}/accept")
    await sign_in(scene.world, 980, trip_invite=token)
    assert await raw_secret_in_database(scene.engine, token) == []
    assert token not in caplog.text
    assert token not in (await scene.owner.get(f"{scene.a}/members")).text
    assert token not in (await scene.owner.get(f"{scene.a}/activity")).text
    # A session's token is the same: its hash is what is kept.
    cookie = scene.member.client.cookies.get("nexus_session")
    assert cookie and await raw_secret_in_database(scene.engine, cookie) == []


# --- 7. signing in with a trip invite -----------------------------------------------------------


async def role_of(scene: Scene, telegram_id: int) -> str | None:
    found = await one(
        scene.engine, select(users.c.role).where(users.c.telegram_user_id == telegram_id)
    )
    return None if found is None else str(found)


async def may_create_guest(scene: Scene, invite_id: str) -> Any:
    return await one(
        scene.engine,
        select(trip_invites.c.may_create_guest).where(trip_invites.c.id == UUID(invite_id)),
    )


async def test_a_trip_invite_never_changes_anyones_role(scene: Scene) -> None:
    """The owner, an ordinary member and a guest each sign in with trip invites (their own
    trip's, the owner's, an ordinary user's): they get the trip, and keep exactly the role,
    the access and the account they had."""
    world = scene.world
    own = await make_trip(scene.member, destination="Kyoto")
    members_invite = (await scene.member.send("POST", f"/api/travel/trips/{own}/invites")).json()[
        "token"
    ]

    # The app owner joins an ordinary user's trip: a member of it, still the owner.
    owner, response = await sign_in(world, OWNER, first="T", trip_invite=members_invite)
    assert response.json()["user"]["role"] == "owner" and response.json()["joined_trip"] == own
    seen = (await owner.get(f"/api/travel/trips/{own}")).json()
    assert seen["trip"]["role"] == "member" and seen["spending"] is None
    assert (await owner.send("POST", "/api/invites")).status_code == 200  # still the owner
    assert await role_of(scene, OWNER) == "owner"

    # An ordinary member joins the owner's trip B: still ordinary, still on the whole app.
    token_b = (await scene.invite_to(scene.b))["token"]
    member, response = await sign_in(world, MEMBER_ID, first="Sam", trip_invite=token_b)
    assert response.json()["user"]["role"] == "member"
    assert response.json()["joined_trip"] == scene.trip_b
    assert (await member.get("/api/transactions")).status_code == 200
    assert (await member.send("POST", "/api/invites")).status_code == 403  # not the owner
    assert await role_of(scene, MEMBER_ID) == "member"

    # A guest joins another trip with the owner's invite, or an ordinary user's: still a
    # guest, still shut out of everything but trips.
    token_a = (await scene.invite_to(scene.a))["token"]
    guest, response = await sign_in(world, GUEST_B_ID, first="Gil", trip_invite=token_a)
    assert (
        response.json()["user"]["role"] == "guest"
        and response.json()["joined_trip"] == scene.trip_a
    )
    second = (await scene.member.send("POST", f"/api/travel/trips/{own}/invites")).json()["token"]
    guest, response = await sign_in(world, GUEST_B_ID, first="Gil", trip_invite=second)
    assert response.json()["user"]["role"] == "guest" and response.json()["joined_trip"] == own
    assert (await guest.get("/api/transactions")).status_code == 403
    assert (await guest.send("POST", "/api/invites")).status_code == 403
    assert await role_of(scene, GUEST_B_ID) == "guest"
    assert (await guest.get(scene.a)).json()["trip"]["role"] == "member"


async def test_only_the_trips_made_guests_are_guests(scene: Scene) -> None:
    """Every guest account in the database is one an owner's trip invite made."""
    world = scene.world
    own = await make_trip(scene.member, destination="Kyoto")
    refused_token = (await scene.member.send("POST", f"/api/travel/trips/{own}/invites")).json()[
        "token"
    ]
    expired = (await scene.invite_to(scene.a))["token"]
    world.clock.now = NOW + timedelta(days=8)
    attempts = [
        ("an ordinary user's invite", 981, refused_token),
        ("an expired invite", 982, expired),
        ("a made-up invite", 983, "x" * 43),
        ("an empty invite", 984, ""),
    ]
    for what, who, token in attempts:
        _, response = await sign_in(world, who, trip_invite=token or None)
        assert response.status_code == 403, what
        assert await role_of(scene, who) is None, what
    world.clock.now = NOW
    guests = await column(
        scene.engine, select(users.c.telegram_user_id).where(users.c.role == "guest")
    )
    assert set(guests) == {GUEST_A_ID, GUEST_B_ID}


async def test_a_guest_cannot_become_a_full_user_with_an_app_invite(scene: Scene) -> None:
    """What happens when a guest signs in with an app invite. Documented behaviour: it is
    ignored. The guest stays a guest and the invite is not spent, so it still works for
    someone else. (A guest who should get the whole app needs a new account; nothing here
    upgrades one.)"""
    world = scene.world
    app_invite = (await scene.owner.send("POST", "/api/invites")).json()["url"].rsplit("/", 1)[-1]
    guest, response = await sign_in(world, GUEST_A_ID, first="Gus", invite=app_invite)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "guest"
    assert (await guest.get("/api/transactions")).status_code == 403
    assert (await guest.get("/api/home")).status_code == 403
    assert await role_of(scene, GUEST_A_ID) == "guest"
    spent = await one(scene.engine, "SELECT count(*) FROM invites WHERE redeemed_at IS NOT NULL")
    assert spent == 4  # the four people the scene invited, and not this guest
    # Not spent: a newcomer can still use it.
    _, newcomer = await sign_in(world, 985, invite=app_invite)
    assert newcomer.status_code == 200 and newcomer.json()["user"]["role"] == "member"


async def test_a_new_person_with_both_invites_is_a_member_and_on_the_trip(scene: Scene) -> None:
    app_invite = (await scene.owner.send("POST", "/api/invites")).json()["url"].rsplit("/", 1)[-1]
    trip_invite = (await scene.invite_to(scene.a))["token"]
    browser, response = await sign_in(scene.world, 986, invite=app_invite, trip_invite=trip_invite)
    assert response.json()["user"]["role"] == "member"
    assert response.json()["joined_trip"] == scene.trip_a
    assert (await browser.get("/api/transactions")).status_code == 200


async def test_a_full_trip_makes_no_guest(scene: Scene) -> None:
    """Ten people on a trip is the most. A link made while there was room fails once it
    is full, and must not leave a half-made guest account behind."""
    room = (await scene.invite_to(scene.b))["token"]
    for n in range(8):  # B has two on it already
        made = await register_user(
            scene.uow(), RegisterUser(telegram_user_id=7000 + n, home_currency="SGD")
        )
        async with scene.uow() as tx:
            await tx.trips.add_member(
                UserId(UUID(scene.owner_id)), UUID(scene.trip_b), made.user.id, None, NOW
            )
            await tx.commit()
    assert (await scene.owner.send("POST", f"{scene.b}/invites")).status_code == 422
    before = await snapshot(scene.engine)
    _, response = await sign_in(scene.world, 987, trip_invite=room)
    assert response.status_code == 422, response.text
    assert await role_of(scene, 987) is None
    assert changed(before, await snapshot(scene.engine)) == {}
    # The link is still open for when someone leaves.
    assert len((await scene.owner.get(f"{scene.b}/invites")).json()) == 1
    # Someone who can sign in anyway is not locked out by a full trip.
    _, plain = await sign_in(scene.world, OUTSIDER_ID, first="Zed", trip_invite=room)
    assert plain.status_code == 200 and plain.json()["joined_trip"] is None
    assert (await scene.outsider.get(scene.b)).status_code == 404


# --- 8. removal and leaving ---------------------------------------------------------------------


async def test_removing_a_member_shuts_every_door_at_once(scene: Scene) -> None:
    owner, a = scene.owner, scene.a
    for who, name in ((scene.member, "Sam"), (scene.guest_a, "Gus")):
        assert (await who.get(a)).status_code == 200
        assert (await owner.send("DELETE", f"{a}/members/{scene.ids[name]}")).status_code == 204
        # The very next request, on every route, is "no such trip" (or the guest rule).
        before = await snapshot(scene.engine)
        for _, method, template, _ in classified(scene):
            got = await call(who, scene, method, template)
            guest_rule = who is scene.guest_a and (got.status_code, got.json()["detail"]) == (
                403,
                GUEST_MESSAGE,
            )
            assert got.status_code == 404 or guest_rule, (name, method, template, got.status_code)
        assert changed(before, await snapshot(scene.engine)) == {}
        assert a.rsplit("/", 1)[-1] not in [
            t["id"] for t in (await who.get("/api/travel/trips")).json()
        ]
        assert (await who.get("/api/me")).status_code == 200  # their sign-in is still theirs
        assert (await owner.send("DELETE", f"{a}/members/{scene.ids[name]}")).status_code == 404


async def test_a_member_can_remove_only_themselves(scene: Scene) -> None:
    a, member = scene.a, scene.member
    owner_id, sam, gus, eve = (scene.ids[k] for k in ("T", "Sam", "Gus", "Eve"))
    before = await snapshot(scene.engine)
    for target in (owner_id, gus, eve, str(uuid4())):  # the owner, another member, no one
        got = await member.send("DELETE", f"{a}/members/{target}")
        assert (got.status_code, got.json()["detail"]) == (403, MONEY_MESSAGE), target
    for target in (owner_id, sam, str(uuid4())):  # a guest has no more say
        got = await scene.guest_a.send("DELETE", f"{a}/members/{target}")
        assert (got.status_code, got.json()["detail"]) == (403, MONEY_MESSAGE), target
    assert changed(before, await snapshot(scene.engine)) == {}
    # The owner cannot be removed from their own trip, by anyone, nor by naming another trip.
    assert (await scene.owner.send("DELETE", f"{a}/members/{owner_id}")).status_code == 404
    assert (await scene.owner.send("DELETE", f"{scene.b}/members/{sam}")).status_code == 404
    assert (await scene.peer_b.send("DELETE", f"{a}/members/{sam}")).status_code == 404
    assert (await scene.outsider.send("DELETE", f"{a}/members/{sam}")).status_code == 404
    assert changed(before, await snapshot(scene.engine)) == {}
    assert (await member.get(a)).status_code == 200
    # Leaving is allowed once, and what they changed stays.
    assert (await member.send("PUT", f"{a}/notes", {"notes": "Sam was here"})).status_code == 200
    assert (await member.send("DELETE", f"{a}/members/{sam}")).status_code == 204
    assert (await member.send("DELETE", f"{a}/members/{sam}")).status_code == 404
    assert (await scene.owner.get(a)).json()["trip"]["notes"] == "Sam was here"
    assert [m["name"] for m in (await scene.owner.get(f"{a}/members")).json()] == ["T", "Gus"]


async def test_leaving_a_trip_does_not_let_an_old_invite_back_in(scene: Scene) -> None:
    world, a = scene.world, scene.a
    token = (await scene.invite_to(a))["token"]
    pia = scene.peer_b
    assert (await pia.send("POST", f"/api/travel/invites/{token}/accept")).json()["new"] is True
    mine = next(m["id"] for m in (await pia.get(f"{a}/members")).json() if m["you"])
    assert (await pia.send("DELETE", f"{a}/members/{mine}")).status_code == 204

    # The spent link neither re-adds her by accepting nor by signing in with it.
    before = await snapshot(scene.engine)
    again = await pia.send("POST", f"/api/travel/invites/{token}/accept")
    assert again.status_code == 404
    _, signed = await sign_in(world, PEER_B_ID, first="Pia", trip_invite=token)
    assert signed.status_code == 200 and signed.json()["joined_trip"] is None
    after = await snapshot(scene.engine)
    assert {
        k: v for k, v in changed(before, after).items() if k not in {"users", "web_sessions"}
    } == {}
    assert (await pia.get(a)).status_code == 404

    # A new link from the owner does.
    new = (await scene.invite_to(a))["token"]
    back = await pia.send("POST", f"/api/travel/invites/{new}/accept")
    assert back.status_code == 200 and back.json() == {
        "trip_id": scene.trip_a,
        "new": True,
        "own": False,
    }
    assert (await pia.get(a)).status_code == 200


async def test_deleting_a_trip_takes_the_people_and_the_links_with_it(scene: Scene) -> None:
    await scene.member.send("PUT", f"{scene.a}/notes", {"notes": "Before"})  # some activity
    assert (await scene.owner.send("DELETE", scene.a)).status_code == 204
    for who in (scene.member, scene.guest_a):
        assert (await who.get(scene.a)).status_code in {404}
        assert (await who.get(f"{scene.a}/activity")).status_code == 404
    token_rows: dict[str, int] = {}
    for table in ("trip_members", "trip_invites", "trip_activity", "trip_bookings"):
        query = f"SELECT count(*) FROM {table} WHERE trip_id = :t"  # noqa: S608 - fixed names
        token_rows[table] = await one(scene.engine, query, t=scene.trip_a)
    assert token_rows == {
        "trip_members": 0,
        "trip_invites": 0,
        "trip_activity": 0,
        "trip_bookings": 0,
    }
    # Trip B and its people are untouched.
    assert (await scene.peer_b.get(scene.b)).status_code == 200
    assert (await scene.guest_b.get(scene.b)).status_code == 200


# --- 9. what people changed ---------------------------------------------------------------------

_MONEY_TALK = re.compile(
    r"\b(budget|cost|costs|spent|spending|expense|paid|pay|owe|owed|split|settle|settled|price|"
    r"amount|saving|set aside)\b|\d+\.\d{2}",
    re.IGNORECASE,
)


async def test_the_activity_feed_is_for_the_people_on_the_trip_and_has_no_money(
    scene: Scene,
) -> None:
    owner, a = scene.owner, scene.a
    # The owner does everything money-ish there is to do on a shared trip.
    taxi2 = (
        await owner.send(
            "POST", "/api/transactions",
            {"direction": "out", "amount": "66.66", "date": "2026-09-22", "counterparty": "Train"},
        )
    ).json()["id"]  # fmt: skip
    for method, path, body in [
        ("PUT", a, {**TRIP_A, "budget": "5555.55", "set_aside": "222.22"}),
        ("POST", f"{a}/expenses/{taxi2}", None),
        ("DELETE", f"{a}/expenses/{taxi2}", None),
        ("POST", f"{a}/expenses/{taxi2}", None),
        ("PUT", f"{a}/split-evenly", {"on": False}),
        ("PUT", f"{a}/split-evenly", {"on": True}),
        ("POST", f"{a}/keep-mine", {"transaction_ids": [taxi2]}),
        ("POST", f"{a}/keep-mine", {"transaction_ids": [taxi2], "keep": False}),
        ("POST", f"{a}/paid-by-others", {"person": "Ann", "amount": "88.88"}),
        ("PUT", f"{a}/paid-by-others/{scene.payment}", {"person": "Ann", "amount": "77.77"}),
        ("POST", f"{a}/split", {"all": True}),
        ("POST", f"{a}/settle", {"person": "Ann"}),
        ("POST", f"{a}/share", {}),
        ("POST", f"{a}/photo", {"choice": "off"}),
    ]:
        got = await owner.send(method, path, body)
        assert got.status_code < 400, (method, path, got.text)
    # ... and one plan edit, so the feed is not empty for want of trying.
    await owner.send("PUT", f"{a}/notes", {"notes": "Meet at the gate"})
    for who in (owner, scene.member, scene.guest_a):
        feed = await who.get(f"{a}/activity")
        assert feed.status_code == 200
        assert [(e["actor"], e["summary"]) for e in feed.json()] == [("T", "changed the notes")], (
            who
        )
        assert not _MONEY_TALK.search(feed.text), feed.text
        assert all(set(e) == {"actor", "summary", "at"} for e in feed.json())
        for secret in (*SECRETS, "5555.55", "5,555.55", "222.22", "88.88", "77.77", "66.66"):
            assert secret not in feed.text
    # The people not on the trip read none of it.
    for who in (scene.outsider, scene.peer_b, scene.ex, scene.guest_b):
        denied = await who.get(f"{a}/activity")
        assert (denied.status_code, denied.json()) == (404, {"detail": "no trip with that id"})
    anon = await scene.world.browser().get(f"{a}/activity")
    assert anon.status_code == 401


def hidden_characters(text_: str) -> list[str]:
    """Control, format and separator characters, which are invisible or flip a line."""
    return [c for c in text_ if unicodedata.category(c) in {"Cc", "Cf", "Zl", "Zp"}]


def chars(*codes: int) -> str:
    """Characters by code point, so no invisible ones sit in this file."""
    return "".join(map(chr, codes))


NASTY_FIRST_NAMES = {
    "right-to-left override": "Sam" + chars(0x202E) + "Evil" + chars(0x202C),
    "isolates": "Sam" + chars(0x2066) + "X" + chars(0x2069),
    "arabic letter mark": "Sam" + chars(0x061C),
    "word joiner": "T" + chars(0x2060),
    "byte order mark": "T" + chars(0xFEFF),
    "soft hyphen": "T" + chars(0x00AD),
    "zero width space": "T" + chars(0x200B),
    "line and paragraph separators": "Sam" + chars(0x2028) + "Smith" + chars(0x2029),
    "new lines and tabs": "Sam\r\nSmith\tJr",
    "a null byte": "Sam\x00Smith",
    "mongolian vowel separator": "T" + chars(0x180E),
    "invisible operators": "T" + chars(0x2062, 0x2063, 0x2064),
    "tag characters": "T" + chars(0xE0041, 0xE0042),
    "annotation characters": "T" + chars(0xFFF9, 0xFFFA, 0xFFFB),
}


@pytest.mark.parametrize("what", sorted(NASTY_FIRST_NAMES))
async def test_names_other_people_see_have_no_invisible_or_direction_characters(
    scene: Scene, what: str
) -> None:
    world = scene.world
    await sign_in(world, MEMBER_ID, first=NASTY_FIRST_NAMES[what], last=chars(0x202E) + "Ng")
    await scene.member.send("PUT", f"{scene.a}/notes", {"notes": "Hello"})
    shown = [
        (await scene.owner.get(f"{scene.a}/members")).text,
        (await scene.owner.get(f"{scene.a}/activity")).text,
        (await scene.guest_a.get(f"{scene.a}/members")).text,
        (await scene.guest_a.get("/api/travel/trips")).text,
    ]
    names = [m["name"] for m in (await scene.owner.get(f"{scene.a}/members")).json()] + [
        e["actor"] for e in (await scene.owner.get(f"{scene.a}/activity")).json()
    ]
    for name in names:
        assert hidden_characters(name) == [], (what, name.encode("unicode_escape"))
        assert len(name) <= 40
        assert name.strip() == name and "  " not in name
    for body in shown:
        assert hidden_characters(body.replace("\n", "")) == [], what


async def test_a_name_is_short_and_html_stays_inert_data(scene: Scene) -> None:
    world = scene.world
    html = "<script>alert(1)</script><img src=x onerror=alert(2)>"
    await sign_in(world, MEMBER_ID, first=html, last="Z" * 500)
    await scene.member.send("PUT", f"{scene.a}/notes", {"notes": "Hello"})
    members = await scene.owner.get(f"{scene.a}/members")
    feed = await scene.owner.get(f"{scene.a}/activity")
    [sam] = [m for m in members.json() if m["role"] == "member" and m["name"] != "Gus"]
    assert len(sam["name"]) <= 40
    # Names are data in JSON: served as JSON, never sniffed into a page, never framed.
    for response in (members, feed):
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["cache-control"] == "no-store"
    # A name of nothing but invisible characters becomes "Someone", never empty.
    await sign_in(world, MEMBER_ID, first=chars(0x200B, 0x202E), last=None)
    names = [m["name"] for m in (await scene.owner.get(f"{scene.a}/members")).json()]
    assert "" not in names and all(n.strip() for n in names)


async def test_a_member_cannot_borrow_the_owners_name_to_look_like_them(scene: Scene) -> None:
    """Anyone can pick a Telegram name, including the owner's. What tells people apart is
    the role next to the name and the "you" flag, which a name cannot change."""
    await sign_in(scene.world, MEMBER_ID, first="T", last=None)
    seen_by_owner = (await scene.owner.get(f"{scene.a}/members")).json()
    pairs = [(m["name"], m["role"]) for m in seen_by_owner]
    assert ("T", "owner") in pairs and ("T", "member") in pairs
    assert [(m["role"], m["id"]) for m in seen_by_owner if m["you"]] == [("owner", scene.owner_id)]
    seen_by_sam = (await scene.member.get(f"{scene.a}/members")).json()
    assert [m["id"] for m in seen_by_sam if m["you"]] == [scene.ids["Sam"]]
    # Sign-in names are the only source: nothing a request sends sets one.
    for body in ({"name": "T"}, {"display_name": "T"}, {"actor": "T"}):
        got = await scene.member.send("PUT", f"{scene.a}/notes", {"notes": "x", **body})
        assert got.status_code == 422


# --- 10. the read-only link ---------------------------------------------------------------------

SHARED_KEYS = {
    "destination", "start", "end", "days", "status", "days_until", "day_number", "day_labels",
    "stops", "photo", "bookings", "show_bookings", "hidden_days",
}  # fmt: skip
SHARED_BOOKING_KEYS = {
    "kind", "title", "provider", "starts", "ends", "segments", "hotel", "address", "check_in",
    "check_out", "day", "at", "category",
}  # fmt: skip


async def test_the_shared_link_is_still_read_only_and_still_hides_the_money(scene: Scene) -> None:
    owner = scene.owner
    hotel = {
        "kind": "hotel", "hotel": "Hotel Kumo", "check_in": "2026-12-10", "check_out": "2026-12-13",
        "cost": "1111.11", "reference": "HK-REF-9",
    }  # fmt: skip
    assert (await owner.send("POST", f"{scene.a}/bookings", hotel)).status_code == 201
    link = (await owner.send("POST", f"{scene.a}/share", {})).json()["token"]
    visitor = scene.world.browser()
    seen = await visitor.get(f"/api/shared/trips/{link}")
    assert seen.status_code == 200
    page = seen.json()
    assert set(page) == SHARED_KEYS
    assert page["bookings"] and all(set(b) == SHARED_BOOKING_KEYS for b in page["bookings"])
    for secret in (*SECRETS, "1111.11", "1,111.11", "HK-REF-9", "R-1", "Bring cash", "Taxi"):
        assert secret not in seen.text, secret
    # The Prep tab is not on the link either: no to-dos, no cover, no policy number.
    for word in ("Get yen", "todo", "cover", "Harbour", "TX-4471", "6123 4567"):
        assert word not in seen.text, word
    assert list(money_keys(page)) == []
    assert "Ann" not in seen.text  # who is going is not on the link either

    # The same page for anyone: signed in as the owner, a member or a guest changes nothing.
    for who in (owner, scene.member, scene.guest_a):
        again = await who.get(f"/api/shared/trips/{link}")
        assert again.json() == page

    # Read-only: no verb but GET, and the link is no key to the trip's own routes.
    before = await snapshot(scene.engine)
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        got = await visitor.client.request(
            verb, f"/api/shared/trips/{link}", headers={"Origin": ORIGIN}, json={"notes": "x"}
        )
        assert got.status_code in {405, 403}, verb
    for path in (f"/api/travel/trips/{link}", f"{scene.a}", f"{scene.a}/members"):
        assert (await visitor.get(path)).status_code == 401
    forged = await visitor.client.request(
        "PUT", f"{scene.a}/notes", headers={"Origin": ORIGIN}, json={"notes": "x"}
    )
    assert forged.status_code == 401
    assert changed(before, await snapshot(scene.engine)) == {}

    # A trip invite is not a link to view, nor a view link an invite.
    invite = (await scene.invite_to(scene.a))["token"]
    assert (await visitor.get(f"/api/shared/trips/{invite}")).status_code == 404
    assert (
        await scene.outsider.send("POST", f"/api/travel/invites/{link}/accept")
    ).status_code == 404
    assert (await scene.outsider.get(scene.a)).status_code == 404

    # Members cannot mint, read or stop the link; the owner's turning bookings off holds.
    for who in (scene.member, scene.guest_a):
        assert (await who.send("POST", f"{scene.a}/share", {"renew": True})).status_code == 403
        assert (await who.send("DELETE", f"{scene.a}/share")).status_code == 403
    assert (
        await visitor.get(f"/api/shared/trips/{link}")
    ).status_code == 200  # still the same link
    off = await owner.send("POST", f"{scene.a}/share", {"show_bookings": False})
    assert off.status_code == 200
    hidden = (await visitor.get(f"/api/shared/trips/{link}")).json()
    assert hidden["show_bookings"] is False
    assert all(b["kind"] == "activity" for b in hidden["bookings"])
    # Stopping it ends it for everyone.
    assert (await owner.send("DELETE", f"{scene.a}/share")).status_code == 204
    assert (await visitor.get(f"/api/shared/trips/{link}")).status_code == 404


# --- more ways in: races, forged requests ---------------------------------------------------------


async def test_one_invite_admits_one_person_even_when_used_at_once(scene: Scene) -> None:
    token = (await scene.invite_to(scene.a))["token"]
    path = f"/api/travel/invites/{token}/accept"
    people = [scene.outsider, scene.peer_b, scene.ex, scene.guest_b]
    got = await asyncio.gather(*(p.send("POST", path) for p in people))
    assert sorted(g.status_code for g in got) == [200, 404, 404, 404], [g.text for g in got]
    spent = await one(
        scene.engine,
        select(trip_invites.c.redeemed_by).where(trip_invites.c.token_hash == token_hash(token)),
    )
    added = await one(
        scene.engine,
        "SELECT count(*) FROM trip_members WHERE added_by_invite IS NOT NULL AND trip_id = :t",
        t=scene.trip_a,
    )
    assert spent is not None
    assert added == 3  # Sam, Gus and Eve before; the removed Eve is gone, this adds exactly one


async def test_one_trip_invite_makes_one_guest_even_when_used_at_once(scene: Scene) -> None:
    token = (await scene.invite_to(scene.a))["token"]
    ids = [1001, 1002, 1003, 1004, 1005]
    got = await asyncio.gather(*(sign_in(scene.world, n, trip_invite=token) for n in ids))
    assert sorted(r.status_code for _, r in got) == [200, 403, 403, 403, 403]
    made = await column(
        scene.engine, select(users.c.telegram_user_id).where(users.c.telegram_user_id.in_(ids))
    )
    assert len(made) == 1  # the four refused left no account behind


async def test_trip_requests_need_the_session_origin_and_csrf_token(scene: Scene) -> None:
    """The routes a guest may use are checked as strictly as any other: a missing or wrong
    CSRF token or a foreign origin is refused before anything is read or written."""
    before = await snapshot(scene.engine)
    writes = [
        (m, t) for (m, t) in CALLS
        if m != "GET" and (m, t) not in owner_only_routes(scene)
    ]  # fmt: skip
    assert len(writes) >= 10
    for who in (scene.member, scene.guest_a):
        for method, template in writes:
            query, body = CALLS[(method, template)]
            ids = ids_of(scene)
            url = fill(template, ids) + fill(query, ids)
            bad_token = await who.client.request(
                method, url, json=fill(body, ids),
                headers={"Origin": ORIGIN, "X-CSRF-Token": "wrong"},
            )  # fmt: skip
            no_token = await who.client.request(
                method, url, json=fill(body, ids), headers={"Origin": ORIGIN}
            )
            foreign = await who.client.request(
                method, url, json=fill(body, ids),
                headers={"Origin": "https://evil.example", "X-CSRF-Token": who.csrf},
            )  # fmt: skip
            others_token = await who.client.request(  # another person's token is no good
                method, url, json=fill(body, ids),
                headers={"Origin": ORIGIN, "X-CSRF-Token": scene.owner.csrf},
            )  # fmt: skip
            for got in (bad_token, no_token, foreign, others_token):
                assert got.status_code == 403, (method, template, got.status_code)
    accept = await scene.guest_a.client.post(
        "/api/travel/invites/anything/accept", headers={"Origin": "https://evil.example"}
    )
    assert accept.status_code == 403
    assert changed(before, await snapshot(scene.engine)) == {}
