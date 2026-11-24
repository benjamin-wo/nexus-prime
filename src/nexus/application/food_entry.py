"""Turning what the model said about a meal into items, in code.

The model passes food names and portions (``FoodRequest``); this resolves each name against
the food database, works out the grams, and builds the confirm and summary texts, so no
nutrient figure ever comes from the model. A question for the user is a ``NeedsAnswer`` whose
message the agent tool returns as an "Error:" for the model to ask about.

Modifiers ("less rice", "extra gravy") scale a component of a composite food by
``domain.nutrition.MODIFIER_SCALES``, but no food in the database has components yet (USDA
foods are single foods), so for now a modifier becomes a note on the item and widens its range
by ``MODIFIER_WIDEN``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nexus.application import nutrition as nutrition_cases
from nexus.application.health_consent import may_send_to_ai
from nexus.application.nutrition import DaySummary, ItemInput
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import NexusError
from nexus.domain.ledger import UserId
from nexus.domain.nutrition import (
    MODIFIER_WIDEN,
    Cooking,
    EstimateKind,
    Food,
    MealSlot,
    MealTotals,
    kcal_range_words,
    make_item,
    meal_totals,
    portion_grams,
    words,
)

MAX_CANDIDATES = 5
MAX_NAME = 60
ID_PREFIXES = ("usda:", "sgfoodid:", "custom:")

type UowFactory = Callable[[], UnitOfWork]
AI_OFF = (
    "Error: AI access to health data is off, so I can't read your logs. To turn it on, "
    "open Health, then Privacy, and switch on AI processing."
)


class NeedsAnswer(NexusError):
    """Something the user has to say before this can be logged. ``kind`` says what is missing
    (``none``: no such food, ``several``: which one of ``candidates``, ``portion``: how much)
    so a flow with no model in it (the photo flow) can ask the user itself."""

    def __init__(self, message: str, kind: str = "other", candidates: Sequence[Food] = ()) -> None:
        super().__init__(message)
        self.kind = kind
        self.candidates = list(candidates)


@dataclass(frozen=True, slots=True)
class FoodRequest:
    food: str  # the name the user used: "chicken rice"
    portion: str | None = None  # "1 cup", "1 plate"
    grams: Decimal | None = None  # a weight given, or the model's estimate
    estimated: bool = False  # True when ``grams`` is a guess, not a weighed amount
    cooking: Cooking | None = None
    modifiers: tuple[str, ...] = ()
    # Read from a photo: whatever the amount, it is an estimate (``EstimateKind.ESTIMATED``).
    photo: bool = False
    shown: str | None = None  # what to call it when shown, if not ``food`` (a photo's item name)


@dataclass(frozen=True, slots=True)
class Resolved:
    inputs: list[ItemInput]
    foods: list[Food]  # the food behind each input, same order
    notes: list[str]  # modifiers that only widened a range


def _names(foods: Sequence[Food]) -> str:
    return "; ".join(f"{f.name} (id {f.id})" for f in foods[:MAX_CANDIDATES])


def _same(food: Food, text: str) -> bool:
    wanted = " ".join(words(text))
    return any(" ".join(words(n)) == wanted for n in (food.name, *food.aliases))


def shown_name(request: FoodRequest) -> str | None:
    """The user's own words for the food, for the confirm card and the day: what they typed or
    the photo's item name; None when all there is is an id (the food's own name is shown)."""
    text = " ".join((request.shown or request.food).split())[:MAX_NAME]
    return None if not text or text.startswith(ID_PREFIXES) else text


async def _pick(uow: UowFactory, request: FoodRequest) -> Food:
    name = request.food.strip()
    if not words(name):
        raise NeedsAnswer("Error: a food needs a name. Ask the user what they ate.")
    if name.startswith(ID_PREFIXES):
        return await nutrition_cases.food(uow(), name)
    found = await nutrition_cases.find_foods(uow(), name, limit=MAX_CANDIDATES + 1)
    if not found:
        raise NeedsAnswer(
            f"Error: no food matching {name!r} in the food database (some local dishes are "
            "missing until the Singapore database is loaded). Ask the user what it is made of "
            "(for example rice and chicken) and how much, or its weight in grams, then call "
            "again with those. Never estimate calories yourself.",
            "none",
        )
    if len(found) == 1 or _same(found[0], name):
        return found[0]
    more = ", and more" if len(found) > MAX_CANDIDATES else ""
    raise NeedsAnswer(
        f"Error: {name!r} could be several foods: {_names(found)}{more}. Ask the user which "
        "one, then call again with that food's id.",
        "several",
        found[:MAX_CANDIDATES],
    )


def _grams_and_kind(request: FoodRequest, food: Food) -> tuple[Decimal, str, EstimateKind]:
    portion_text = (request.portion or "").strip()
    if request.photo:
        # The photo's amounts are the model's guess: a known portion's weight is used, but
        # the item still gets the estimated range (plus or minus 30%).
        if request.grams is not None:
            label = portion_text or f"{request.grams.normalize():f} g"
            return request.grams, label, EstimateKind.ESTIMATED
        matched = portion_grams(food, portion_text) if portion_text else None
        if matched is not None:
            return matched[1], portion_text, EstimateKind.ESTIMATED
    if portion_text:
        matched = portion_grams(food, portion_text)
        if matched is not None:
            return matched[1], portion_text, EstimateKind.PORTION
    if request.grams is not None:
        if portion_text:
            return request.grams, portion_text, EstimateKind.ESTIMATED
        kind = EstimateKind.ESTIMATED if request.estimated else EstimateKind.WEIGHED
        return request.grams, f"{request.grams.normalize():f} g", kind
    have = "; ".join(p.label for p in food.portions[:MAX_CANDIDATES])
    options = f" Its known portions: {have}." if have else ""
    what = f"{portion_text!r} is not a portion I know for" if portion_text else "How much of"
    raise NeedsAnswer(
        f"Error: {what} {food.name}.{options} Ask the user how much they had "
        "(a known portion or a weight in grams).",
        "portion",
    )


async def resolve(uow: UowFactory, requests: Sequence[FoodRequest]) -> Resolved:
    """Each request to an ``ItemInput`` (``uow`` makes a fresh unit of work per lookup), or
    raise ``NeedsAnswer`` for the first one that needs the user: a food not found, ambiguous,
    or without a usable portion."""
    inputs: list[ItemInput] = []
    foods: list[Food] = []
    notes: list[str] = []
    for request in requests:
        food = await _pick(uow, request)
        grams, label, kind = _grams_and_kind(request, food)
        mods = [m.strip() for m in request.modifiers if m.strip()]
        if mods:
            notes.append(f"{food.name}: {', '.join(mods)}")
        inputs.append(
            ItemInput(
                food.id,
                grams,
                label,
                kind,
                request.cooking,
                MODIFIER_WIDEN if mods else Decimal(0),
                ", ".join(mods) or None,
                shown_name(request),
            )
        )
        foods.append(food)
    return Resolved(inputs, foods, notes)


def _preview_totals(resolved: Resolved) -> tuple[list[MealTotals], MealTotals]:
    items = [
        make_item(
            f,
            i.grams,
            i.label,
            i.kind,
            cooking=i.cooking,
            extra_uncertainty=i.extra_uncertainty,
        )
        for f, i in zip(resolved.foods, resolved.inputs, strict=True)
    ]
    return [meal_totals([item]) for item in items], meal_totals(items)


def confirm_text(
    resolved: Resolved,
    meal: MealSlot,
    *,
    hidden: bool,
    done: bool = False,
    photo: bool = False,
) -> str:
    """ "Log lunch: chicken rice (1 plate, about 600-750 kcal)? I estimated the portion."
    built from the database figures ("Logged lunch: ...." with ``done``). With ``hidden``
    (numbers-free mode) no number appears. A meal read from a photo says so ("Log lunch from
    your photo: ...") and that the portions are estimates."""
    each, total = _preview_totals(resolved)
    parts = []
    for food, item, t in zip(resolved.foods, resolved.inputs, each, strict=True):
        detail = item.label if hidden else f"{item.label}, about {kcal_range_words(t)}"
        parts.append(f"{(item.name or food.name).lower()} ({detail})")
    source = " from your photo" if photo else ""
    text = f"{'Logged' if done else 'Log'} {meal.value}{source}: {', '.join(parts)}"
    if not hidden and len(parts) > 1:
        text += f"; about {kcal_range_words(total)} in all"
    text += "." if done else "?"
    estimated = [i for i in resolved.inputs if i.kind is EstimateKind.ESTIMATED]
    if photo:
        text += " I estimated the portions."
    elif estimated:
        text += " I estimated the portion." if len(estimated) == 1 else " I estimated the portions."
    if resolved.notes:
        text += f" Noted: {'; '.join(resolved.notes)}" + (
            "." if hidden else " (the range is wider for it)."
        )
    return text


def day_text(summary: DaySummary, names: dict[str, str]) -> str:
    """A day's food log for the model to quote: foods and meal names always, figures unless
    numbers-free mode is on."""
    if not summary.entries:
        return f"{summary.day.isoformat()}: nothing logged."
    lines = [f"{summary.day.isoformat()}:"]
    for entry in summary.entries:
        foods = ", ".join(
            f"{i.name or names.get(i.food_id, i.food_id)} ({i.label})" for i in entry.items
        )
        line = f"- {entry.meal.value}: {foods}"
        if not summary.hidden:
            line += f" [about {kcal_range_words(entry.totals)}]"
        lines.append(line)
    if summary.hidden:
        return "\n".join(lines)
    t = summary.totals
    protein = (
        f"{t.point.protein_g:.0f} g protein (range {t.low.protein_g:.0f}-{t.high.protein_g:.0f})"
    )
    lines.append(
        f"Total: about {kcal_range_words(summary.totals)} (point {t.point.kcal:.0f} kcal), "
        f"{protein}, {t.point.carbs_g:.0f} g carbs, {t.point.fat_g:.0f} g fat"
        + (f", at least {t.point.fibre_g:.0f} g fibre" if t.point.fibre_g is not None else "")
        + "."
    )
    r = summary.remaining
    if r is not None:
        lines.append(
            f"Against today's targets: {r.kcal:.0f} kcal and {r.protein_g:.0f} g protein "
            "remaining (a negative number means above the target)."
        )
    return "\n".join(lines)


async def ai_may_read(uow: UnitOfWork, user_id: UserId) -> bool:
    """Whether past meals may go into a tool result the model reads (``may_send_to_ai``)."""
    return await may_send_to_ai(uow, user_id)
