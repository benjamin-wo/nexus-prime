"""Health -> Gym: the shared exercise catalogue."""

from nexus.application.ports import UnitOfWork
from nexus.domain.errors import NotFound
from nexus.domain.gym import Equipment, Exercise, Level, Muscle, search


async def sync_catalogue(uow: UnitOfWork, catalogue: list[Exercise]) -> int:
    """Bring the table up to date with the bundled catalogue; returns rows written (0 when it
    already matches). Safe to run on every start, from several instances at once."""
    async with uow:
        written = await uow.gym.upsert_exercises(catalogue)
        await uow.commit()
        return written


async def find_exercises(
    uow: UnitOfWork,
    *,
    text: str | None = None,
    muscle: Muscle | None = None,
    equipment: Equipment | None = None,
    level: Level | None = None,
    limit: int = 50,
) -> list[Exercise]:
    async with uow:
        found = await uow.gym.find_exercises(
            text=text, muscle=muscle, equipment=equipment, level=level
        )
    return search(found, text=text, muscle=muscle, equipment=equipment, level=level, limit=limit)


async def exercise(uow: UnitOfWork, exercise_id: str) -> Exercise:
    async with uow:
        found = await uow.gym.get_exercise(exercise_id)
    if found is None:
        raise NotFound("no such exercise")
    return found
