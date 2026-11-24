"""Gym training: routines, the weekly plan, workouts, sets, and the rules over them.

Pure rules, no I/O. Weights are ``Decimal`` with at most two decimal places and are stored
with their unit; they are compared in kilograms (1 lb = 0.45359237 kg exactly), so a set in
pounds can beat or tie one in kilograms. Warm-up sets never count towards records, volume or
the best set.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.gym import Exercise, Muscle
from nexus.domain.ledger import UserId

LB_IN_KG = Decimal("0.45359237")  # exact, by definition of the pound

MAX_SLOTS = 50
MAX_SETS = 20
MAX_SLOT_REPS = 100
MAX_SLOT_SECONDS = 3600
MAX_REST_SECONDS = 900
MAX_SET_REPS = 1000
MAX_SET_SECONDS = 86_400
MAX_WEIGHT = Decimal("5000")
MAX_NAME = 80
MAX_NOTE = 500
MAX_ROTATION = 30
EPLEY_MAX_REPS = 12
CENT = Decimal("0.01")


class PlanKind(StrEnum):
    WEEKLY = "weekly"  # a routine on set weekdays
    ROTATION = "rotation"  # the routines in turn, whatever the day


class SetKind(StrEnum):
    # Room for DROP and FAILURE later; every stored value is a ``SetKind`` value.
    WARMUP = "warmup"
    WORKING = "working"


class WeightUnit(StrEnum):
    KG = "kg"
    LB = "lb"


class PrKind(StrEnum):
    HEAVIEST_WEIGHT = "heaviest_weight"
    BEST_E1RM = "best_e1rm"
    MOST_REPS = "most_reps"  # at a weight the user has lifted before


def _clean_text(value: str | None, what: str, limit: int, *, required: bool = False) -> str | None:
    text = (value or "").strip()
    if not text:
        if required:
            raise InvalidInput(f"{what} can't be empty")
        return None
    if len(text) > limit:
        raise InvalidInput(f"{what} can be at most {limit} characters")
    return text


def clean_weight(value: Decimal | None) -> Decimal | None:
    """A weight with at most two decimal places, between 0 and 5000; None passes through."""
    if value is None:
        return None
    if not value.is_finite():
        raise InvalidInput("that weight isn't a number")
    if value != value.quantize(CENT):
        raise InvalidInput("a weight has at most 2 decimal places")
    if not 0 <= value <= MAX_WEIGHT:
        raise InvalidInput(f"a weight is between 0 and {MAX_WEIGHT}")
    return value.quantize(CENT)


def to_kg(weight: Decimal, unit: WeightUnit) -> Decimal:
    """The weight in kilograms, exactly (no rounding)."""
    return weight if unit is WeightUnit.KG else weight * LB_IN_KG


def _in_range(value: int, low: int, high: int, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidInput(f"{what} must be a whole number from {low} to {high}")


# --- routines and the plan ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Slot:
    """One line of a routine: an exercise, how many sets, and a rep or time target."""

    exercise_id: str
    sets: int
    reps: int | None
    seconds: int | None
    rest_seconds: int = 90
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.exercise_id.strip():
            raise InvalidInput("a slot needs an exercise")
        _in_range(self.sets, 1, MAX_SETS, "sets")
        if (self.reps is None) == (self.seconds is None):
            raise InvalidInput("a slot has either reps or seconds, not both and not neither")
        if self.reps is not None:
            _in_range(self.reps, 1, MAX_SLOT_REPS, "reps")
        if self.seconds is not None:
            _in_range(self.seconds, 1, MAX_SLOT_SECONDS, "seconds")
        _in_range(self.rest_seconds, 0, MAX_REST_SECONDS, "rest")
        object.__setattr__(self, "note", _clean_text(self.note, "a note", MAX_NOTE))

    def as_dict(self) -> dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "sets": self.sets,
            "reps": self.reps,
            "seconds": self.seconds,
            "rest_seconds": self.rest_seconds,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Slot":
        try:
            return cls(
                exercise_id=data["exercise_id"],
                sets=data["sets"],
                reps=data.get("reps"),
                seconds=data.get("seconds"),
                rest_seconds=data.get("rest_seconds", 90),
                note=data.get("note"),
            )
        except (KeyError, TypeError) as exc:
            raise InvalidInput(f"bad slot: {exc}") from exc


@dataclass(frozen=True, slots=True)
class Routine:
    id: UUID
    user_id: UserId
    name: str
    slots: tuple[Slot, ...]
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _clean_text(self.name, "a name", MAX_NAME, required=True))
        if not self.slots:
            raise InvalidInput("a routine needs at least one exercise")
        if len(self.slots) > MAX_SLOTS:
            raise InvalidInput(f"a routine has at most {MAX_SLOTS} exercises")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "name": self.name,
            "slots": [s.as_dict() for s in self.slots],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Routine":
        try:
            return cls(
                id=UUID(data["id"]),
                user_id=UserId(UUID(data["user_id"])),
                name=data["name"],
                slots=tuple(Slot.from_dict(s) for s in data["slots"]),
                created_at=datetime.fromisoformat(data["created_at"]),
                updated_at=datetime.fromisoformat(data["updated_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidInput(f"bad routine: {exc}") from exc


@dataclass(frozen=True, slots=True)
class TrainingPlan:
    """When to train what: a routine per weekday (Monday is 0), or the routines in turn."""

    user_id: UserId
    kind: PlanKind
    weekly: dict[int, UUID] = field(default_factory=dict)
    rotation: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        for weekday in self.weekly:
            _in_range(weekday, 0, 6, "a weekday")
        if len(self.rotation) > MAX_ROTATION:
            raise InvalidInput(f"a rotation has at most {MAX_ROTATION} workouts")
        if self.kind is PlanKind.WEEKLY and self.rotation:
            raise InvalidInput("a weekly plan has no rotation")
        if self.kind is PlanKind.ROTATION and self.weekly:
            raise InvalidInput("a rotation plan has no weekdays")

    def routine_ids(self) -> set[UUID]:
        return {*self.weekly.values(), *self.rotation}

    def without(self, routine_id: UUID) -> "TrainingPlan":
        """The plan with a deleted routine taken out of it."""
        return TrainingPlan(
            self.user_id,
            self.kind,
            {d: r for d, r in self.weekly.items() if r != routine_id},
            tuple(r for r in self.rotation if r != routine_id),
        )


def next_in_rotation(plan: TrainingPlan, last_routine_id: UUID | None) -> UUID | None:
    """The routine after ``last_routine_id`` in the rotation, wrapping round; the first one
    when there is no last one (or it has left the rotation). None for an empty rotation."""
    if not plan.rotation:
        return None
    if last_routine_id is None or last_routine_id not in plan.rotation:
        return plan.rotation[0]
    # With a routine twice, continue after its last place: that is where they most likely are.
    index = len(plan.rotation) - 1 - plan.rotation[::-1].index(last_routine_id)
    return plan.rotation[(index + 1) % len(plan.rotation)]


# --- workouts and sets ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Workout:
    id: UUID
    user_id: UserId
    routine_id: UUID | None
    started_at: datetime
    finished_at: datetime | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.finished_at is not None and self.finished_at < self.started_at:
            raise InvalidInput("a workout can't finish before it starts")
        object.__setattr__(self, "note", _clean_text(self.note, "a note", MAX_NOTE))

    @property
    def is_open(self) -> bool:
        return self.finished_at is None


@dataclass(frozen=True, slots=True)
class SetEntry:
    id: UUID
    workout_id: UUID
    exercise_id: str
    position: int
    kind: SetKind
    reps: int | None
    weight: Decimal | None
    unit: WeightUnit
    seconds: int | None
    rpe: Decimal | None
    done_at: datetime

    def __post_init__(self) -> None:
        if not self.exercise_id.strip():
            raise InvalidInput("a set needs an exercise")
        _in_range(self.position, 1, 10_000, "position")
        if self.reps is None and self.seconds is None:
            raise InvalidInput("a set needs reps or seconds")
        if self.reps is not None:
            _in_range(self.reps, 1, MAX_SET_REPS, "reps")
        if self.seconds is not None:
            _in_range(self.seconds, 1, MAX_SET_SECONDS, "seconds")
        object.__setattr__(self, "weight", clean_weight(self.weight))
        if self.rpe is not None:
            if not self.rpe.is_finite() or not 1 <= self.rpe <= 10 or (self.rpe * 2) % 1 != 0:
                raise InvalidInput("RPE is from 1 to 10, in steps of 0.5")

    @property
    def weight_kg(self) -> Decimal | None:
        return None if self.weight is None else to_kg(self.weight, self.unit)

    @property
    def counts(self) -> bool:
        """Warm-ups never count."""
        return self.kind is SetKind.WORKING


def epley_1rm(weight: Decimal, reps: int) -> Decimal | None:
    """The estimated one-rep max, weight x (1 + reps / 30), in the weight's own unit and to two
    places; one rep is the weight itself. None outside 1 to 12 reps (the formula drifts), or
    for no weight."""
    if weight <= 0 or not 1 <= reps <= EPLEY_MAX_REPS:
        return None
    if reps == 1:
        return weight
    return (weight * (1 + Decimal(reps) / 30)).quantize(CENT, ROUND_HALF_UP)


def e1rm_kg(entry: SetEntry) -> Decimal | None:
    """A set's estimated one-rep max in kilograms; None for warm-ups and sets without one."""
    if not entry.counts or entry.weight is None or entry.reps is None:
        return None
    return epley_1rm(entry.weight_kg or Decimal(0), entry.reps)


