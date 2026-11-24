"""Health -> Nutrition: the food database and one user's meals.

The model names foods and portions; this code looks them up and computes kcal and macros from
the database (``domain.nutrition``). Writing a meal needs the master health consent; deleting
one never does (the user must always be able to remove their data). The first write turns
Health on in the menu, as Gym's does.

Energy uses what was logged: ``intake_provider`` reads daily kcal from the meals, and a day
with no meal is not a logged day (it is never counted as 0 kcal).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, tzinfo
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application.energy import IntakeProvider
from nexus.application.health import FUTURE_SLACK
from nexus.application.health_consent import require_consent
from nexus.application.health_menu import note_health_write
from nexus.application.ports import UnitOfWork
from nexus.domain.energy import Targets
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import UserId
from nexus.domain.nutrition import (
    EMPTY_TOTALS,
    Cooking,
    EntrySource,
    EstimateKind,
    Food,
    FoodItem,
    MealEntry,
    MealSlot,
    MealTotals,
    daily_totals,
    make_item,
    search,
)

MAX_ITEMS = 40
MAX_NOTE = 500
MAX_MEALS = 500
MAX_DAYS = 92
CANDIDATES = 2000  # foods fetched for ranking; the database returns the shortest names first


@dataclass(frozen=True, slots=True)
class ItemInput:
    """One food to log: the food's id, how much, and how that amount was known."""

    food_id: str
    grams: Decimal
    label: str  # "350 g", "1 cup", "1 plate"
    kind: EstimateKind
    cooking: Cooking | None = None
    extra_uncertainty: Decimal = Decimal(0)
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Remaining:
    """What is left of today's targets after what was logged (negative when above)."""

    kcal: Decimal
    protein_g: Decimal
    fibre_g: Decimal | None


@dataclass(frozen=True, slots=True)
class DaySummary:
    day: date
    entries: list[MealEntry]
    totals: MealTotals
    hidden: bool  # numbers-free mode: show foods and meal names, no kcal or macros
    targets: Targets | None
    remaining: Remaining | None


# --- the food database ---------------------------------------------------------------------


async def sync_foods(uow: UnitOfWork, foods: Sequence[Food]) -> int:
    """Bring the table up to date with the bundled files; returns rows written (0 when it
    already matches). Safe to run on every start, from several instances at once."""
    async with uow:
        written = await uow.food.upsert_foods(foods)
        await uow.commit()
        return written


async def find_foods(uow: UnitOfWork, text: str, *, limit: int = 20) -> list[Food]:
    async with uow:
        found = await uow.food.find_foods(text, limit=CANDIDATES)
    return search(found, text, limit=limit)


async def food(uow: UnitOfWork, food_id: str) -> Food:
    async with uow:
        found = await uow.food.get_food(food_id)
    if found is None:
        raise NotFound("no such food")
    return found


# --- meals ---------------------------------------------------------------------------------


async def _zone(uow: UnitOfWork, user_id: UserId) -> tzinfo:
    user = await uow.ledger.get_user(user_id)
    return ZoneInfo(user.timezone) if user else ZoneInfo("UTC")


async def _build_items(uow: UnitOfWork, items: Sequence[ItemInput]) -> tuple[FoodItem, ...]:
    if not items:
        raise InvalidInput("a meal needs at least one food")
    if len(items) > MAX_ITEMS:
        raise InvalidInput(f"a meal has at most {MAX_ITEMS} foods")
    known = await uow.food.get_foods(list(dict.fromkeys(i.food_id for i in items)))
    built = []
    for item in items:
        found = known.get(item.food_id)
        if found is None:
            raise InvalidInput(f"no such food: {item.food_id}")
        made = make_item(
            found,
            item.grams,
            item.label,
            item.kind,
            cooking=item.cooking,
            extra_uncertainty=item.extra_uncertainty,
            note=item.note,
        )
        built.append(replace(made, id=uuid4()))
    return tuple(built)


def _clean_note(note: str | None) -> str | None:
    text = (note or "").strip()
    if len(text) > MAX_NOTE:
        raise InvalidInput(f"a note is at most {MAX_NOTE} characters")
    return text or None


def _not_future(at: datetime, now: datetime) -> None:
    if at.tzinfo is None:
        raise InvalidInput("the time needs a time zone")
    if at > now + FUTURE_SLACK:
        raise InvalidInput("that time is in the future")


async def log_meal(
    uow: UnitOfWork,
    user_id: UserId,
    items: Sequence[ItemInput],
    meal: MealSlot,
    eaten_at: datetime | None,
    source: EntrySource,
    *,
    note: str | None = None,
    now: datetime,
) -> MealEntry:
    """Record a meal; ``eaten_at`` defaults to now. Needs the master health consent. The
    nutrients are computed here from the database and kept with each item."""
    when = eaten_at or now
    _not_future(when, now)
    async with uow:
        await require_consent(uow, user_id, None)
        entry = MealEntry(
            uuid4(),
            user_id,
            meal,
            when,
            source,
            _clean_note(note),
            await _build_items(uow, items),
            now,
            now,
        )
        await uow.food.add_meal(entry)
        await note_health_write(uow, user_id)
        await uow.commit()
    return entry


