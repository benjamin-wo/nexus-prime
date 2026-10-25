"""Splitting habits: "I always split dinners with Ann 50/50".

A habit is a default the code applies when the user logs an expense: it names a person, the
category it holds for (or any category) and the person's share of the bill. The model may
override it for one expense ("my treat tonight"); it never has to remember it.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import ShareRequest, UserId, clean_name, same_person
from nexus.domain.money import Money, minor_units

DEFAULT_SHARE = Decimal("0.5")
_SHARE_SCALE = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class SplitHabit:
    id: UUID
    user_id: UserId
    person: str  # as the user wrote it
    applies_to: str | None  # a category name; None: any category
    share: Decimal  # the other person's share of the bill, between 0 and 1 exclusive
    created_at: datetime

    def describe(self) -> str:
        where = f"{self.applies_to} expenses" if self.applies_to else "any expense"
        return f"{where} with {self.person}: their share {percent(self.share)}"


def percent(share: Decimal) -> str:
    """0.5 as "50%", 0.3333 as "33.33%"."""
    shown = (share * 100).quantize(Decimal("0.01")).normalize()
    return f"{shown:f}%"


def clean_share(value: Decimal) -> Decimal:
    """A share strictly between 0 and 1, to 4 decimal places."""
    share = value.quantize(_SHARE_SCALE, rounding=ROUND_HALF_UP) if value.is_finite() else value
    if not share.is_finite() or not Decimal(0) < share < Decimal(1):
        raise InvalidInput("a share is between 0 and 100 percent, neither included")
    return share


def parse_share(text: str | None) -> Decimal:
    """A share as people write it: "0.4", "40%" or "1/3". None: an equal two-way split."""
    if text is None or not text.strip():
        return DEFAULT_SHARE
    raw = text.strip().replace(" ", "")
    try:
        if raw.endswith("%"):
            value = Decimal(raw[:-1]) / 100
        elif "/" in raw:
            top, _, bottom = raw.partition("/")
            value = Decimal(top) / Decimal(bottom)
        else:
            value = Decimal(raw)
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise InvalidInput(f"can't read {text!r} as a share; try 0.5, 50% or 1/3") from exc
    return clean_share(value)


def clean_habit(
    person: str, applies_to: str | None, share: Decimal
) -> tuple[str, str | None, Decimal]:
    """The person's name, category and share, checked and tidied."""
    name = clean_name(" ".join(person.split()), field_name="person")
    category = " ".join(applies_to.split()) if applies_to else None
    return name, category or None, clean_share(share)


def select_for_removal(
    habits: list[SplitHabit], person: str, applies_to: str | None = None
) -> list[SplitHabit]:
    """The habits "stop splitting with Ann" (or "...dinners with Ann") refers to.

    Without a category, all of the person's habits. The name matches as written (any case);
    failing that, the one person it plainly refers to ("Ann" for "Ann Lee")."""
    wanted = person.strip().casefold()
    people = {h.person for h in habits}
    exact = [p for p in people if p.casefold() == wanted]
    if exact:
        chosen = set(exact)
    else:
        loose = [p for p in people if same_person(p, person)]
        chosen = set(loose) if len(loose) == 1 else set()
    return [
        h
        for h in habits
        if h.person in chosen
        and (applies_to is None or (h.applies_to or "").casefold() == applies_to.casefold())
    ]


def matching(habits: list[SplitHabit], category: str | None) -> list[SplitHabit]:
    """The habits that hold for an expense in ``category``.

    Habits for that very category beat the "any category" ones: if there are any, only they
    apply (dinners with Ann, not also "everything with Ben"). Otherwise the "any category"
    habits do. A split can be with several people, so this is all of them, one per person."""
    named = (category or "").casefold()
    specific = [h for h in habits if h.applies_to and h.applies_to.casefold() == named]
    chosen = specific or [h for h in habits if h.applies_to is None]
    seen: set[str] = set()
    result: list[SplitHabit] = []
    for habit in sorted(chosen, key=lambda h: (h.created_at, h.person.casefold())):
        if habit.person.casefold() not in seen:
            seen.add(habit.person.casefold())
            result.append(habit)
    return result


def habit_shares(total: Money, habits: list[SplitHabit]) -> list[ShareRequest]:
    """What each person owes of ``total`` under their habit, rounded down to the currency's
    smallest unit so a friend is never charged more than their share. The user keeps the
    rest. People whose share rounds to nothing are left out."""
    unit = Decimal(1).scaleb(-minor_units(total.currency))
    requests: list[ShareRequest] = []
    for habit in habits:
        owed = (total.amount * habit.share).quantize(unit, rounding=ROUND_DOWN)
        if owed > 0:
            requests.append(ShareRequest(habit.person, Money(owed, total.currency)))
    if sum((r.share.amount for r in requests if r.share), Decimal(0)) > total.amount:
        raise InvalidInput("the split habits add up to more than the whole bill")
    return requests
