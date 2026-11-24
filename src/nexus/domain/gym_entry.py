"""Reading what a person types in the gym: "3x5 at 80", "3 by 8 at 60kg RPE 8", "last week".
Pure rules, no I/O. Every number comes from the user's own words: nothing is guessed or worked out.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from nexus.domain.errors import InvalidInput
from nexus.domain.gym import Exercise, words
from nexus.domain.gym_training import SetKind, WeightUnit, week_start

MAX_SETS_AT_ONCE = 30
MAX_RANGE_DAYS = 366

# What people call the common lifts, to the catalogue's own id. Without these "bench" matches
# a dozen exercises and Prime would have to ask every time.
ALIASES: dict[str, str] = {
    "bench": "Barbell_Bench_Press_-_Medium_Grip",
    "bench press": "Barbell_Bench_Press_-_Medium_Grip",
    "barbell bench press": "Barbell_Bench_Press_-_Medium_Grip",
    "flat bench": "Barbell_Bench_Press_-_Medium_Grip",
    "squat": "Barbell_Squat",
    "squats": "Barbell_Squat",
    "back squat": "Barbell_Squat",
    "barbell squat": "Barbell_Squat",
    "front squat": "Front_Barbell_Squat",
    "deadlift": "Barbell_Deadlift",
    "deadlifts": "Barbell_Deadlift",
    "barbell deadlift": "Barbell_Deadlift",
    "rdl": "Romanian_Deadlift",
    "romanian deadlift": "Romanian_Deadlift",
    "ohp": "Standing_Military_Press",
    "overhead press": "Standing_Military_Press",
    "military press": "Standing_Military_Press",
    "shoulder press": "Standing_Military_Press",
    "barbell row": "Bent_Over_Barbell_Row",
    "bent over row": "Bent_Over_Barbell_Row",
    "row": "Bent_Over_Barbell_Row",
    "barbell curl": "Barbell_Curl",
}


def alias_id(query: str) -> str | None:
    """The catalogue id a common name stands for, if it is one."""
    return ALIASES.get(" ".join(words(query)))


def unambiguous(query: str, found: Sequence[Exercise]) -> Exercise | None:
    """The one exercise ``query`` clearly means among ``found``: the only match, or the only
    one whose name is the query. None when it could be several (ask the user)."""
    if len(found) == 1:
        return found[0]
    wanted = words(query)
    exact = [e for e in found if words(e.name) == wanted]
    return exact[0] if len(exact) == 1 else None


# --- sets ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedSet:
    reps: int | None = None
    seconds: int | None = None
    weight: Decimal | None = None
    unit: WeightUnit | None = None  # None: the user didn't say
    rpe: Decimal | None = None
    kind: SetKind = SetKind.WORKING


_SPLIT = re.compile(r"\s*(?:,\s+|;|\+|\bthen\b|\band\b)\s*")
_RPE = re.compile(r"\b(?:@\s*)?rpe\s*(\d+(?:\.\d+)?)")
_WARMUP = re.compile(r"\bwarm\s*-?\s*ups?\b")
_BODYWEIGHT = re.compile(r"\b(?:bw|body\s*weight|bodyweight)\b")
_SECS = r"(?:seconds?|secs?|s)"
_BLOCK = re.compile(
    rf"(?P<count>\d{{1,2}})\s*(?:x|\u00d7|\*|by|sets?\s+of|sets?\s+x)\s*(?P<n>\d{{1,5}})"
    rf"(?:\s*(?P<secs>{_SECS}))?\b"
)
_ONE = re.compile(rf"\b(?P<n>\d{{1,5}})\s*(?:(?P<reps>reps?)|(?P<secs>{_SECS}))\b")
_WEIGHT = re.compile(
    r"(?:\b(?:at|with|using)\s+|@\s*)?(?<![\d.])(?P<w>\d+(?:[.,]\d+)?)\s*"
    r"(?P<u>kgs?|kilos?|kilograms?|lbs?|pounds?)?\b"
)


def _number(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation as exc:  # pragma: no cover - the patterns only pass digits
        raise InvalidInput(f"{text!r} isn't a number") from exc


def _unit(text: str | None) -> WeightUnit | None:
    if text is None:
        return None
    return WeightUnit.LB if text.startswith(("lb", "pound")) else WeightUnit.KG


def _chunk(text: str) -> list[ParsedSet]:
    rest = text.casefold().strip()
    rpe: Decimal | None = None
    if found := _RPE.search(rest):
        rpe = _number(found[1])
        rest = rest[: found.start()] + " " + rest[found.end() :]
    kind = SetKind.WORKING
    if _WARMUP.search(rest):
        kind = SetKind.WARMUP
        rest = _WARMUP.sub(" ", rest)
    rest = _BODYWEIGHT.sub(" ", rest)
    count, reps, seconds = 1, None, None
    if block := _BLOCK.search(rest):
        count = int(block["count"])
        number = int(block["n"])
        reps, seconds = (None, number) if block["secs"] else (number, None)
        rest = rest[: block.start()] + " " + rest[block.end() :]
    elif one := _ONE.search(rest):
        number = int(one["n"])
        reps, seconds = (None, number) if one["secs"] else (number, None)
        rest = rest[: one.start()] + " " + rest[one.end() :]
    else:
        raise InvalidInput(
            f"couldn't read {text.strip()!r} as sets: say it like '3x5 at 80 kg' or "
            "'8 reps at 60 kg'"
        )
    if not 1 <= count <= MAX_SETS_AT_ONCE:
        raise InvalidInput(f"log from 1 to {MAX_SETS_AT_ONCE} sets at a time")
    weight, unit = None, None
    if heavy := _WEIGHT.search(rest):
        weight, unit = _number(heavy["w"]), _unit(heavy["u"])
    return [ParsedSet(reps, seconds, weight, unit, rpe, kind)] * count


def parse_sets(text: str) -> list[ParsedSet]:
    """The sets in what the user typed, in order: "3x5 at 80", "3 by 8 at 60kg RPE 8",
    "warm-up 2x5 at 40, 3x5 at 80", "5 reps at 60 lb", "3x60s". A weight with no unit has
    ``unit`` None; no weight (or "bodyweight") means none. Raises ``InvalidInput`` if any
    part can't be read, or for more than 30 sets."""
    sets: list[ParsedSet] = []
    for part in _SPLIT.split(text):
        if part.strip():
            sets.extend(_chunk(part))
    if not sets:
        raise InvalidInput("no sets to log: say it like '3x5 at 80 kg'")
    if len(sets) > MAX_SETS_AT_ONCE:
        raise InvalidInput(f"log from 1 to {MAX_SETS_AT_ONCE} sets at a time")
    return sets


