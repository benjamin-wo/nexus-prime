from decimal import Decimal

import pytest

from nexus.domain.email import read_amount


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("12.40", "SGD", ("12.40", "SGD")),
        ("12.40", None, ("12.40", "SGD")),  # the home currency
        ("SGD 5.20", None, ("5.20", "SGD")),
        ("SGD5.20", "SGD", ("5.20", "SGD")),
        ("S$5.20", None, ("5.20", "SGD")),
        ("5.20", "S$", ("5.20", "SGD")),
        ("$5.20", None, ("5.20", "SGD")),
        ("US$18.00", None, ("18.00", "USD")),
        ("USD 18", "SGD", ("18", "USD")),  # the code written with the figure wins
        ("1,234.50", "sgd", ("1234.50", "SGD")),
        ("RM 42.00", None, ("42.00", "MYR")),
        ("€9,99", None, None),  # two figures: not clear enough
    ],
)
def test_amounts_as_emails_write_them(
    amount: str, currency: str | None, expected: tuple[str, str] | None
) -> None:
    money = read_amount(amount, currency, "SGD")
    if expected is None:
        assert money is None
    else:
        assert money is not None
        assert (money.amount, money.currency) == (Decimal(expected[0]), expected[1])


@pytest.mark.parametrize("amount", [None, "", "free", "0.00", "-5.00 SGD", "5 or 6"])
def test_no_clear_positive_amount(amount: str | None) -> None:
    assert read_amount(amount, None, "SGD") is None
