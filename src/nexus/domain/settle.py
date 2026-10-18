"""Settling up a trip with the people on it: what each owes the other, netted.

Pure rules, no I/O. Nexus never moves money: it works out who owes whom from what the
user recorded, and settling only records what the user says has happened.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId, clean_name, clean_text, same_person
from nexus.domain.money import Money

MAX_PAYMENT_NOTE = 100
# Far beyond any trip, and well inside what the database stores.
MAX_PAYMENT = Decimal("1000000000000")


@dataclass(frozen=True, slots=True)
class PaidByOther:
    """Something a fellow traveller paid for the trip that the user shares in."""

    id: UUID
    user_id: UserId
    trip_id: UUID
    person: str  # who paid
    amount: Money  # the whole bill, in the currency it was paid in
    note: str | None  # what it was for
    paid_on: date
    # The other travellers sharing it, besides the payer and the user (who always
    # share), by name. Everyone's share is an equal part.
    split_with: tuple[str, ...]
    settled_at: datetime | None
    created_at: datetime

    @property
    def settled(self) -> bool:
        return self.settled_at is not None

    @property
    def sharers(self) -> int:
        """How many ways the bill is split: the payer, the user and the others."""
        return 2 + len(self.split_with)

    @property
    def my_share(self) -> Money:
        return my_share_of(self.amount, self.sharers)


def my_share_of(amount: Money, sharers: int) -> Money:
    """The user's equal share of a bill someone else paid. Rounded as ``plan_split``
    does: the user's share comes first, so it takes any leftover minor unit."""
    return amount.allocate(sharers)[0]


def clean_payment_note(raw: str | None) -> str | None:
    return clean_text(raw, field_name="note", limit=MAX_PAYMENT_NOTE)


def check_payment(amount: Money) -> Money:
    """A positive bill in whole minor units (cents; yen), of a size a trip can have."""
    if not amount.is_positive:
        raise InvalidInput("amount must be greater than zero")
    if amount.amount >= MAX_PAYMENT:
        raise InvalidInput("that amount is too large")
    amount.allocate(1)  # refuses fractions of a minor unit
    return amount


def match_traveller(travellers: Iterable[str], name: str) -> str | None:
    """The traveller ``name`` refers to, as the trip spells them: the same name in any
    case, else the one person it plainly matches ("Wei Ming" for "TAN WEI MING")."""
    people = list(travellers)
    wanted = name.strip().casefold()
    for person in people:
        if person.casefold() == wanted:
            return person
    loose = [p for p in people if same_person(p, name)]
    return loose[0] if len(loose) == 1 else None


def clean_split_with(
    travellers: Sequence[str], payer: str, split_with: Sequence[str] | None
) -> tuple[str, ...]:
    """Who else shares the bill, as the trip spells them. None is every traveller; the
    payer is left out of the list (they always share), and so is the user."""
    if split_with is None:
        return tuple(t for t in travellers if t != payer)
    found: list[str] = []
    for raw in split_with:
        name = clean_name(raw, field_name="name")
        person = match_traveller(travellers, name)
        if person is None:
            raise InvalidInput(f"{name} isn't on this trip")
        if person != payer and person not in found:
            found.append(person)
    return tuple(found)


# --- who owes whom ---------------------------------------------------------------------


class DebtKind(StrEnum):
    IOU = "iou"  # a share of a bill the user paid, which someone owes them
    PAYMENT = "payment"  # the user's share of a bill someone else paid


@dataclass(frozen=True, slots=True)
class Debt:
    """One thing owed between the user and one person, in its own currency and (when
    there is a rate) the home currency."""

    kind: DebtKind
    ref: UUID  # the split (IOU) or the payment
    name: str
    amount: Money
    home: Money | None
    label: str | None
    on: date


class Direction(StrEnum):
    OWES_YOU = "owes_you"
    YOU_OWE = "you_owe"
    EVEN = "even"


@dataclass(frozen=True, slots=True)
class PersonBalance:
    """Where the user stands with one person: what they owe the user less what the
    user owes them."""

    name: str
    owes_you: list[Debt]
    you_owe: list[Debt]
    # In the home currency, positive when they owe the user; None when a part has no
    # exchange rate yet.
    net_home: Money | None
    # The same per currency, signed the same way, for when a rate is missing.
    net_by_currency: list[Money]

    @property
    def direction(self) -> Direction | None:
        """None when the net isn't known (no rate) and the currencies don't agree."""
        if self.net_home is not None:
            amount = self.net_home.amount
        elif len(self.net_by_currency) == 1:
            amount = self.net_by_currency[0].amount
        else:
            return None
        if amount > 0:
            return Direction.OWES_YOU
        return Direction.YOU_OWE if amount < 0 else Direction.EVEN


def _person(known: list[str], travellers: Sequence[str], name: str) -> str:
    """The name a person goes by here: how the trip spells them, else the first way
    they were written."""
    for pool in (travellers, known):
        found = match_traveller(pool, name)
        if found is not None:
            return found
    return name.strip()


def settle_up(
    owed_to_me: Iterable[Debt],
    owed_by_me: Iterable[Debt],
    home: str,
    *,
    travellers: Sequence[str] = (),
) -> list[PersonBalance]:
    """One balance per person, A to Z: what they owe the user less what the user owes
    them, in the home currency. Names are matched as ``same_person`` does, and written
    as the trip spells them (``travellers``) when it names them."""
    known: list[str] = []
    mine: dict[str, list[Debt]] = {}
    theirs: dict[str, list[Debt]] = {}
    for debts, into in ((owed_to_me, mine), (owed_by_me, theirs)):
        for debt in debts:
            person = _person(known, travellers, debt.name)
            if person not in known:
                known.append(person)
            into.setdefault(person, []).append(debt)

    balances: list[PersonBalance] = []
    for person in sorted(known, key=str.casefold):
        owes, owing = mine.get(person, []), theirs.get(person, [])
        net: Money | None = Money.zero(home)
        by_currency: dict[str, Decimal] = {}
        for sign, debts in ((1, owes), (-1, owing)):
            for debt in debts:
                if net is not None and debt.home is not None:
                    net = net + debt.home if sign > 0 else net - debt.home
                else:
                    net = None
                currency = debt.amount.currency
                by_currency[currency] = by_currency.get(currency, Decimal(0)) + (
                    debt.amount.amount * sign
                )
        balances.append(
            PersonBalance(
                name=person,
                owes_you=owes,
                you_owe=owing,
                net_home=net,
                net_by_currency=[Money(v, c) for c, v in sorted(by_currency.items())],
            )
        )
    return balances


def describe_balance(balance: PersonBalance) -> str:
    """ "Alex owes you 538.00 SGD", "You owe Sam 40.00 SGD", for chat."""
    net = balance.net_home
    if net is not None:
        if net.amount > 0:
            return f"{balance.name} owes you {net}"
        if net.amount < 0:
            return f"You owe {balance.name} {-net}"
        return f"You and {balance.name} are even"
    owes = ", ".join(str(m) for m in balance.net_by_currency if m.amount > 0)
    owing = ", ".join(str(-m) for m in balance.net_by_currency if m.amount < 0)
    parts = []
    if owes:
        parts.append(f"{balance.name} owes you {owes}")
    if owing:
        parts.append(f"you owe {balance.name} {owing}")
    if not parts:
        return f"You and {balance.name} are even"
    return "; ".join(parts) + " (no exchange rate yet, so no single total)"
