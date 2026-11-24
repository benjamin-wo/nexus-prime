"""The Health department's API. For now: the shared exercise catalogue (Gym)."""

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from nexus.application import gym as gym_cases
from nexus.channels.web.security import Auth, Runtime
from nexus.domain.gym import Equipment, Exercise, Level, Muscle

router = APIRouter(prefix="/api/health")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ExerciseOut(Model):
    id: str
    name: str
    category: str
    level: str
    equipment: str | None
    force: str | None
    mechanic: str | None
    primary_muscles: list[str]
    secondary_muscles: list[str]
    instructions: list[str]
    images: list[str]  # full URLs


def _exercise(e: Exercise, base_url: str) -> ExerciseOut:
    base = base_url if base_url.endswith("/") else base_url + "/"
    return ExerciseOut(
        id=e.id,
        name=e.name,
        category=e.category.value,
        level=e.level.value,
        equipment=e.equipment.value if e.equipment else None,
        force=e.force.value if e.force else None,
        mechanic=e.mechanic.value if e.mechanic else None,
        primary_muscles=[m.value for m in e.primary],
        secondary_muscles=[m.value for m in e.secondary],
        instructions=list(e.instructions),
        images=[base + image for image in e.images],
    )


@router.get("/exercises")
async def exercises(
    auth: Auth,
    web: Runtime,
    text: Annotated[str | None, Query(max_length=100)] = None,
    muscle: Muscle | None = None,
    equipment: Equipment | None = None,
    level: Level | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ExerciseOut]:
    found = await gym_cases.find_exercises(
        web.uow(), text=text, muscle=muscle, equipment=equipment, level=level, limit=limit
    )
    return [_exercise(e, web.settings.exercise_image_base_url) for e in found]


@router.get("/exercises/{exercise_id}")
async def exercise(exercise_id: str, auth: Auth, web: Runtime) -> ExerciseOut:
    found = await gym_cases.exercise(web.uow(), exercise_id)
    return _exercise(found, web.settings.exercise_image_base_url)