def best_set(sets: Iterable[SetEntry]) -> SetEntry | None:
    """The working set with the best estimated one-rep max; ties go to the heavier weight,
    then the earlier set. None when no set has one."""
    best: tuple[Decimal, Decimal, SetEntry] | None = None
    for entry in sorted(sets, key=lambda s: (s.done_at, s.position)):
        estimate = e1rm_kg(entry)
        if estimate is None:
            continue
        key = (estimate, entry.weight_kg or Decimal(0))
        if best is None or key > best[:2]:
            best = (*key, entry)
    return best[2] if best else None


def detect_prs(
    new_sets: Sequence[SetEntry], history: Sequence[SetEntry]
) -> dict[str, tuple[PrKind, ...]]:
    """Records the new sets set against everything done before, by exercise: the heaviest
    weight, the best estimated one-rep max, and the most reps at a weight lifted before.
    Warm-ups don't count, on either side. An exercise with no history has nothing to beat, so
    it has no records yet. Sets in ``history`` that are also in ``new_sets`` are ignored."""
    new_ids = {s.id for s in new_sets}
    before: dict[str, list[SetEntry]] = defaultdict(list)
    for h in history:
        if h.counts and h.id not in new_ids:
            before[h.exercise_id].append(h)
    now: dict[str, list[SetEntry]] = defaultdict(list)
    for s in new_sets:
        if s.counts:
            now[s.exercise_id].append(s)

    found: dict[str, tuple[PrKind, ...]] = {}
    for exercise_id, mine in now.items():
        old = before.get(exercise_id)
        if not old:
            continue
        kinds: list[PrKind] = []
        old_weight = max((w for s in old if (w := s.weight_kg) is not None), default=None)
        new_weight = max((w for s in mine if (w := s.weight_kg) is not None), default=None)
        if new_weight is not None and old_weight is not None and new_weight > old_weight:
            kinds.append(PrKind.HEAVIEST_WEIGHT)
        old_e1rm = max((e for s in old if (e := e1rm_kg(s)) is not None), default=None)
        new_e1rm = max((e for s in mine if (e := e1rm_kg(s)) is not None), default=None)
        if new_e1rm is not None and old_e1rm is not None and new_e1rm > old_e1rm:
            kinds.append(PrKind.BEST_E1RM)
        if _beats_reps(mine, old):
            kinds.append(PrKind.MOST_REPS)
        if kinds:
            found[exercise_id] = tuple(kinds)
    return found


