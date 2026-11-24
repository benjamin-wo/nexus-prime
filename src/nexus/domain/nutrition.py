"""Food logging: foods, portions, meals, and the nutrient maths. Pure rules, no I/O, all Decimal.

The rule behind everything here (Nexus Health research report, section B): the model names a
food and a portion, code computes kcal and macros from a nutrient database, and the user is
shown a range, not a single figure. The model never emits a nutrient value.

Foods come from bundled JSON files (``infra/foods/``), one per source, with nutrients per
100 g. The uncertainty figures below are Nexus's own design choices, not research findings;
they are constants so they can be tuned in one place once the app has real data to measure
them against. The research only says that photo and estimate methods undercount, that fat is
worst, and that portion information matters more than the model (so a weighed portion gets
the narrowest range).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId

D = Decimal
HUNDRED = D(100)
NONE = D(0)
SNAPSHOT_STEP = D("0.001")  # snapshots are kept to a thousandth
MAX_RESULTS = 200
MAX_GRAMS = D(5000)  # one item; beyond this it is a typo

# --- design choices: how unsure each way of knowing a portion is ----------------------------
# Half-width of an item's range as a share of its point value.
UNCERTAINTY_WEIGHED = D("0.05")  # weighed on a scale, in grams
UNCERTAINTY_PORTION = D("0.15")  # a standard portion from the database ("1 cup")
UNCERTAINTY_ESTIMATED = D("0.30")  # the model's estimate of a vague portion ("a plate")
# Added to an item's half-width when the user gave a modifier we can't apply to a
# single-component food ("less rice" on a food that has no rice component).
MODIFIER_WIDEN = D("0.15")
# The research found photo and estimate methods undercount, fat most of all (about 30 g a meal
# in the NIH-led study). So the *upper* end of kcal and fat is raised by this share of the
# item's point value for oily cooking. The point value itself is never adjusted. Design
# figures, not published ones.
COOKING_UPLIFT_FRIED = D("0.20")
COOKING_UPLIFT_STIR_FRIED = D("0.15")
COOKING_UPLIFT_GRAVY = D("0.25")  # curry and coconut-milk gravies: the biggest unknown
# Scale for a modifier on one component of a composite food. Only used when a food has
# components; USDA foods don't, so today a modifier is a note plus ``MODIFIER_WIDEN``.
MODIFIER_SCALES: Mapping[str, Decimal] = {
    "less": D("0.7"),
    "little": D("0.7"),
    "half": D("0.5"),
    "no": D(0),
    "without": D(0),
    "extra": D("1.3"),
    "more": D("1.3"),
    "double": D(2),
}


class FoodSource(StrEnum):
    USDA = "usda"
    SGFOODID = "sgfoodid"
    CUSTOM = "custom"


class MealSlot(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


class EntrySource(StrEnum):
    CHAT = "chat"
    VOICE = "voice"
    MANUAL = "manual"
    PHOTO = "photo"


class EstimateKind(StrEnum):
    WEIGHED = "weighed"
    PORTION = "portion"
    ESTIMATED = "estimated"


class Cooking(StrEnum):
    FRIED = "fried"
    STIR_FRIED = "stir-fried"
    GRAVY = "curry/gravy"


UNCERTAINTY: Mapping[EstimateKind, Decimal] = {
    EstimateKind.WEIGHED: UNCERTAINTY_WEIGHED,
    EstimateKind.PORTION: UNCERTAINTY_PORTION,
    EstimateKind.ESTIMATED: UNCERTAINTY_ESTIMATED,
}
COOKING_UPLIFT: Mapping[Cooking, Decimal] = {
    Cooking.FRIED: COOKING_UPLIFT_FRIED,
    Cooking.STIR_FRIED: COOKING_UPLIFT_STIR_FRIED,
    Cooking.GRAVY: COOKING_UPLIFT_GRAVY,
}


@dataclass(frozen=True, slots=True)
class Nutrients:
    """kcal and macros for some amount of food. ``fibre_g`` is None when the source has no
    fibre figure; a sum of several keeps what is known (so it is a lower bound)."""

    kcal: Decimal
    protein_g: Decimal
    carbs_g: Decimal
    fat_g: Decimal
    fibre_g: Decimal | None = None

    def __add__(self, other: "Nutrients") -> "Nutrients":
        fibre = (
            None
            if self.fibre_g is None and other.fibre_g is None
            else (self.fibre_g or D(0)) + (other.fibre_g or D(0))
        )
        return Nutrients(
            self.kcal + other.kcal,
            self.protein_g + other.protein_g,
            self.carbs_g + other.carbs_g,
            self.fat_g + other.fat_g,
            fibre,
        )

    def scaled(self, factor: Decimal) -> "Nutrients":
        return Nutrients(
            self.kcal * factor,
            self.protein_g * factor,
            self.carbs_g * factor,
            self.fat_g * factor,
            None if self.fibre_g is None else self.fibre_g * factor,
        )

    def quantized(self, step: Decimal = SNAPSHOT_STEP) -> "Nutrients":
        """Each figure rounded half up to ``step`` (what is stored in a snapshot)."""
        return Nutrients(
            self.kcal.quantize(step, ROUND_HALF_UP),
            self.protein_g.quantize(step, ROUND_HALF_UP),
            self.carbs_g.quantize(step, ROUND_HALF_UP),
            self.fat_g.quantize(step, ROUND_HALF_UP),
            None if self.fibre_g is None else self.fibre_g.quantize(step, ROUND_HALF_UP),
        )


ZERO = Nutrients(D(0), D(0), D(0), D(0), None)


@dataclass(frozen=True, slots=True)
class Portion:
    """A household measure and what it weighs: ``label`` ("2 tablespoon", "1 cup, chopped")
    is for the whole quantity it names, ``grams`` its weight."""

    label: str
    grams: Decimal

    def __post_init__(self) -> None:
        if not self.label.strip() or self.grams <= 0:
            raise InvalidInput("a portion needs a label and a positive weight")


@dataclass(frozen=True, slots=True)
class Food:
    """One food, with its nutrients per 100 g. ``id`` is ``<source>:<source's own id>``."""

    id: str
    source: FoodSource
    name: str
    aliases: tuple[str, ...]
    per_100g: Nutrients
    portions: tuple[Portion, ...]

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise InvalidInput("a food needs an id and a name")
        if not self.id.startswith(f"{self.source.value}:"):
            raise InvalidInput(f"{self.id}: the id starts with the source")
        n = self.per_100g
        if min(n.kcal, n.protein_g, n.carbs_g, n.fat_g, n.fibre_g or D(0)) < 0:
            raise InvalidInput(f"{self.id}: nutrients can't be negative")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Food":
        """From a JSON entry (numbers parsed as Decimal); bad input is an ``InvalidInput``."""
        try:
            fibre = data["fibre_g"]
            return cls(
                id=data["id"],
                source=FoodSource(data["source"]),
                name=data["name"],
                aliases=tuple(data["aliases"]),
                per_100g=Nutrients(
                    D(data["kcal"]),
                    D(data["protein_g"]),
                    D(data["carbs_g"]),
                    D(data["fat_g"]),
                    None if fibre is None else D(fibre),
                ),
                portions=tuple(Portion(p["label"], D(p["grams"])) for p in data["portions"]),
            )
        except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError) as exc:
            raise InvalidInput(f"bad food {data.get('id')!r}: {exc}") from exc


