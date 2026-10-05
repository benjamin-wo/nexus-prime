"""Holdings rules: tickers, merging a screenshot's rows, what saving would change,
and buying and selling at an average cost. Every figure here is made up."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.investments import (
    Dividend,
    Position,
    Trade,
    TradeSide,
    buy,
    changes,
    clean_quantity,
    clean_symbol,
    expected,
    held_on,
    merge_positions,
    realised,
    sell,
)
from nexus.domain.ledger import UserId
from nexus.domain.money import Money

USER = UserId(uuid4())
MADE = datetime(2026, 9, 28, tzinfo=UTC)


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


def test_a_sale_locks_in_its_gain_against_the_average_cost() -> None:
    held = Position("NVDA", Decimal(10), Money.of("100", "USD"))
    assert realised(held, Decimal(4), Money.of("150", "USD")) == Money.of("200", "USD")
    assert realised(held, Decimal(2), Money.of("90.5", "USD")) == Money.of("-19", "USD")
    with pytest.raises(InvalidInput, match="held in USD"):
        realised(held, Decimal(1), Money.of("150", "SGD"))


def test_shares_held_on_a_day_are_worked_back_from_the_trades() -> None:
    def t(side: TradeSide, qty: str, day: date) -> Trade:
        return Trade(uuid4(), USER, "NVDA", side, Decimal(qty), None, day, None, MADE)

    trades = [t(TradeSide.BUY, "10", date(2026, 9, 1)), t(TradeSide.SELL, "4", date(2026, 9, 20))]
    assert held_on(Decimal(6), trades, date(2026, 9, 15)) == Decimal(10)
    assert held_on(Decimal(6), trades, date(2026, 9, 25)) == Decimal(6)
    assert held_on(Decimal(6), trades, date(2026, 8, 1)) == Decimal(0)


def test_dividends_net_of_us_withholding_and_the_year_ahead() -> None:
    d = Dividend(uuid4(), USER, "NVDA", date(2026, 9, 15), Money.of("0.04", "USD"),
                 Decimal(10), MADE)  # fmt: skip
    assert (d.gross, d.withheld, d.net) == (
        Money.of("0.40", "USD"), Money.of("0.12", "USD"), Money.of("0.28", "USD"),
    )  # fmt: skip
    sg = Dividend(uuid4(), USER, "D05", date(2026, 9, 15), Money.of("0.6", "SGD"),
                  Decimal(100), MADE)  # fmt: skip
    assert sg.withheld.is_zero and sg.net == Money.of("60", "SGD")
    held = Position("KO", Decimal(100), Money.of("50", "USD"))
    e = expected(
        held, [Decimal("0.5"), Decimal("0.5"), Decimal("0.51"), Decimal("0.51")], Decimal(68)
    )
    assert e is not None
    assert (e.per_share, e.payments, e.net) == (
        Money.of("2.02", "USD"), 4, Money.of("141.4", "USD"),
    )  # fmt: skip
    assert (e.yield_on_value, e.yield_on_cost) == (Decimal("2.97"), Decimal("4.04"))
    assert expected(held, [], Decimal(68)) is None