def _beats_reps(mine: Sequence[SetEntry], old: Sequence[SetEntry]) -> bool:
    def top(sets: Sequence[SetEntry]) -> dict[Decimal | None, int]:
        out: dict[Decimal | None, int] = {}
        for s in sets:
            if s.reps is not None:
                key = s.weight_kg
                out[key] = max(out.get(key, 0), s.reps)
        return out

    before = top(old)
    return any(weight in before and reps > before[weight] for weight, reps in top(mine).items())


def last_time(exercise_id: str, history: Sequence[SetEntry]) -> list[SetEntry]:
    """The sets of the most recent workout that had this exercise, in order: what to prefill
    from. The most recent is the one whose last set of it is latest. Empty if never done."""
    mine = [s for s in history if s.exercise_id == exercise_id]
    if not mine:
        return []
    latest: dict[UUID, datetime] = {}
    for s in mine:
        latest[s.workout_id] = max(latest.get(s.workout_id, s.done_at), s.done_at)
    winner = max(latest, key=lambda w: (latest[w], str(w)))
    return sorted(
        (s for s in mine if s.workout_id == winner), key=lambda s: (s.position, s.done_at)
    )


def todays_routine(
    plan: TrainingPlan,
    day: date,
    last_workout: Workout | None,
    *,
    tz: tzinfo = UTC,
) -> UUID | None:
    """The routine to do on ``day``. Weekly: the one set for that weekday. Rotation: the one
    after the routine of the user's last routine workout, but a routine already started today
    stays today's until tomorrow. ``last_workout`` is the latest workout that followed a
    routine (an ad-hoc one doesn't move the rotation)."""
    if plan.kind is PlanKind.WEEKLY:
        return plan.weekly.get(day.weekday())
    if last_workout is None or last_workout.routine_id is None:
        return next_in_rotation(plan, None)
    if (
        last_workout.started_at.astimezone(tz).date() == day
        and last_workout.routine_id in plan.rotation
    ):
        return last_workout.routine_id
    return next_in_rotation(plan, last_workout.routine_id)