def nutrients_for(food: Food, grams: Decimal) -> Nutrients:
    """The nutrients in ``grams`` of ``food``."""
    if not 0 < grams <= MAX_GRAMS:
        raise InvalidInput(f"grams must be above 0 and at most {MAX_GRAMS}")
    return food.per_100g.scaled(grams / HUNDRED).quantized()


@dataclass(frozen=True, slots=True)
class FoodItem:
    """One food in a meal. ``nutrients`` is a snapshot taken when it was logged, so a later
    database update never rewrites history. ``extra_uncertainty`` is added to the kind's
    half-width (a modifier we couldn't apply). ``note`` carries the user's own words."""

    food_id: str
    grams: Decimal
    label: str  # how it was said or matched: "1 plate", "350 g"
    nutrients: Nutrients
    kind: EstimateKind = EstimateKind.ESTIMATED
    cooking: Cooking | None = None
    extra_uncertainty: Decimal = NONE
    note: str | None = None
    name: str | None = None  # what to call it when shown: the user's own word, else the food's
    id: UUID | None = None

    def __post_init__(self) -> None:
        if not 0 < self.grams <= MAX_GRAMS:
            raise InvalidInput(f"grams must be above 0 and at most {MAX_GRAMS}")
        if self.extra_uncertainty < 0:
            raise InvalidInput("extra uncertainty can't be negative")


