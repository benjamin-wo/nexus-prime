from decimal import Decimal

import pytest

from nexus.domain.email import amount_in_text, read_amount


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


ALERT = (
    "A transaction of SGD 12.40 was made with your Example Card ending 0000 on 03/09/26 at "
    "KOPI CORNER. If unauthorised, call our 24/7 hotline now\nEMAIL DISCLAIMER: any person "
    "receiving this email shall treat it as confidential."
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (ALERT, ("12.40", "SGD")),
        ("Charged S$1,234.50 at SHOP. Not you? Call 1800 000 0000.", ("1234.50", "SGD")),
        ("USD12.00 at APP STORE on 01 Oct", ("12.00", "USD")),
        ("Paid SGD 12.40. Amount: SGD 12.40", ("12.40", "SGD")),  # said twice, still one
    ],
)
def test_the_one_amount_an_email_states(text: str, expected: tuple[str, str]) -> None:
    money = amount_in_text(text)
    assert money is not None
    assert (money.amount, money.currency) == (Decimal(expected[0]), expected[1])


@pytest.mark.parametrize(
    "text",
    [
        "Subtotal SGD 10.00, GST SGD 0.90, Total SGD 10.90",  # several: not guessed
        "Your card ending 0000 was used on 03/09/26",  # no amount
        "Order 12345.67 shipped",  # a figure without a currency
        "Total incl. GST 0.90",  # capitals that aren't a currency
    ],
)
def test_no_single_stated_amount(text: str) -> None:
    assert amount_in_text(text) is None
