"""Holdings rules: tickers, merging a screenshot's rows, what saving would change,
and buying and selling at an average cost. Every figure here is made up."""

from decimal import Decimal

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.investments import (
    Position,
    buy,
    changes,
    clean_quantity,
    clean_symbol,
    merge_positions,
    sell,
)
from nexus.domain.money import Money


def usd(amount: str) -> Money:
    return Money(Decimal(amount), "USD")


def pos(symbol: str, quantity: str, cost: str) -> Position:
    return Position(symbol, Decimal(quantity), usd(cost))


def test_tickers_and_quantities() -> None:
    assert clean_symbol(" nvda ") == "NVDA"
    assert clean_symbol("$brk.b") == "BRK.B"
    for bad in ("", "TOTAL VALUE", "123", "NVDA!"):
        with pytest.raises(InvalidInput):
            clean_symbol(bad)
    assert clean_quantity("1,250.50") == Decimal("1250.5")
    with pytest.raises(InvalidInput):
        clean_quantity("0")


def test_a_ticker_listed_twice_is_one_position_at_the_weighted_cost() -> None:
    merged = merge_positions(
        [pos("NVDA", "10", "100"), pos("AAPL", "1", "190"), pos("NVDA", "30", "120")]
    )
    assert merged == [pos("AAPL", "1", "190"), pos("NVDA", "40", "115")]


def test_what_saving_would_change() -> None:
    held = [pos("AAPL", "5", "190"), pos("NVDA", "10", "118.40"), pos("TSLA", "2", "250")]
    shot = [pos("AAPL", "5", "190"), pos("AMD", "3", "150"), pos("NVDA", "20", "119.20")]
    assert changes(held, shot) == [
        "+ AMD: 3 at 150.00 USD avg (new)",
        "+ NVDA: 10 → 20 shares",
        "- TSLA: gone (was 2)",
    ]
    assert changes(held, held) == []


def test_buying_and_selling() -> None:
    first = buy(None, "NVDA", Decimal("10"), usd("100"))
    more = buy(first, "NVDA", Decimal("10"), usd("110"))
    assert more == pos("NVDA", "20", "105")
    assert sell(more, "NVDA", Decimal("5")) == pos("NVDA", "15", "105")
    assert sell(more, "NVDA", Decimal("20")) is None
    with pytest.raises(InvalidInput, match="only hold 20"):
        sell(more, "NVDA", Decimal("21"))
    with pytest.raises(InvalidInput, match="don't hold any AMD"):
        sell(None, "AMD", Decimal("1"))
    with pytest.raises(InvalidInput, match="held in USD"):
        buy(more, "NVDA", Decimal("1"), Money(Decimal("150"), "SGD"))
