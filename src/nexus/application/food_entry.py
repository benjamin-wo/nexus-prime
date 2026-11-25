"""Turning what the model said about a meal into items, in code.

The model passes food names and portions (``FoodRequest``); this resolves each name against
the food database (the best match wins, with no question), works out the grams, and builds the
reply text. Nutrient figures come from the database. Only for a food that has no match does the
model's own estimate for the item (``FoodRequest.estimate``) stand in, after a bounds check
(``domain.nutrition.check_ai_estimate``); a guess outside them is dropped. A question for the
user is a ``NeedsAnswer``, only for an item with neither a match nor a usable estimate; the
agent tool returns its message as an "Error:" for the model to ask about.

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
from nexus.application.nutrition import DaySummary, ItemInput, build_item
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput, NexusError
from nexus.domain.ledger import UserId
from nexus.domain.nutrition import (
    MODIFIER_WIDEN,
    Cooking,
    EstimateKind,
    Food,
    MealSlot,
    MealTotals,
    Nutrients,
    check_ai_estimate,
    kcal_range_words,
    meal_totals,
    portion_grams,
    words,
)

MAX_CANDIDATES = 5  # a food's known portions listed in a question
MAX_NAME = 60
ID_PREFIXES = ("usda:", "sgfoodid:", "custom:")

type UowFactory = Callable[[], UnitOfWork]
AI_OFF = (
    "Error: AI access to health data is off, so I can't read your logs. To turn it on, "
    "open Health, then Privacy, and switch on AI processing."
)


class NeedsAnswer(NexusError):
    """Something the user has to say before this can be logged. ``kind`` says what is missing
    (``none``: no such food and no usable estimate, ``portion``: how much) so a flow with no
    model in it (the photo flow) can ask the user itself."""

    def __init__(self, message: str, kind: str = "other") -> None:
        super().__init__(message)
        self.kind = kind


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
    # The model's guess of the item's nutrients, checked; used only when the food isn't found.
    estimate: Nutrients | None = None


@dataclass(frozen=True, slots=True)
class Resolved:
    inputs: list[ItemInput]
    foods: list[Food | None]  # the food behind each input, same order; None: an AI estimate
    notes: list[str]  # modifiers that only widened a range


def estimate_from(
    kcal: float | Decimal | None,
    protein_g: float | Decimal | None,
    carbs_g: float | Decimal | None,
    fat_g: float | Decimal | None,
) -> Nutrients | None:
    """The model's four figures for an item as checked nutrients; None when one is missing or
    the guess isn't believable (see ``check_ai_estimate``)."""
    if None in (kcal, protein_g, carbs_g, fat_g):
        return None
    try:
        return check_ai_estimate(
            Decimal(str(kcal)), Decimal(str(protein_g)), Decimal(str(carbs_g)), Decimal(str(fat_g))
        )
    except (InvalidInput, ArithmeticError):
        return None


def shown_name(request: FoodRequest) -> str | None:
    """The user's own words for the food, for the confirm card and the day: what they typed or
    the photo's item name; None when all there is is an id (the food's own name is shown)."""
    text = " ".join((request.shown or request.food).split())[:MAX_NAME]
    return None if not text or text.startswith(ID_PREFIXES) else text


async def _pick(uow: UowFactory, request: FoodRequest) -> Food | None:
    """The food for a request: the top-ranked match (it is an estimate anyway, so no question
    about which). None when there is no match but the request has a usable estimate."""
    name = request.food.strip()
    if not words(name):
        raise NeedsAnswer("Error: a food needs a name. Ask the user what they ate.")
    if name.startswith(ID_PREFIXES):
        return await nutrition_cases.food(uow(), name)
    found = await nutrition_cases.find_foods(uow(), name, limit=MAX_CANDIDATES + 1)
    if found:
        return found[0]
    if request.estimate is not None:
        return None
    raise NeedsAnswer(
        f"Error: no food matching {name!r} in the food database, and no usable estimate was "
        "given. Ask the user what it is made of (for example rice and chicken) and how much, "
        "then call again with those; or call again with est_kcal, est_protein_g, est_carbs_g "
        "and est_fat_g for the item (your rough estimate, in line with each other).",
        "none",
    )


def _estimate_label(request: FoodRequest) -> tuple[Decimal | None, str]:
    portion_text = (request.portion or "").strip()
    if portion_text:
        return request.grams, portion_text
    if request.grams is not None:
        return request.grams, f"{request.grams.normalize():f} g"
    return None, "1 serving"


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
    foods: list[Food | None] = []
    notes: list[str] = []
    for request in requests:
        food = await _pick(uow, request)
        grams: Decimal | None = None
        if food is not None:
            try:
                grams, label, kind = _grams_and_kind(request, food)
            except NeedsAnswer:
                if request.estimate is None:
                    raise
                food = None  # a match but no amount: the estimate of the item as eaten
        if food is None:
            grams, label = _estimate_label(request)
            kind = EstimateKind.AI_ESTIMATE
        mods = [m.strip() for m in request.modifiers if m.strip()]
        if mods:
            notes.append(
                f"{food.name if food else shown_name(request) or request.food}: {', '.join(mods)}"
            )
        inputs.append(
            ItemInput(
                food.id if food else None,
                grams or Decimal(1),
                label,
                kind,
                None if food is None else request.cooking,
                MODIFIER_WIDEN if mods else Decimal(0),
                ", ".join(mods) or None,
                shown_name(request),
                request.estimate if food is None else None,
            )
        )
        foods.append(food)
    return Resolved(inputs, foods, notes)


def _line_figures(t: MealTotals) -> str:
    p = t.point
    return (
        f"about {kcal_range_words(t)} · ~{p.protein_g:.0f} g protein · "
        f"{p.carbs_g:.0f} g carbs · {p.fat_g:.0f} g fat"
    )


def logged_text(resolved: Resolved, meal: MealSlot, *, hidden: bool, photo: bool = False) -> str:
    """What was logged, built from the stored figures, for the reply to quote as it is:
    "Logged lunch: chicken rice, about 550-700 kcal · ~30 g protein · 70 g carbs · 20 g fat. A
    rough guide." (more than one item: a line each and a total; from a photo: "A rough guide
    from your photo."). With ``hidden`` (numbers-free mode) no number appears."""
    items = [build_item(f, i) for f, i in zip(resolved.foods, resolved.inputs, strict=True)]
    names = [
        (i.name or (f.name if f else "food")).lower()
        for f, i in zip(resolved.foods, resolved.inputs, strict=True)
    ]
    head = f"Logged {meal.value}:"
    if hidden:
        text = f"{head} {', '.join(names)}."
    else:
        guide = "A rough guide from your photo." if photo else "A rough guide."
        each = [meal_totals([item]) for item in items]
        if len(items) == 1:
            text = f"{head} {names[0]}, {_line_figures(each[0])}. {guide}"
        else:
            lines = [f"- {n}, {_line_figures(t)}" for n, t in zip(names, each, strict=True)]
            text = "\n".join([head, *lines, f"Total: {_line_figures(meal_totals(items))}. {guide}"])
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
            f"{i.name or names.get(i.food_id or '', 'food')} ({i.label})" for i in entry.items
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