# --- dates --------------------------------------------------------------------------------------

RANGES = (
    "today, yesterday, this week, last week, this month, last month, last 7 days (any number up "
    "to 366), a date like 2026-09-14, or two dates like 2026-09-01 to 2026-09-14"
)
_DAYS = re.compile(r"(?:last|past)\s+(\d{1,3})\s+days?")
_DATES = re.compile(r"(\d{4}-\d{2}-\d{2})(?:\s*(?:to|\.\.|-|until)\s*(\d{4}-\d{2}-\d{2}))?")


def _iso(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise InvalidInput(f"{text!r} isn't a date (like 2026-09-14)") from exc


def _first_of_next_month(day: date) -> date:
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def parse_range(text: str, today: date) -> tuple[date, date]:
    """``(first day, day after the last)`` for a range of days the user named; weeks start on
    Monday. Raises ``InvalidInput`` for anything else, saying what is understood."""
    said = " ".join(text.casefold().replace("_", " ").split())
    if said == "today":
        return today, today + timedelta(days=1)
    if said == "yesterday":
        return today - timedelta(days=1), today
    if said in ("this week", "week"):
        start = week_start(today)
        return start, start + timedelta(days=7)
    if said == "last week":
        start = week_start(today) - timedelta(days=7)
        return start, start + timedelta(days=7)
    if said in ("this month", "month"):
        first = today.replace(day=1)
        return first, _first_of_next_month(first)
    if said == "last month":
        end = today.replace(day=1)
        return (end - timedelta(days=1)).replace(day=1), end
    if days := _DAYS.fullmatch(said):
        n = int(days[1])
        if not 1 <= n <= MAX_RANGE_DAYS:
            raise InvalidInput(f"a range is from 1 to {MAX_RANGE_DAYS} days")
        return today - timedelta(days=n - 1), today + timedelta(days=1)
    if dates := _DATES.fullmatch(said):
        start = _iso(dates[1])
        end = _iso(dates[2]) if dates[2] else start
        if end < start or (end - start).days >= MAX_RANGE_DAYS:
            raise InvalidInput(f"a range is from 1 to {MAX_RANGE_DAYS} days, oldest first")
        return start, end + timedelta(days=1)
    raise InvalidInput(f"I can read: {RANGES}")


def parse_week(text: str | None, today: date) -> date:
    """The Monday of the week the user means: none or "this week", "last week", or any date
    in the week (2026-09-14)."""
    said = " ".join((text or "this week").casefold().split())
    if said in ("this week", "last week"):
        return parse_range(said, today)[0]
    if _DATES.fullmatch(said) and " " not in said:
        return week_start(_iso(said))
    raise InvalidInput("a week is 'this week', 'last week' or a date in it like 2026-09-14")
