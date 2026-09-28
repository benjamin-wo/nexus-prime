"""Exact money. Amounts are Decimals with at most 4 decimal places; never floats."""

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Self

from nexus.domain.errors import InvalidInput

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_SCALE = Decimal("0.0001")
# NUMERIC(19,4) holds up to 15 integer digits.
_LIMIT = Decimal(10) ** 15

# ISO 4217 minor units for currencies that do not use 2 decimals.
_MINOR_UNITS = {
    "BHD": 3, "CLP": 0, "IQD": 3, "ISK": 0, "JOD": 3, "JPY": 0, "KRW": 0,
    "KWD": 3, "LYD": 3, "OMR": 3, "PYG": 0, "TND": 3, "UGX": 0, "VND": 0,
}  # fmt: skip


def minor_units(currency: str) -> int:
    return _MINOR_UNITS.get(currency, 2)


@dataclass(frozen=True, slots=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal) or isinstance(self.amount, bool):
            raise InvalidInput("money amount must be a Decimal")
        if not self.amount.is_finite():
            raise InvalidInput("money amount must be finite")
        if not isinstance(self.currency, str) or not _CURRENCY.match(self.currency):
            raise InvalidInput(f"invalid currency code {self.currency!r}")
        quantized = self.amount.quantize(_SCALE)
        if quantized != self.amount:
            raise InvalidInput("money amount has more than 4 decimal places")
        if abs(quantized) >= _LIMIT:
            raise InvalidInput("money amount is too large")
        object.__setattr__(self, "amount", quantized)

    @classmethod
    def of(cls, amount: str | int | Decimal, currency: str) -> Self:
        if isinstance(amount, float | bool):
            raise InvalidInput("money amount must not be a float")
        try:
            value = Decimal(str(amount).strip()) if isinstance(amount, str) else Decimal(amount)
        except InvalidOperation as exc:
            raise InvalidInput(f"invalid amount {amount!r}") from exc
        return cls(value, currency.strip().upper())

    @classmethod
    def zero(cls, currency: str) -> Self:
        return cls(Decimal(0), currency)

    def _same(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise InvalidInput(f"cannot combine {self.currency} and {other.currency}")

    def __add__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount + other.amount, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same(other)
        return Money(self.amount - other.amount, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.amount, self.currency)

    def __lt__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._same(other)
        return self.amount >= other.amount

    @property
    def is_positive(self) -> bool:
        return self.amount > 0

    @property
    def is_zero(self) -> bool:
        return self.amount == 0

    def min(self, other: "Money") -> "Money":
        return self if self <= other else other

    def allocate(self, parts: int) -> list["Money"]:
        """Split into ``parts`` shares in the currency's minor unit.

        Shares differ by at most one minor unit; earlier shares take the
        remainder, so the result always sums back to exactly this amount.
        """
        if parts < 1:
            raise InvalidInput("cannot allocate into fewer than 1 part")
        if self.amount < 0:
            raise InvalidInput("cannot allocate a negative amount")
        unit = Decimal(1).scaleb(-minor_units(self.currency))
        if self.amount != self.amount.quantize(unit):
            raise InvalidInput(f"{self} is not a whole number of {self.currency} minor units")
        base = (self.amount / parts).quantize(unit, rounding=ROUND_DOWN)
        remainder = int((self.amount - base * parts) / unit)
        return [Money(base + (unit if i < remainder else 0), self.currency) for i in range(parts)]

    def __str__(self) -> str:
        shown = self.amount.quantize(Decimal(1).scaleb(-minor_units(self.currency)))
        return f"{shown} {self.currency}"
