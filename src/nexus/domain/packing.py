"""A trip's packing list: what to bring, ticked off as it's packed, and suggestions
worked out from the trip (abroad or not, its length, the season, the weather)."""

from dataclasses import dataclass
from typing import Any

from nexus.domain.destination_photos import Season
from nexus.domain.errors import InvalidInput

MAX_ITEMS = 80
MAX_ITEM = 60


@dataclass(frozen=True, slots=True)
class PackItem:
    text: str
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "done": self.done}


def from_rows(rows: Any) -> tuple[PackItem, ...]:
    """Stored items, skipping anything malformed."""
    items = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("text"), str) and row["text"].strip():
            items.append(PackItem(row["text"][:MAX_ITEM], bool(row.get("done"))))
    return tuple(items[:MAX_ITEMS])


def clean_list(items: list[PackItem]) -> tuple[PackItem, ...]:
    """The list as the user gave it, each item once (by its words, ignoring case),
    blank ones dropped. Raises InvalidInput past MAX_ITEMS."""
    seen: set[str] = set()
    out = []
    for item in items:
        printable = "".join(c for c in item.text if c.isprintable())
        text = " ".join(printable.split())[:MAX_ITEM]
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(PackItem(text, item.done))
    if len(out) > MAX_ITEMS:
        raise InvalidInput(f"keep at most {MAX_ITEMS} things on the packing list")
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Outlook:
    """What the weather looks like for the trip, as far as it's known."""

    low: float | None = None  # coldest night, °C
    high: float | None = None  # warmest day, °C
    rain: bool = False  # rain likely on some day


def suggestions(*, abroad: bool, nights: int, season: Season, outlook: Outlook | None) -> list[str]:
    """Things most trips like this need, most important first."""
    found = []
    if abroad:
        found += ["Passport", "Travel adapter", "Travel insurance details", "Some local cash"]
    found += ["Phone charger", "Toiletries", "Medicines you take"]
    days = max(nights, 1)
    found.append(f"Clothes for {min(days, 7)} {'day' if days == 1 else 'days'}")
    if days > 7:
        found.append("Laundry bag")
    if abroad:
        found.append("eSIM or pocket wifi")
    cold = (outlook and outlook.low is not None and outlook.low < 10) or season is Season.WINTER
    hot = (outlook and outlook.high is not None and outlook.high > 27) or season is Season.SUMMER
    if outlook is None and season is Season.ANY:
        hot = True  # the tropics
    if cold:
        found += ["Warm jacket", "Layers"]
    if outlook and outlook.low is not None and outlook.low < 2:
        found += ["Gloves and a hat"]
    if hot:
        found += ["Sunscreen", "Sunglasses", "Light clothes"]
    if (outlook and outlook.rain) or (outlook is None and season is Season.ANY):
        found.append("Umbrella or rain jacket")
    found.append("Comfortable walking shoes")
    return found