def make_item(
    food: Food,
    grams: Decimal,
    label: str,
    kind: EstimateKind,
    *,
    cooking: Cooking | None = None,
    extra_uncertainty: Decimal = NONE,
    note: str | None = None,
    name: str | None = None,
) -> FoodItem:
    """An item for ``grams`` of ``food`` with the nutrients computed here, from the database."""
    return FoodItem(
        food.id,
        grams,
        label,
        nutrients_for(food, grams),
        kind,
        cooking,
        extra_uncertainty,
        note,
        name,
    )


@dataclass(frozen=True, slots=True)
class MealTotals:
    """The point value and the range around it. ``fibre_g`` sums only the foods that have a
    fibre figure."""

    point: Nutrients
    low: Nutrients
    high: Nutrients


EMPTY_TOTALS = MealTotals(ZERO, ZERO, ZERO)


def item_totals(item: FoodItem) -> MealTotals:
    """An item's point value and range: the kind's half-width plus any extra either side,
    then, for oily cooking, the upper kcal and fat raised by the cooking uplift."""
    half = UNCERTAINTY[item.kind] + item.extra_uncertainty
    point = item.nutrients
    low = point.scaled(max(D(0), 1 - half))
    high = point.scaled(1 + half)
    if item.cooking is not None:
        uplift = COOKING_UPLIFT[item.cooking]
        high = Nutrients(
            high.kcal + point.kcal * uplift,
            high.protein_g,
            high.carbs_g,
            high.fat_g + point.fat_g * uplift,
            high.fibre_g,
        )
    return MealTotals(point, low, high)


def meal_totals(items: Iterable[FoodItem]) -> MealTotals:
    """The sum of the items' points and of their ranges."""
    total = EMPTY_TOTALS
    for item in items:
        t = item_totals(item)
        total = MealTotals(total.point + t.point, total.low + t.low, total.high + t.high)
    return total


def round_to(value: Decimal, step: int = 1) -> Decimal:
    """Round half up to a multiple of ``step``."""
    s = D(step)
    return (value / s).quantize(D(1), rounding=ROUND_HALF_UP) * s


def kcal_range_words(totals: MealTotals, step: int = 10) -> str:
    """ "600-750 kcal", rounded so it doesn't pretend to precision. The en dash is the
    separator the confirm texts use."""
    low, high = round_to(totals.low.kcal, step), round_to(totals.high.kcal, step)
    return f"{low}{EN_DASH}{high} kcal" if low != high else f"{low} kcal"


@dataclass(frozen=True, slots=True)
class MealEntry:
    id: UUID
    user_id: UserId
    meal: MealSlot
    eaten_at: datetime
    source: EntrySource
    note: str | None
    items: tuple[FoodItem, ...]
    created_at: datetime
    updated_at: datetime
    totals: MealTotals = field(init=False)

    def __post_init__(self) -> None:
        if self.eaten_at.tzinfo is None:
            raise InvalidInput("eaten_at needs a time zone")
        object.__setattr__(self, "totals", meal_totals(self.items))


def daily_totals(entries: Iterable[MealEntry], tz: tzinfo) -> dict[date, MealTotals]:
    """Each local day (in ``tz``) that has an entry, with its meals' totals, oldest first."""
    days: dict[date, MealTotals] = defaultdict(lambda: EMPTY_TOTALS)
    for entry in entries:
        day = entry.eaten_at.astimezone(tz).date()
        t = entry.totals
        have = days[day]
        days[day] = MealTotals(have.point + t.point, have.low + t.low, have.high + t.high)
    return dict(sorted(days.items()))


def modifier_scale(modifier: str) -> Decimal | None:
    """The factor a modifier word applies to one component ("less rice" is 0.7), or None."""
    for word in words(modifier):
        if word in MODIFIER_SCALES:
            return MODIFIER_SCALES[word]
    return None


# --- search and portions -------------------------------------------------------------------


def words(text: str) -> list[str]:
    """Lower-case alphanumeric runs: how names and search text are compared."""
    cleaned = "".join(c if c.isalnum() else " " for c in text.casefold())
    return cleaned.split()


