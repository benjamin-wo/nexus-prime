"""Holdings: what the user owns, and what it cost them. Pure rules, no I/O.

Research only: nothing here places a trade or talks to a broker. Positions come
from a screenshot of the user's broker (read, then confirmed by the user) or from
what they type ("I bought 10 NVDA at 118").
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.money import Money

# A US ticker as brokers show it: "NVDA", "BRK.B", "BF-B".
_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z0-9]{1,2})?$")
MAX_POSITIONS = 100
_CENTS = Decimal("0.0001")


def _money(amount: Decimal, currency: str) -> Money:
    """An amount rounded to what Money keeps (4 places): averages rarely divide evenly."""
    return Money(amount.quantize(_CENTS, rounding=ROUND_HALF_UP), currency)


def clean_symbol(raw: str) -> str:
    symbol = raw.strip().upper().removeprefix("$")
    if not _SYMBOL.match(symbol):
        raise InvalidInput(f"{raw!r} doesn't look like a stock ticker")
    return symbol


def plain(quantity: Decimal) -> Decimal:
    """Without trailing zeros, and never in exponent form ("10", not "1E+1")."""
    trimmed = quantity.normalize()
    return trimmed.quantize(Decimal(1)) if trimmed == trimmed.to_integral() else trimmed


def clean_quantity(raw: Decimal | str | float | int) -> Decimal:
    try:
        quantity = Decimal(str(raw).replace(",", ""))
    except InvalidOperation as exc:
        raise InvalidInput(f"{raw!r} isn't a number of shares") from exc
    if not quantity.is_finite() or quantity <= 0:
        raise InvalidInput("a number of shares must be more than zero")
    return plain(quantity)


@dataclass(frozen=True, slots=True)
class Position:
    """One stock and how much of it, at what average cost per share."""

    symbol: str
    quantity: Decimal
    average_cost: Money

    def __post_init__(self) -> None:
        if self.average_cost.amount < 0:
            raise InvalidInput("an average cost can't be negative")

    @property
    def cost(self) -> Money:
        return _money(self.quantity * self.average_cost.amount, self.average_cost.currency)

    def as_dict(self) -> dict[str, str]:
        return {
            "symbol": self.symbol,
            "quantity": str(self.quantity),
            "average_cost": str(self.average_cost.amount),
            "currency": self.average_cost.currency,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Position":
        return cls(
            clean_symbol(data["symbol"]),
            clean_quantity(data["quantity"]),
            _money(Decimal(data["average_cost"]), data["currency"]),
        )


@dataclass(frozen=True, slots=True)
class Holding:
    id: UUID
    user_id: UserId
    position: Position
    created_at: datetime
    updated_at: datetime


class DraftStatus(StrEnum):
    WAITING = "waiting"  # read from a screenshot, waiting for the user
    SAVED = "saved"
    DISCARDED = "discarded"


@dataclass(frozen=True, slots=True)
class HoldingsDraft:
    """Positions read from a screenshot, kept until the user saves or drops them."""

    id: UUID
    user_id: UserId
    positions: list[Position]
    status: DraftStatus
    created_at: datetime


def merge_positions(positions: list[Position]) -> list[Position]:
    """One position per ticker (a screenshot can list a stock twice, across
    accounts): quantities add up and the average cost is weighted by them."""
    merged: dict[str, Position] = {}
    for p in positions:
        before = merged.get(p.symbol)
        if before is None:
            merged[p.symbol] = p
            continue
        if before.average_cost.currency != p.average_cost.currency:
            raise InvalidInput(f"{p.symbol} is listed in two currencies")
        quantity = before.quantity + p.quantity
        cost = before.cost.amount + p.cost.amount
        merged[p.symbol] = Position(
            p.symbol, quantity, _money(cost / quantity, p.average_cost.currency)
        )
    if len(merged) > MAX_POSITIONS:
        raise InvalidInput(f"that's more than {MAX_POSITIONS} positions")
    return sorted(merged.values(), key=lambda p: p.symbol)


def _shares(quantity: Decimal) -> str:
    return f"{quantity:,f}".rstrip("0").rstrip(".") if "." in f"{quantity:f}" else f"{quantity:,f}"


def describe_position(p: Position) -> str:
    return f"{p.symbol}: {_shares(p.quantity)} at {p.average_cost} avg"


def changes(current: list[Position], proposed: list[Position]) -> list[str]:
    """What saving ``proposed`` (a whole portfolio) would change, in words."""
    before = {p.symbol: p for p in current}
    after = {p.symbol: p for p in proposed}
    lines = []
    for symbol in sorted(before.keys() | after.keys()):
        old, new = before.get(symbol), after.get(symbol)
        if old is None and new is not None:
            lines.append(f"+ {describe_position(new)} (new)")
        elif new is None and old is not None:
            lines.append(f"- {symbol}: gone (was {_shares(old.quantity)})")
        elif old is not None and new is not None and old != new:
            if old.quantity != new.quantity:
                diff = new.quantity - old.quantity
                sign = "+" if diff > 0 else "-"
                lines.append(
                    f"{sign} {symbol}: {_shares(old.quantity)} → {_shares(new.quantity)} shares"
                )
            else:
                lines.append(f"~ {symbol}: average cost {old.average_cost} → {new.average_cost}")
    return lines


def buy(held: Position | None, symbol: str, quantity: Decimal, price: Money) -> Position:
    """A purchase: more shares, and the average cost weighted by what was paid."""
    if held is None:
        return Position(symbol, quantity, price)
    if held.average_cost.currency != price.currency:
        raise InvalidInput(
            f"{symbol} is held in {held.average_cost.currency}, not {price.currency}"
        )
    total = held.quantity + quantity
    cost = held.cost.amount + quantity * price.amount
    return Position(symbol, total, _money(cost / total, price.currency))


def sell(held: Position | None, symbol: str, quantity: Decimal) -> Position | None:
    """A sale: fewer shares at the same average cost; None when none are left."""
    if held is None:
        raise InvalidInput(f"you don't hold any {symbol}")
    if quantity > held.quantity:
        raise InvalidInput(f"you only hold {_shares(held.quantity)} {symbol}")
    left = held.quantity - quantity
    return None if left == 0 else Position(symbol, left, held.average_cost)
