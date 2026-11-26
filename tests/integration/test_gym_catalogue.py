"""The shared exercise catalogue: loading it into the database, finding exercises, and the
web API."""

import dataclasses

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.application import gym as gym_cases
from nexus.domain.errors import NotFound
from nexus.domain.gym import Equipment, Level, Muscle
from nexus.infra.db.tables import exercises
from nexus.infra.exercises import load_catalogue
from tests.integration import test_web_api
from tests.integration.conftest import UowFactory
from tests.integration.test_web_api import OWNER, World

pytestmark = pytest.mark.integration

world = test_web_api.world  # the web API tests' app, as a fixture here too

BENCH = "Barbell_Bench_Press_-_Medium_Grip"


async def count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return (await connection.execute(select(func.count()).select_from(exercises))).scalar_one()


async def test_sync_loads_everything_and_is_idempotent(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    catalogue = load_catalogue()
    assert await count(engine) == 0
    assert await gym_cases.sync_catalogue(uow(), catalogue) == len(catalogue)
    assert await count(engine) == len(catalogue)
    assert await gym_cases.sync_catalogue(uow(), catalogue) == 0
    assert await count(engine) == len(catalogue)


async def test_sync_updates_changed_rows_and_keeps_removed_ones(
    uow: UowFactory, engine: AsyncEngine
) -> None:
    catalogue = load_catalogue()
    await gym_cases.sync_catalogue(uow(), catalogue)
    async with engine.begin() as connection:
        await connection.execute(
            update(exercises).where(exercises.c.id == BENCH).values(name="Edited", level="expert")
        )
    assert await gym_cases.sync_catalogue(uow(), catalogue[1:]) == 1
    assert (await gym_cases.exercise(uow(), BENCH)).name != "Edited"
    assert await gym_cases.sync_catalogue(uow(), catalogue[:5]) == 0
    assert await count(engine) == len(catalogue)


async def test_the_round_trip_keeps_every_field(uow: UowFactory) -> None:
    catalogue = load_catalogue()
    await gym_cases.sync_catalogue(uow(), catalogue)
    for wanted in (catalogue[0], catalogue[400], catalogue[-1]):
        assert await gym_cases.exercise(uow(), wanted.id) == wanted
    bare = dataclasses.replace(
        catalogue[0], id="Made_Up", equipment=None, force=None, mechanic=None, secondary=()
    )
    await gym_cases.sync_catalogue(uow(), [bare])
    assert await gym_cases.exercise(uow(), "Made_Up") == bare


async def test_find_exercises(uow: UowFactory) -> None:
    await gym_cases.sync_catalogue(uow(), load_catalogue())
    found = await gym_cases.find_exercises(uow(), text="bench press", limit=5)
    assert len(found) == 5 and all("bench" in e.name.lower() for e in found)
    exact = await gym_cases.find_exercises(uow(), text="Bench Press - Powerlifting")
    assert exact[0].name == "Bench Press - Powerlifting"

    neck = await gym_cases.find_exercises(uow(), muscle=Muscle.NECK, limit=200)
    assert neck and all(Muscle.NECK in e.primary + e.secondary for e in neck)
    assert Muscle.NECK in neck[0].primary

    bands = await gym_cases.find_exercises(
        uow(), equipment=Equipment.BANDS, level=Level.BEGINNER, limit=200
    )
    assert bands and all(
        e.equipment is Equipment.BANDS and e.level is Level.BEGINNER for e in bands
    )

    both = await gym_cases.find_exercises(uow(), text="curl", muscle=Muscle.BICEPS, limit=200)
    assert both and all("curl" in e.name.lower() for e in both)
    assert await gym_cases.find_exercises(uow(), text="zzzz nothing") == []
    assert len(await gym_cases.find_exercises(uow())) == 50


async def test_exercise_not_found(uow: UowFactory) -> None:
    with pytest.raises(NotFound):
        await gym_cases.exercise(uow(), "No_Such_Exercise")


async def test_the_app_loads_the_catalogue_at_startup(world: World) -> None:
    assert await count(world.engine) == len(load_catalogue())


async def test_exercises_api(world: World) -> None:
    anonymous = world.browser()
    assert (await anonymous.get("/api/health/exercises")).status_code in (401, 403)
    assert (await anonymous.get(f"/api/health/exercises/{BENCH}")).status_code in (401, 403)

    owner = world.browser()
    assert (await owner.login(OWNER)).status_code == 200
    listing = await owner.get("/api/health/exercises", params={"text": "bench press", "limit": 3})
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 3 and "bench press" in rows[0]["name"].lower()

    one = await owner.get(f"/api/health/exercises/{BENCH}")
    assert one.status_code == 200
    body = one.json()
    base = world.app.state.settings.exercise_image_base_url
    assert base.startswith("https://raw.githubusercontent.com/yuhonas/free-exercise-db/")
    assert body["name"] == "Barbell Bench Press - Medium Grip"
    assert body["primary_muscles"] == ["chest"]
    assert body["equipment"] == "barbell"
    assert body["images"] == [f"{base}{BENCH}/0.jpg", f"{base}{BENCH}/1.jpg"]
    assert body["instructions"]

    filtered = await owner.get(
        "/api/health/exercises",
        params={"muscle": "lower back", "equipment": "machine", "level": "beginner"},
    )
    assert filtered.status_code == 200
    assert all(r["equipment"] == "machine" and r["level"] == "beginner" for r in filtered.json())

    assert (await owner.get("/api/health/exercises/No_Such")).status_code == 404
    for bad in ({"muscle": "wings"}, {"limit": 0}, {"limit": 201}, {"level": "godlike"}):
        assert (await owner.get("/api/health/exercises", params=bad)).status_code == 422