async def edit_meal(
    uow: UnitOfWork,
    user_id: UserId,
    meal_id: UUID,
    *,
    items: Sequence[ItemInput] | None = None,
    meal: MealSlot | None = None,
    eaten_at: datetime | None = None,
    note: str | None = None,
    clear_note: bool = False,
    now: datetime,
) -> MealEntry:
    """Change a meal's foods (replacing all of them), slot, time or note. A change to the
    foods recomputes their nutrients from the database as it is now."""
    if items is None and meal is None and eaten_at is None and note is None and not clear_note:
        raise InvalidInput("nothing to change")
    if eaten_at is not None:
        _not_future(eaten_at, now)
    async with uow:
        await require_consent(uow, user_id, None)
        old = await uow.food.get_meal(user_id, meal_id)
        if old is None:
            raise NotFound("no such meal")
        entry = MealEntry(
            old.id,
            user_id,
            meal or old.meal,
            eaten_at or old.eaten_at,
            old.source,
            None if clear_note else _clean_note(note) if note is not None else old.note,
            old.items if items is None else await _build_items(uow, items),
            old.created_at,
            now,
        )
        await uow.food.replace_meal(entry)
        await note_health_write(uow, user_id)
        await uow.commit()
    return entry


async def delete_meal(uow: UnitOfWork, user_id: UserId, meal_id: UUID) -> None:
    """Delete a meal and its foods. It never needs consent."""
    async with uow:
        if not await uow.food.delete_meal(user_id, meal_id):
            raise NotFound("no such meal")
        await uow.commit()


async def meal(uow: UnitOfWork, user_id: UserId, meal_id: UUID) -> MealEntry:
    async with uow:
        found = await uow.food.get_meal(user_id, meal_id)
    if found is None:
        raise NotFound("no such meal")
    return found


async def _hidden(uow: UnitOfWork, user_id: UserId) -> bool:
    profile = await uow.health.get_profile(user_id)
    return bool(profile and profile.numbers_free)


async def numbers_hidden(uow: UnitOfWork, user_id: UserId) -> bool:
    """Whether the user is in numbers-free mode: show foods and meals, no kcal or macros."""
    async with uow:
        return await _hidden(uow, user_id)


async def food_names(uow: UnitOfWork, ids: Sequence[str]) -> dict[str, str]:
    """Food id to name, for showing what a meal holds."""
    async with uow:
        return {i: f.name for i, f in (await uow.food.get_foods(list(dict.fromkeys(ids)))).items()}


def _span(first: date, last: date, tz: tzinfo) -> tuple[datetime, datetime]:
    return (
        datetime.combine(first, time.min, tz),
        datetime.combine(last + timedelta(days=1), time.min, tz),
    )


async def meals(
    uow: UnitOfWork,
    user_id: UserId,
    *,
    day: date | None = None,
    first: date | None = None,
    last: date | None = None,
    now: datetime,
) -> list[MealEntry]:
    """The meals of one day, or of ``first`` to ``last`` (both included, in the user's time
    zone), oldest first. Today when nothing is given."""
    async with uow:
        tz = await _zone(uow, user_id)
        start = day or first or now.astimezone(tz).date()
        end = day or last or start
        if end < start or (end - start).days >= MAX_DAYS:
            raise InvalidInput(f"give a range of at most {MAX_DAYS} days")
        begin, finish = _span(start, end, tz)
        return await uow.food.list_meals(user_id, start=begin, end=finish, limit=MAX_MEALS)


def remaining_of(targets: Targets, totals: MealTotals) -> Remaining:
    fibre = totals.point.fibre_g or Decimal(0)
    return Remaining(
        targets.kcal - totals.point.kcal,
        targets.protein_g - totals.point.protein_g,
        targets.fibre_g - fibre,
    )


async def day_summary(
    uow: UnitOfWork,
    user_id: UserId,
    day: date | None = None,
    *,
    targets: Targets | None = None,
    now: datetime,
) -> DaySummary:
    """One day's meals with totals and ranges. ``targets`` are today's (from ``energy``); when
    given, and the day is today, what remains of them is worked out. In numbers-free mode
    ``hidden`` is True and the caller must show no figures."""
    async with uow:
        tz = await _zone(uow, user_id)
        today = now.astimezone(tz).date()
        the_day = day or today
        begin, finish = _span(the_day, the_day, tz)
        entries = await uow.food.list_meals(user_id, start=begin, end=finish, limit=MAX_MEALS)
        hidden = await _hidden(uow, user_id)
    totals = daily_totals(entries, tz).get(the_day)
    totals = totals or EMPTY_TOTALS
    use = targets if the_day == today else None
    return DaySummary(
        the_day, entries, totals, hidden, use, remaining_of(use, totals) if use else None
    )


# --- energy --------------------------------------------------------------------------------


def intake_provider(uow_factory: Callable[[], UnitOfWork]) -> IntakeProvider:
    """Daily logged kcal for ``IntakeProvider``: the point value of each day's meals, in the
    user's time zone. A day without a meal is absent, so it counts as not logged."""

    async def provider(user_id: UserId, first: date, last: date) -> dict[date, Decimal]:
        uow = uow_factory()
        async with uow:
            tz = await _zone(uow, user_id)
            begin, finish = _span(first, last, tz)
            entries = await uow.food.list_meals(
                user_id, start=begin, end=finish, limit=MAX_MEALS * MAX_DAYS
            )
        return {day: t.point.kcal for day, t in daily_totals(entries, tz).items()}

    return provider
