"""Holdings: what the user owns, and what it cost them. Pure rules, no I/O.

Research only: nothing here places a trade or talks to a broker. Positions come
from a screenshot of the user's broker (read, then confirmed by the user) or from
what they type ("I bought 10 NVDA at 118").
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
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


def realised(held: Position, quantity: Decimal, price: Money) -> Money:
    """What selling ``quantity`` at ``price`` locked in against the average cost, as
    brokers show it (average-cost method; below zero for a loss)."""
    if price.currency != held.average_cost.currency:
        raise InvalidInput(
            f"{held.symbol} is held in {held.average_cost.currency}, not {price.currency}"
        )
    return _money(quantity * (price.amount - held.average_cost.amount), price.currency)


# --- trades ---------------------------------------------------------------------------


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True, slots=True)
class Trade:
    """A trade the user made at their broker and told Nexus about."""

    id: UUID
    user_id: UserId
    symbol: str
    side: TradeSide
    quantity: Decimal
    price: Money | None  # per share; a sale told without its price has none
    traded_on: date
    realised: Money | None  # a sale's gain or loss against the average cost
    created_at: datetime


def held_on(quantity_now: Decimal, trades: list[Trade], day: date) -> Decimal:
    """Shares held at the end of ``day``, worked back from today's quantity through
    the trades made after it."""
    held = quantity_now
    for t in trades:
        if t.traded_on > day:
            held += -t.quantity if t.side is TradeSide.BUY else t.quantity
    return max(held, Decimal(0))


# --- dividends ------------------------------------------------------------------------

# Tax withheld from dividends at source, by the price's currency, for a Singapore
# resident: the US takes 30% (no treaty); Singapore, Hong Kong and the UK take none.
WITHHOLDING: dict[str, Decimal] = {"USD": Decimal("0.30")}


def withholding_rate(currency: str) -> Decimal:
    return WITHHOLDING.get(currency, Decimal(0))


@dataclass(frozen=True, slots=True)
class Dividend:
    """A dividend on shares the user held when it went ex."""

    id: UUID
    user_id: UserId
    symbol: str
    ex_date: date
    per_share: Money
    shares: Decimal
    created_at: datetime

    @property
    def gross(self) -> Money:
        return _money(self.shares * self.per_share.amount, self.per_share.currency)

    @property
    def withheld(self) -> Money:
        rate = withholding_rate(self.per_share.currency)
        return _money(self.gross.amount * rate, self.per_share.currency)

    @property
    def net(self) -> Money:
        return self.gross - self.withheld


@dataclass(frozen=True, slots=True)
class Expected:
    """A stock's dividends over the next year if it pays what it paid in the last one."""

    symbol: str
    per_share: Money  # the last 12 months' dividends per share
    payments: int  # how many in those 12 months
    net: Money  # on today's shares, after withholding
    yield_on_value: Decimal | None  # the 12-month dividends over today's price, %
    yield_on_cost: Decimal | None  # over the average cost, %


def expected(
    position: Position, past_year: list[Decimal], price: Decimal | None
) -> Expected | None:
    """From the dividends per share paid in the last 12 months, oldest first."""
    if not past_year:
        return None
    currency = position.average_cost.currency
    per_share = sum(past_year, Decimal(0))
    gross = position.quantity * per_share
    net = gross * (1 - withholding_rate(currency))
    hundred = Decimal(100)
    on_value = (per_share / price * hundred).quantize(Decimal("0.01")) if price else None
    cost = position.average_cost.amount
    on_cost = (per_share / cost * hundred).quantize(Decimal("0.01")) if cost else None
    return Expected(
        position.symbol, _money(per_share, currency), len(past_year), _money(net, currency),
        on_value, on_cost,
    )  # fmt: skip
