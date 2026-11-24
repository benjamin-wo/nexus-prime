"""Food logging over HTTP: the food database, meals, and a day's summary. Writing a meal needs
the user's health consent (403 until they give it). In numbers-free mode a meal shows its foods
and name but no kcal or macros."""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import energy as energy_cases
from nexus.application import nutrition as nutrition_cases
from nexus.channels.web.health_api import _uuid
from nexus.channels.web.health_energy_api import _safety_pending_h2
from nexus.channels.web.security import Auth, Runtime
from nexus.domain.errors import InvalidInput
from nexus.domain.nutrition import (
    Cooking,
    EntrySource,
    EstimateKind,
    Food,
    MealEntry,
    MealSlot,
    MealTotals,
    Nutrients,
)

router = APIRouter(prefix="/api/health")

ONE = Decimal(1)
TENTH = Decimal("0.1")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- the food database ----------------------------------------------------------------------


class PortionOut(Model):
    label: str
    grams: str


class FoodOut(Model):
    id: str
    source: str
    name: str
    aliases: list[str]
    kcal_per_100g: str
    protein_g_per_100g: str
    carbs_g_per_100g: str
    fat_g_per_100g: str
    fibre_g_per_100g: str | None
    portions: list[PortionOut]


def _food(f: Food) -> FoodOut:
    n = f.per_100g
    return FoodOut(
        id=f.id,
        source=f.source.value,
        name=f.name,
        aliases=list(f.aliases),
        kcal_per_100g=str(n.kcal.quantize(ONE, ROUND_HALF_UP)),
        protein_g_per_100g=str(n.protein_g.quantize(TENTH, ROUND_HALF_UP)),
        carbs_g_per_100g=str(n.carbs_g.quantize(TENTH, ROUND_HALF_UP)),
        fat_g_per_100g=str(n.fat_g.quantize(TENTH, ROUND_HALF_UP)),
        fibre_g_per_100g=None if n.fibre_g is None else str(n.fibre_g.quantize(TENTH)),
        portions=[PortionOut(label=p.label, grams=str(p.grams)) for p in f.portions],
    )


@router.get("/foods")
async def list_foods(
    auth: Auth,
    web: Runtime,
    text: Annotated[str, Query(min_length=1, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100)] = 0,
) -> list[FoodOut]:
    found = await nutrition_cases.find_foods(web.uow(), text, limit=limit + offset)
    return [_food(f) for f in found[offset:]]


@router.get("/foods/{food_id}")
async def get_food(food_id: str, auth: Auth, web: Runtime) -> FoodOut:
    return _food(await nutrition_cases.food(web.uow(), food_id))


# --- meals ----------------------------------------------------------------------------------


class ItemIn(Model):
    food_id: str = Field(max_length=100)
    grams: str = Field(max_length=12)
    label: str | None = Field(None, max_length=100)  # "1 cup"; "<grams> g" when left out
    kind: EstimateKind = EstimateKind.WEIGHED
    cooking: Cooking | None = None
    note: str | None = Field(None, max_length=200)


class MealIn(Model):
    meal: MealSlot
    items: list[ItemIn] = Field(min_length=1, max_length=nutrition_cases.MAX_ITEMS)
    eaten_at: datetime | None = None
    source: EntrySource = EntrySource.MANUAL
    note: str | None = Field(None, max_length=nutrition_cases.MAX_NOTE)


class MealPatch(Model):
    meal: MealSlot | None = None
    items: list[ItemIn] | None = Field(None, min_length=1, max_length=nutrition_cases.MAX_ITEMS)
    eaten_at: datetime | None = None
    note: str | None = Field(None, max_length=nutrition_cases.MAX_NOTE)  # "" clears it


class NutrientsOut(Model):
    kcal: str
    protein_g: str
    carbs_g: str
    fat_g: str
    fibre_g: str | None


class TotalsOut(Model):
    point: NutrientsOut
    low: NutrientsOut
    high: NutrientsOut


class ItemOut(Model):
    id: str | None
    food_id: str
    name: str | None
    grams: str
    label: str
    kind: EstimateKind
    cooking: Cooking | None
    note: str | None
    nutrients: NutrientsOut | None  # None in numbers-free mode


class MealOut(Model):
    id: str
    meal: MealSlot
    eaten_at: datetime
    source: EntrySource
    note: str | None
    items: list[ItemOut]
    totals: TotalsOut | None  # None in numbers-free mode
    created_at: datetime
    updated_at: datetime


def _grams(value: str) -> Decimal:
    try:
        number = Decimal(value)
    except ArithmeticError as exc:
        raise InvalidInput("grams must be a number") from exc
    if not number.is_finite():
        raise InvalidInput("grams must be a number")
    return number


def _inputs(items: list[ItemIn]) -> list[nutrition_cases.ItemInput]:
    out = []
    for i in items:
        grams = _grams(i.grams)
        out.append(
            nutrition_cases.ItemInput(
                i.food_id,
                grams,
                i.label or f"{grams.normalize():f} g",
                i.kind,
                i.cooking,
                note=i.note,
            )
        )
    return out


def _nutrients(n: Nutrients) -> NutrientsOut:
    return NutrientsOut(
        kcal=str(n.kcal.quantize(ONE, ROUND_HALF_UP)),
        protein_g=str(n.protein_g.quantize(TENTH, ROUND_HALF_UP)),
        carbs_g=str(n.carbs_g.quantize(TENTH, ROUND_HALF_UP)),
        fat_g=str(n.fat_g.quantize(TENTH, ROUND_HALF_UP)),
        fibre_g=None if n.fibre_g is None else str(n.fibre_g.quantize(TENTH, ROUND_HALF_UP)),
    )


