"""PostgreSQL storage for the exercise catalogue: shared by every user, so no user_id."""

from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import ColumnElement

from nexus.domain.gym import (
    Category,
    Equipment,
    Exercise,
    Force,
    Level,
    Mechanic,
    Muscle,
    words,
)
from nexus.infra.db.tables import exercises


def _exercise(row: Row[Any]) -> Exercise:
    return Exercise(
        id=row.id,
        name=row.name,
        category=Category(row.category),
        level=Level(row.level),
        equipment=Equipment(row.equipment) if row.equipment else None,
        force=Force(row.force) if row.force else None,
        mechanic=Mechanic(row.mechanic) if row.mechanic else None,
        primary=tuple(Muscle(m) for m in row.primary_muscles),
        secondary=tuple(Muscle(m) for m in row.secondary_muscles),
        instructions=tuple(row.instructions),
        images=tuple(row.images),
    )


def _values(e: Exercise) -> dict[str, Any]:
    return {
        "id": e.id,
        "name": e.name,
        "category": e.category.value,
        "level": e.level.value,
        "equipment": e.equipment.value if e.equipment else None,
        "force": e.force.value if e.force else None,
        "mechanic": e.mechanic.value if e.mechanic else None,
        "primary_muscles": [m.value for m in e.primary],
        "secondary_muscles": [m.value for m in e.secondary],
        "instructions": list(e.instructions),
        "images": list(e.images),
    }


class SqlGymRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._connection = connection

    async def get_exercise(self, exercise_id: str) -> Exercise | None:
        row = (
            await self._connection.execute(select(exercises).where(exercises.c.id == exercise_id))
        ).first()
        return _exercise(row) if row else None

    async def find_exercises(
        self,
        *,
        text: str | None = None,
        muscle: Muscle | None = None,
        equipment: Equipment | None = None,
        level: Level | None = None,
    ) -> list[Exercise]:
        """The exercises passing every filter, unranked: the name must contain each word of
        ``text``. The caller ranks them."""
        clauses: list[ColumnElement[bool]] = [
            exercises.c.name.ilike(f"%{word}%") for word in words(text or "")
        ]
        if muscle is not None:
            clauses.append(
                exercises.c.primary_muscles.contains([muscle.value])
                | exercises.c.secondary_muscles.contains([muscle.value])
            )
        if equipment is not None:
            clauses.append(exercises.c.equipment == equipment.value)
        if level is not None:
            clauses.append(exercises.c.level == level.value)
        query = select(exercises).where(*clauses).order_by(exercises.c.id)
        return [_exercise(r) for r in (await self._connection.execute(query)).all()]

    async def upsert_exercises(self, catalogue: list[Exercise]) -> int:
        """Insert new exercises and update changed ones; leave identical rows alone and never
        delete. Returns how many rows were written."""
        have = {r.id: _exercise(r) for r in (await self._connection.execute(select(exercises)))}
        changed = [e for e in catalogue if have.get(e.id) != e]
        if changed:
            insert = pg_insert(exercises)
            await self._connection.execute(
                insert.on_conflict_do_update(
                    index_elements=[exercises.c.id],
                    set_={c.name: insert.excluded[c.name] for c in exercises.c if c.name != "id"},
                ),
                [_values(e) for e in changed],
            )
        return len(changed)
