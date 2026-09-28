"""Converting foreign amounts into the user's home currency at dated rates.

A transaction converts at the latest reference rate published on or before its
own date, never a later one. When no such rate is available the conversion is
reported as unavailable rather than guessed. Stored amounts are never changed:
a conversion is a view beside the original.
"""

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from nexus.domain.money import Money, minor_units

# Parallel rate lookups per request; the provider is a small public service.
_CONCURRENCY = 4


@dataclass(frozen=True, slots=True)
class Rate:
    base: str
    quote: str
    value: Decimal  # one unit of base in quote
    effective: date  # the day the rate was published, on or before the date asked for


class RateSource(Protocol):
    async def rate(self, base: str, quote: str, on: date) -> Rate | None:
        """The latest rate published on or before ``on``, or None if unavailable."""
        ...


@dataclass(frozen=True, slots=True)
class Conversion:
    original: Money
    home: Money | None  # None when no rate was available
    rate: Rate | None


def apply(amount: Money, rate: Rate) -> Money:
    unit = Decimal(1).scaleb(-minor_units(rate.quote))
    return Money((amount.amount * rate.value).quantize(unit, rounding=ROUND_HALF_UP), rate.quote)


async def rates_for(
    source: RateSource, home: str, wanted: Iterable[tuple[str, date]]
) -> dict[tuple[str, date], Rate | None]:
    """Look up each distinct (currency, day) once; home-currency pairs are skipped."""
    pairs = sorted({(currency, day) for currency, day in wanted if currency != home})
    gate = asyncio.Semaphore(_CONCURRENCY)

    async def one(currency: str, day: date) -> Rate | None:
        async with gate:
            found = await source.rate(currency, home, day)
        # Defend the rule even against a misbehaving provider.
        if found is None or found.effective > day or found.value <= 0:
            return None
        return found

    results = await asyncio.gather(*(one(c, d) for c, d in pairs))
    return dict(zip(pairs, results, strict=True))


def convert(
    amount: Money, day: date, home: str, rates: dict[tuple[str, date], Rate | None]
) -> Conversion:
    if amount.currency == home:
        return Conversion(amount, amount, None)
    rate = rates.get((amount.currency, day))
    return Conversion(amount, apply(amount, rate) if rate else None, rate)