def _totals(t: MealTotals) -> TotalsOut:
    return TotalsOut(point=_nutrients(t.point), low=_nutrients(t.low), high=_nutrients(t.high))


def _meal(entry: MealEntry, names: dict[str, str], hidden: bool) -> MealOut:
    return MealOut(
        id=str(entry.id),
        meal=entry.meal,
        eaten_at=entry.eaten_at,
        source=entry.source,
        note=entry.note,
        items=[
            ItemOut(
                id=None if i.id is None else str(i.id),
                food_id=i.food_id,
                name=names.get(i.food_id),
                grams=str(i.grams.normalize()),
                label=i.label,
                kind=i.kind,
                cooking=i.cooking,
                note=i.note,
                nutrients=None if hidden else _nutrients(i.nutrients),
            )
            for i in entry.items
        ],
        totals=None if hidden else _totals(entry.totals),
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


async def _shown(web: Runtime, user_id: Any, entries: list[MealEntry]) -> list[MealOut]:
    names = await nutrition_cases.food_names(
        web.uow(), [i.food_id for e in entries for i in e.items]
    )
    hidden = await nutrition_cases.numbers_hidden(web.uow(), user_id)
    return [_meal(e, names, hidden) for e in entries]


@router.post("/meals", status_code=201)
async def log_meal(body: MealIn, auth: Auth, web: Runtime) -> MealOut:
    """Record a meal. The kcal and macros are worked out here from the food database."""
    entry = await nutrition_cases.log_meal(
        web.uow(),
        auth.user.id,
        _inputs(body.items),
        body.meal,
        body.eaten_at,
        body.source,
        note=body.note,
        now=web.clock(),
    )
    return (await _shown(web, auth.user.id, [entry]))[0]


@router.get("/meals")
async def list_meals(
    auth: Auth,
    web: Runtime,
    date: date | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[MealOut]:
    """One day's meals (``date``), or ``start`` to ``end``, both included; today by default."""
    found = await nutrition_cases.meals(
        web.uow(), auth.user.id, day=date, first=start, last=end, now=web.clock()
    )
    return await _shown(web, auth.user.id, found)


@router.get("/meals/{meal_id}")
async def get_meal(meal_id: str, auth: Auth, web: Runtime) -> MealOut:
    entry = await nutrition_cases.meal(web.uow(), auth.user.id, _uuid(meal_id, "meal"))
    return (await _shown(web, auth.user.id, [entry]))[0]


@router.patch("/meals/{meal_id}")
async def edit_meal(meal_id: str, body: MealPatch, auth: Auth, web: Runtime) -> MealOut:
    given = body.model_fields_set
    if ("meal" in given and body.meal is None) or ("items" in given and body.items is None):
        raise InvalidInput("meal and items can't be cleared")
    entry = await nutrition_cases.edit_meal(
        web.uow(),
        auth.user.id,
        _uuid(meal_id, "meal"),
        items=None if body.items is None else _inputs(body.items),
        meal=body.meal,
        eaten_at=body.eaten_at,
        note=body.note or None,
        clear_note="note" in given and not body.note,
        now=web.clock(),
    )
    return (await _shown(web, auth.user.id, [entry]))[0]


@router.delete("/meals/{meal_id}", status_code=204)
async def delete_meal(meal_id: str, auth: Auth, web: Runtime) -> None:
    await nutrition_cases.delete_meal(web.uow(), auth.user.id, _uuid(meal_id, "meal"))


# --- a day ----------------------------------------------------------------------------------


class RemainingOut(Model):
    kcal: str
    protein_g: str
    fibre_g: str | None


class DayOut(Model):
    date: date
    hidden: bool
    meals: list[MealOut]
    totals: TotalsOut | None
    targets_kcal: str | None
    remaining: RemainingOut | None


@router.get("/day")
async def day(auth: Auth, web: Runtime, date: date | None = None) -> DayOut:
    """A day's meals with totals and ranges and, for today, what is left of the targets."""
    now = web.clock()
    t = await energy_cases.current_targets(
        web.uow(),
        auth.user.id,
        now=now,
        intake_provider=nutrition_cases.intake_provider(web.uow),
        apply_safety=_safety_pending_h2,
    )
    summary = await nutrition_cases.day_summary(
        web.uow(), auth.user.id, date, targets=t.targets, now=now
    )
    names = await nutrition_cases.food_names(
        web.uow(), [i.food_id for e in summary.entries for i in e.items]
    )
    hidden = summary.hidden
    r = summary.remaining
    return DayOut(
        date=summary.day,
        hidden=hidden,
        meals=[_meal(e, names, hidden) for e in summary.entries],
        totals=None if hidden else _totals(summary.totals),
        targets_kcal=None if hidden or summary.targets is None else str(summary.targets.kcal),
        remaining=None
        if hidden or r is None
        else RemainingOut(
            kcal=str(r.kcal.quantize(ONE, ROUND_HALF_UP)),
            protein_g=str(r.protein_g.quantize(ONE, ROUND_HALF_UP)),
            fibre_g=None if r.fibre_g is None else str(r.fibre_g.quantize(ONE, ROUND_HALF_UP)),
        ),
    )
