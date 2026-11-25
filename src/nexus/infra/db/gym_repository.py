"""PostgreSQL storage for Gym: the exercise catalogue (shared by every user, so no user_id) and
each user's routines, plan, workouts and sets (every query filters on user_id)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import ColumnElement

from nexus.domain.coach import TrainingProfile, WorkoutSuggestion
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
from nexus.domain.gym_training import (
    PlanKind,
    Routine,
    SetEntry,
    SetKind,
    Slot,
    TrainingPlan,
    WeightUnit,
    Workout,
)
from nexus.domain.ledger import UserId
from nexus.infra.db.tables import (
    exercises,
    routines,
    training_plans,
    training_profiles,
    users,
    workout_sets,
    workout_suggestions,
    workouts,
)


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


def _routine(row: Row[Any]) -> Routine:
    return Routine(
        id=row.id,
        user_id=UserId(row.user_id),
        name=row.name,
        slots=tuple(Slot.from_dict(d) for d in row.slots),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _plan(row: Row[Any]) -> TrainingPlan:
    return TrainingPlan(
        user_id=UserId(row.user_id),
        kind=PlanKind(row.kind),
        weekly={int(day): UUID(r) for day, r in row.weekly.items()},
        rotation=tuple(UUID(r) for r in row.rotation),
    )


def _workout(row: Row[Any]) -> Workout:
    return Workout(
        id=row.id,
        user_id=UserId(row.user_id),
        routine_id=row.routine_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        note=row.note,
        planned_slots=(
            None
            if row.planned_slots is None
            else tuple(Slot.from_dict(s) for s in row.planned_slots)
        ),
    )


def _set(row: Row[Any]) -> SetEntry:
    return SetEntry(
        id=row.id,
        workout_id=row.workout_id,
        exercise_id=row.exercise_id,
        position=row.position,
        kind=SetKind(row.kind),
        reps=row.reps,
        weight=row.weight,
        unit=WeightUnit(row.unit),
        seconds=row.seconds,
        rpe=row.rpe,
        done_at=row.done_at,
    )


def _set_values(user_id: UserId, e: SetEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "user_id": user_id,
        "workout_id": e.workout_id,
        "exercise_id": e.exercise_id,
        "position": e.position,
        "kind": e.kind.value,
        "reps": e.reps,
        "weight": e.weight,
        "unit": e.unit.value,
        "seconds": e.seconds,
        "rpe": e.rpe,
        "done_at": e.done_at,
    }


_SET_ORDER = (workout_sets.c.done_at, workout_sets.c.position, workout_sets.c.id)


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

    async def get_exercises(self, ids: Sequence[str]) -> dict[str, Exercise]:
        if not ids:
            return {}
        rows = await self._connection.execute(select(exercises).where(exercises.c.id.in_(ids)))
        return {r.id: _exercise(r) for r in rows}

    # --- consent -----------------------------------------------------------------------

    async def health_consent(self, user_id: UserId) -> datetime | None:
        return (
            await self._connection.execute(
                select(users.c.health_consent_at).where(users.c.id == user_id)
            )
        ).scalar_one_or_none()

    async def set_health_consent(self, user_id: UserId, at: datetime | None) -> None:
        await self._connection.execute(
            update(users).where(users.c.id == user_id).values(health_consent_at=at)
        )

    async def weight_unit(self, user_id: UserId) -> WeightUnit | None:
        value = (
            await self._connection.execute(select(users.c.weight_unit).where(users.c.id == user_id))
        ).scalar_one_or_none()
        return WeightUnit(value) if value else None

    async def set_weight_unit(self, user_id: UserId, unit: WeightUnit) -> None:
        await self._connection.execute(
            update(users).where(users.c.id == user_id).values(weight_unit=unit.value)
        )

    # --- routines and the plan -----------------------------------------------------------

    async def add_routine(self, routine: Routine) -> None:
        await self._connection.execute(
            routines.insert().values(
                id=routine.id,
                user_id=routine.user_id,
                name=routine.name,
                slots=[s.as_dict() for s in routine.slots],
                created_at=routine.created_at,
                updated_at=routine.updated_at,
            )
        )

    async def update_routine(self, routine: Routine) -> bool:
        result = await self._connection.execute(
            update(routines)
            .where(routines.c.id == routine.id, routines.c.user_id == routine.user_id)
            .values(
                name=routine.name,
                slots=[s.as_dict() for s in routine.slots],
                updated_at=routine.updated_at,
            )
        )
        return bool(result.rowcount)

    async def get_routine(self, user_id: UserId, routine_id: UUID) -> Routine | None:
        row = (
            await self._connection.execute(
                select(routines).where(routines.c.id == routine_id, routines.c.user_id == user_id)
            )
        ).first()
        return _routine(row) if row else None

    async def list_routines(self, user_id: UserId) -> list[Routine]:
        query = (
            select(routines)
            .where(routines.c.user_id == user_id)
            .order_by(routines.c.created_at, routines.c.name, routines.c.id)
        )
        return [_routine(r) for r in (await self._connection.execute(query)).all()]

    async def routine_ids(self, user_id: UserId, ids: Sequence[UUID]) -> set[UUID]:
        """Which of ``ids`` are this user's routines."""
        if not ids:
            return set()
        query = select(routines.c.id).where(routines.c.user_id == user_id, routines.c.id.in_(ids))
        return set((await self._connection.execute(query)).scalars())

    async def delete_routine(self, user_id: UserId, routine_id: UUID) -> bool:
        """Past workouts that followed it stay, with no routine."""
        result = await self._connection.execute(
            delete(routines).where(routines.c.id == routine_id, routines.c.user_id == user_id)
        )
        return bool(result.rowcount)

    async def get_plan(self, user_id: UserId) -> TrainingPlan | None:
        row = (
            await self._connection.execute(
                select(training_plans).where(training_plans.c.user_id == user_id)
            )
        ).first()
        return _plan(row) if row else None

    async def save_plan(self, plan: TrainingPlan, at: datetime) -> None:
        values = {
            "kind": plan.kind.value,
            "weekly": {str(day): str(r) for day, r in plan.weekly.items()},
            "rotation": [str(r) for r in plan.rotation],
            "updated_at": at,
        }
        insert = pg_insert(training_plans).values(user_id=plan.user_id, **values)
        await self._connection.execute(
            insert.on_conflict_do_update(index_elements=[training_plans.c.user_id], set_=values)
        )

    # --- the coach's inputs --------------------------------------------------------------

    async def get_training_profile(self, user_id: UserId) -> TrainingProfile | None:
        row = (
            await self._connection.execute(
                select(training_profiles).where(training_profiles.c.user_id == user_id)
            )
        ).first()
        return None if row is None else TrainingProfile.from_dict(dict(row._mapping))

    async def save_training_profile(
        self, user_id: UserId, profile: TrainingProfile, at: datetime
    ) -> None:
        values = {**profile.as_dict(), "updated_at": at}
        insert = pg_insert(training_profiles).values(user_id=user_id, **values)
        await self._connection.execute(
            insert.on_conflict_do_update(index_elements=[training_profiles.c.user_id], set_=values)
        )

    # --- workouts and sets ---------------------------------------------------------------

    async def add_workout(self, workout: Workout) -> None:
        await self._connection.execute(
            workouts.insert().values(
                id=workout.id,
                user_id=workout.user_id,
                routine_id=workout.routine_id,
                started_at=workout.started_at,
                finished_at=workout.finished_at,
                note=workout.note,
                planned_slots=(
                    None
                    if workout.planned_slots is None
                    else [s.as_dict() for s in workout.planned_slots]
                ),
            )
        )

    async def add_workout_suggestion(self, suggestion: WorkoutSuggestion) -> None:
        await self._connection.execute(
            workout_suggestions.insert().values(
                id=suggestion.id,
                user_id=suggestion.user_id,
                focus=suggestion.focus,
                slots=[s.as_dict() for s in suggestion.slots],
                minutes=suggestion.minutes,
                created_at=suggestion.created_at,
            )
        )

    async def get_workout_suggestion(
        self, user_id: UserId, suggestion_id: UUID, *, since: datetime
    ) -> WorkoutSuggestion | None:
        row = (
            await self._connection.execute(
                select(workout_suggestions).where(
                    workout_suggestions.c.id == suggestion_id,
                    workout_suggestions.c.user_id == user_id,
                    workout_suggestions.c.created_at >= since,
                )
            )
        ).first()
        if row is None:
            return None
        return WorkoutSuggestion(
            id=row.id,
            user_id=row.user_id,
            focus=row.focus,
            slots=tuple(Slot.from_dict(s) for s in row.slots),
            minutes=row.minutes,
            created_at=row.created_at,
        )

    async def get_workout(self, user_id: UserId, workout_id: UUID) -> Workout | None:
        row = (
            await self._connection.execute(
                select(workouts).where(workouts.c.id == workout_id, workouts.c.user_id == user_id)
            )
        ).first()
        return _workout(row) if row else None

    async def update_workout(self, workout: Workout) -> bool:
        result = await self._connection.execute(
            update(workouts)
            .where(workouts.c.id == workout.id, workouts.c.user_id == workout.user_id)
            .values(finished_at=workout.finished_at, note=workout.note)
        )
        return bool(result.rowcount)

    async def delete_workout(self, user_id: UserId, workout_id: UUID) -> bool:
        """Its sets go with it."""
        result = await self._connection.execute(
            delete(workouts).where(workouts.c.id == workout_id, workouts.c.user_id == user_id)
        )
        return bool(result.rowcount)

    async def open_workout(self, user_id: UserId) -> Workout | None:
        """The newest workout not yet finished."""
        row = (
            await self._connection.execute(
                select(workouts)
                .where(workouts.c.user_id == user_id, workouts.c.finished_at.is_(None))
                .order_by(workouts.c.started_at.desc(), workouts.c.id)
                .limit(1)
            )
        ).first()
        return _workout(row) if row else None

    async def last_routine_workout(self, user_id: UserId) -> Workout | None:
        """The newest workout that followed a routine (finished or not)."""
        row = (
            await self._connection.execute(
                select(workouts)
                .where(workouts.c.user_id == user_id, workouts.c.routine_id.is_not(None))
                .order_by(workouts.c.started_at.desc(), workouts.c.id)
                .limit(1)
            )
        ).first()
        return _workout(row) if row else None

    async def list_workouts(
        self, user_id: UserId, *, start: datetime | None = None, end: datetime | None = None
    ) -> list[Workout]:
        """Workouts that started in ``[start, end)``, newest first."""
        query = select(workouts).where(workouts.c.user_id == user_id)
        if start is not None:
            query = query.where(workouts.c.started_at >= start)
        if end is not None:
            query = query.where(workouts.c.started_at < end)
        query = query.order_by(workouts.c.started_at.desc(), workouts.c.id)
        return [_workout(r) for r in (await self._connection.execute(query)).all()]

    async def add_set(self, user_id: UserId, entry: SetEntry) -> None:
        await self._connection.execute(workout_sets.insert().values(_set_values(user_id, entry)))

    async def get_set(self, user_id: UserId, set_id: UUID) -> SetEntry | None:
        row = (
            await self._connection.execute(
                select(workout_sets).where(
                    workout_sets.c.id == set_id, workout_sets.c.user_id == user_id
                )
            )
        ).first()
        return _set(row) if row else None

    async def update_set(self, user_id: UserId, entry: SetEntry) -> bool:
        values = _set_values(user_id, entry)
        for fixed in ("id", "user_id", "workout_id", "position"):
            del values[fixed]
        result = await self._connection.execute(
            update(workout_sets)
            .where(workout_sets.c.id == entry.id, workout_sets.c.user_id == user_id)
            .values(values)
        )
        return bool(result.rowcount)

    async def delete_set(self, user_id: UserId, set_id: UUID) -> bool:
        result = await self._connection.execute(
            delete(workout_sets).where(
                workout_sets.c.id == set_id, workout_sets.c.user_id == user_id
            )
        )
        return bool(result.rowcount)

    async def sets_of_workouts(
        self, user_id: UserId, workout_ids: Sequence[UUID]
    ) -> dict[UUID, list[SetEntry]]:
        """Each workout's sets in the order they were logged."""
        found: dict[UUID, list[SetEntry]] = {w: [] for w in workout_ids}
        if not workout_ids:
            return found
        query = (
            select(workout_sets)
            .where(workout_sets.c.user_id == user_id, workout_sets.c.workout_id.in_(workout_ids))
            .order_by(workout_sets.c.workout_id, workout_sets.c.position, *_SET_ORDER)
        )
        for row in (await self._connection.execute(query)).all():
            found[row.workout_id].append(_set(row))
        return found

    async def next_position(self, user_id: UserId, workout_id: UUID) -> int:
        top = (
            await self._connection.execute(
                select(func.max(workout_sets.c.position)).where(
                    workout_sets.c.user_id == user_id, workout_sets.c.workout_id == workout_id
                )
            )
        ).scalar_one()
        return int(top or 0) + 1

    async def last_set(self, user_id: UserId, workout_id: UUID) -> SetEntry | None:
        row = (
            await self._connection.execute(
                select(workout_sets)
                .where(workout_sets.c.user_id == user_id, workout_sets.c.workout_id == workout_id)
                .order_by(workout_sets.c.position.desc(), workout_sets.c.done_at.desc())
                .limit(1)
            )
        ).first()
        return _set(row) if row else None

    async def sets_of_exercises(
        self,
        user_id: UserId,
        exercise_ids: Sequence[str],
        *,
        before: datetime | None = None,
        exclude_workout: UUID | None = None,
    ) -> list[SetEntry]:
        """The user's sets of these exercises, oldest first; ``before`` keeps those done
        earlier than it."""
        if not exercise_ids:
            return []
        query = select(workout_sets).where(
            workout_sets.c.user_id == user_id, workout_sets.c.exercise_id.in_(exercise_ids)
        )
        if before is not None:
            query = query.where(workout_sets.c.done_at < before)
        if exclude_workout is not None:
            query = query.where(workout_sets.c.workout_id != exclude_workout)
        query = query.order_by(*_SET_ORDER)
        return [_set(r) for r in (await self._connection.execute(query)).all()]

    async def sets_between(self, user_id: UserId, start: datetime, end: datetime) -> list[SetEntry]:
        """Sets done in ``[start, end)``, oldest first."""
        query = (
            select(workout_sets)
            .where(
                workout_sets.c.user_id == user_id,
                workout_sets.c.done_at >= start,
                workout_sets.c.done_at < end,
            )
            .order_by(*_SET_ORDER)
        )
        return [_set(r) for r in (await self._connection.execute(query)).all()]
