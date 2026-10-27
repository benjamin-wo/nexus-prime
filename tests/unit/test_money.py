from decimal import Decimal

import pytest

from nexus.domain.errors import InvalidInput
from nexus.domain.money import Money


def test_parses_strings_exactly() -> None:
    assert Money.of("5.50", "sgd") == Money(Decimal("5.5"), "SGD")
    assert Money.of("0.1", "SGD") + Money.of("0.2", "SGD") == Money.of("0.3", "SGD")


def test_rejects_floats() -> None:
    with pytest.raises(InvalidInput, match="float"):
        Money.of(0.1, "SGD")  # type: ignore[arg-type]


@pytest.mark.parametrize("amount", ["1.00001", "NaN", "Infinity", "1e15", "abc"])
def test_rejects_bad_amounts(amount: str) -> None:
    with pytest.raises(InvalidInput):
        Money.of(amount, "SGD")


@pytest.mark.parametrize("currency", ["", "SG", "SGDX", "S1D"])
def test_rejects_bad_currency(currency: str) -> None:
    with pytest.raises(InvalidInput, match="currency"):
        Money.of("1", currency)


def test_never_mixes_currencies() -> None:
    with pytest.raises(InvalidInput, match="cannot combine"):
        Money.of("1", "SGD") + Money.of("1", "USD")
    with pytest.raises(InvalidInput):
        _ = Money.of("1", "SGD") < Money.of("1", "USD")


def test_allocate_sums_back_and_front_loads_remainder() -> None:
    parts = Money.of("100", "SGD").allocate(3)
    assert [p.amount for p in parts] == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    total = Money.zero("SGD")
    for part in parts:
        total = total + part
    assert total == Money.of("100", "SGD")


def test_allocate_uses_currency_minor_units() -> None:
    assert [p.amount for p in Money.of("1000", "JPY").allocate(3)] == [334, 333, 333]
    with pytest.raises(InvalidInput, match="minor units"):
        Money.of("10.5", "JPY").allocate(2)


def test_allocate_rejects_bad_input() -> None:
    with pytest.raises(InvalidInput):
        Money.of("10", "SGD").allocate(0)
    with pytest.raises(InvalidInput):
        Money.of("-10", "SGD").allocate(2)


def test_str_uses_minor_units() -> None:
    assert str(Money.of("5.5", "SGD")) == "5.50 SGD"
    assert str(Money.of("500", "JPY")) == "500 JPY"


def test_str_separates_thousands() -> None:
    assert str(Money.of("1240", "SGD")) == "1,240.00 SGD"
    assert str(Money.of("-1240.5", "SGD")) == "-1,240.50 SGD"
    assert str(Money.of("0", "SGD")) == "0.00 SGD"
    assert str(Money.of("125000", "JPY")) == "125,000 JPY"
    assert str(Money.of("-125000", "JPY")) == "-125,000 JPY"
    assert str(Money.of("1234567.891", "KWD")) == "1,234,567.891 KWD"


def test_parse_money_accepts_what_the_app_now_writes() -> None:
    from types import SimpleNamespace
    from typing import Any, cast

    from nexus.agent.tools import parse_money

    ctx = cast(Any, SimpleNamespace(user=SimpleNamespace(home_currency="SGD")))
    assert parse_money(ctx, "1,240.50", None) == Money.of("1240.50", "SGD")
    assert parse_money(ctx, "1,240,000", "JPY") == Money.of("1240000", "JPY")
    assert parse_money(ctx, "-1,240.50", "USD") == Money.of("-1240.50", "USD")
    assert parse_money(ctx, "1240.50", None) == Money.of("1240.50", "SGD")