# --- volume, summaries and progress -----------------------------------------------------------


def week_start(day: date) -> date:
    """The Monday of ``day``'s week."""
    return day - timedelta(days=day.weekday())


@dataclass(frozen=True, slots=True)
class MuscleVolume:
    volume_kg: Decimal  # reps x weight; a primary muscle gets all of it, a secondary half
    sets: int  # working sets that train it primarily
    secondary_sets: int  # working sets that train it secondarily


def volume_kg(entry: SetEntry) -> Decimal:
    """Reps x weight in kilograms for a working set; 0 for warm-ups, time and bodyweight sets."""
    if not entry.counts or entry.reps is None or entry.weight_kg is None:
        return Decimal(0)
    return entry.weight_kg * entry.reps


def volume_by_muscle(
    sets: Iterable[SetEntry],
    catalogue: Mapping[str, Exercise],
    *,
    week: date,
    tz: tzinfo = UTC,
) -> dict[Muscle, MuscleVolume]:
    """Working volume per muscle over the Monday-to-Sunday week that holds ``week`` (judged in
    ``tz``). Exercises not in the catalogue are left out."""
    start = week_start(week)
    end = start + timedelta(days=7)
    volume: dict[Muscle, Decimal] = defaultdict(Decimal)
    primary: dict[Muscle, int] = defaultdict(int)
    secondary: dict[Muscle, int] = defaultdict(int)
    for s in sets:
        if not s.counts or not start <= s.done_at.astimezone(tz).date() < end:
            continue
        exercise = catalogue.get(s.exercise_id)
        if exercise is None:
            continue
        v = volume_kg(s)
        for muscle in exercise.primary:
            volume[muscle] += v
            primary[muscle] += 1
        for muscle in exercise.secondary:
            if muscle in exercise.primary:
                continue
            volume[muscle] += v / 2
            secondary[muscle] += 1
    return {m: MuscleVolume(volume[m], primary[m], secondary[m]) for m in volume}


@dataclass(frozen=True, slots=True)
class WorkoutSummary:
    workout_id: UUID
    duration: timedelta
    sets: int  # working sets
    volume_kg: Decimal
    prs: dict[str, tuple[PrKind, ...]]


def summarise(
    workout: Workout, sets: Sequence[SetEntry], history: Sequence[SetEntry]
) -> WorkoutSummary:
    """How a finished workout went; ``history`` is every set before it."""
    if workout.finished_at is None:
        raise InvalidInput("that workout isn't finished")
    return WorkoutSummary(
        workout_id=workout.id,
        duration=workout.finished_at - workout.started_at,
        sets=sum(1 for s in sets if s.counts),
        volume_kg=sum((volume_kg(s) for s in sets), Decimal(0)),
        prs=detect_prs(sets, history),
    )


@dataclass(frozen=True, slots=True)
class ProgressPoint:
    workout_id: UUID
    at: datetime  # when the best set was done
    best: SetEntry
    e1rm_kg: Decimal


def progress(sets: Iterable[SetEntry]) -> list[ProgressPoint]:
    """The best set of one exercise in each workout, oldest first."""
    by_workout: dict[UUID, list[SetEntry]] = defaultdict(list)
    for s in sets:
        by_workout[s.workout_id].append(s)
    points: list[ProgressPoint] = []
    for workout_id, group in by_workout.items():
        best = best_set(group)
        estimate = e1rm_kg(best) if best else None
        if best is not None and estimate is not None:
            points.append(ProgressPoint(workout_id, best.done_at, best, estimate))
    return sorted(points, key=lambda p: (p.at, str(p.workout_id)))