STATES = ("raw", "cooked")
EN_DASH = "\N{EN DASH}"


def _rank(name: str, query: str, tokens: Sequence[str]) -> int | None:
    """0 exact, 1 starts with the query, 2 every query word starts a word of the name, 3 every
    query word appears inside the name; else None."""
    if name == query:
        return 0
    if name.startswith(query):
        return 1
    name_words = name.split()
    if all(any(w.startswith(t) for w in name_words) for t in tokens):
        return 2
    if all(t in name for t in tokens):
        return 3
    return None


def search(foods: Iterable[Food], text: str, *, limit: int = 50) -> list[Food]:
    """Foods whose name or alias matches ``text``, best first: exact, then prefix, then
    word starts, then contained. Among equals, a name with the state the query asks for
    ("raw" or "cooked") comes first, then the shorter name."""
    if not 1 <= limit <= MAX_RESULTS:
        raise InvalidInput(f"limit must be between 1 and {MAX_RESULTS}")
    tokens = words(text)
    if not tokens:
        raise InvalidInput("say what to look for")
    query = " ".join(tokens)
    wanted = [s for s in STATES if s in tokens]
    ranked: list[tuple[int, int, int, str, str, Food]] = []
    for food in foods:
        best: int | None = None
        for candidate in (food.name, *food.aliases):
            rank = _rank(" ".join(words(candidate)), query, tokens)
            if rank is not None and (best is None or rank < best):
                best = rank
        if best is None:
            continue
        name_words = words(food.name)
        stated = 0 if not wanted or any(s in name_words for s in wanted) else 1
        ranked.append((best, stated, len(food.name), food.name.casefold(), food.id, food))
    ranked.sort(key=lambda r: r[:5])
    return [r[5] for r in ranked[:limit]]


_UNIT_WORDS = {
    "tbsp": "tablespoon", "tbs": "tablespoon", "tsp": "teaspoon", "oz": "oz", "ounces": "oz",
    "ounce": "oz", "lbs": "lb", "pound": "lb", "pounds": "lb", "ml": "ml", "fl": "fl",
}  # fmt: skip
_NUMBER_WORDS = {"a": D(1), "an": D(1), "one": D(1), "half": D("0.5"), "two": D(2), "three": D(3)}


_FILLER = frozenset({"a", "an", "of", "the"})


def _singular(word: str) -> str:
    word = _UNIT_WORDS.get(word, word)
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _quantity(tokens: list[str]) -> tuple[Decimal, list[str]]:
    """The leading number of a portion text ("2", "1/2", "half", "a") and what is left."""
    if not tokens:
        return D(1), []
    first = tokens[0]
    if first in _NUMBER_WORDS:
        return _NUMBER_WORDS[first], tokens[1:]
    try:
        if "/" in first:
            top, _, bottom = first.partition("/")
            return D(top) / D(bottom), tokens[1:]
        return D(first), tokens[1:]
    except (ArithmeticError, ValueError):
        return D(1), tokens


def _parts(text: str) -> tuple[Decimal, list[str]]:
    """A quantity and the singular words after it. "1/2" survives ``words`` split, so the
    text is cut on spaces first."""
    raw = text.casefold().replace(",", " ").split()
    quantity, rest = _quantity(raw)
    return quantity, [_singular(w) for w in words(" ".join(rest)) if w not in _FILLER]


def portion_grams(food: Food, text: str) -> tuple[Portion, Decimal] | None:
    """Match a spoken portion ("1 cup", "2 tbsp", "half a cup") to one of the food's own
    portions and return it with the weight of the quantity asked for; None when nothing
    matches (the caller then asks). A portion matches when its words, after its leading
    amount, include every word given; an exact set of words wins, then the shortest label."""
    quantity, wanted = _parts(text)
    if not wanted or quantity <= 0:
        return None
    best: tuple[int, int, Portion, Decimal] | None = None
    for portion in food.portions:
        amount, have = _parts(portion.label)
        if amount <= 0 or not all(w in have for w in wanted):
            continue
        key = (0 if set(have) == set(wanted) else 1, len(have))
        if best is None or key < best[:2]:
            best = (key[0], key[1], portion, portion.grams / amount * quantity)
    return None if best is None else (best[2], best[3])
