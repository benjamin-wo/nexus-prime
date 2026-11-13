"""The calculator behind the chat's ``calculate`` tool: exact decimal arithmetic on a typed
expression, and nothing else (never ``eval``)."""

from decimal import Decimal

import pytest

from nexus.agent.outlook_text import describe_calculation
from nexus.domain.calc import MAX_LENGTH, calculate, clean
from nexus.domain.errors import InvalidInput


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,234.50 + 987.25 - 42", "2179.75"),
        ("2308.42 + 4798", "7106.42"),
        ("0.1 + 0.2", "0.3"),  # exact, where a float says 0.30000000000000004
        ("10 - 2 - 3", "5"),  # left to right
        ("2 + 3 * 4", "14"),
        ("(2 + 3) * 4", "20"),
        ("-5 + 8", "3"),
        ("--5", "5"),
        ("-(2 + 3) * 4", "-20"),
        ("+2,308.42", "2308.42"),
        ("100 / 8", "12.5"),
        ("0.18 * 2350", "423.00"),
        ("1,000,000 * 3", "3000000"),
        (".5 + .25", "0.75"),
        ("SGD 1,234.50 + SGD 987.25", "2221.75"),
        ("500 SGD - 12", "488"),
        ("$12.50 * 4", "50.00"),
        ("1234.50 \u2212 42", "1192.50"),  # a typed minus sign
        ("3 \u00d7 4 \u00f7 6", "2"),
    ],
)
def test_plain_arithmetic_is_exact(text: str, value: str) -> None:
    result = calculate(text)
    assert result.value == Decimal(value)
    assert result.exact


def test_a_division_that_does_not_end_is_rounded_to_cents_and_says_so() -> None:
    result = calculate("186.40 / 3")
    assert result.rounded == Decimal("62.13") and not result.exact
    assert str(result.value).startswith("62.1333333333")
    text = describe_calculation(result)
    assert "= 62.13" in text and "doesn't divide out evenly" in text and "62.1333333333" in text


def test_rounding_is_half_up_and_never_negative_zero() -> None:
    assert calculate("111.105").rounded == Decimal("111.11")
    assert calculate("-111.105").rounded == Decimal("-111.11")
    zero = calculate("0 - 0.004").rounded
    assert zero == 0 and str(zero) == "0.00"


def test_the_words_give_the_rounded_figure_and_the_exact_one_when_different() -> None:
    assert describe_calculation(calculate("1,234.50 + 987.25 - 42")).endswith("= 2,179.75")
    text = describe_calculation(calculate("1 / 8"))
    assert "= 0.13" in text and "(exactly 0.125)" in text
    assert describe_calculation(calculate("-1672.78 + 4798")).endswith("= 3,125.22")


def test_commas_symbols_and_currency_codes_are_stripped() -> None:
    assert clean("SGD 1,234.50 + usd 5") == "1234.50 + 5"
    assert clean("S$ 12") == "S 12"  # a stray letter is left to be refused, not guessed at


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",  # a name
        "x + 1",
        "__import__('os').system('ls')",  # a call
        "(1).real",  # an attribute
        "open('/etc/passwd')",
        "2 ** 3",  # power
        "2 ^ 3",
        "9 ** 9 ** 9",
        "10 % 3",
        "18% of 2350",
        "5 5",  # two numbers in a row
        "5 +",
        "* 5",
        "(1 + 2",
        "1 + 2)",
        "1_000 + 1",
        "0x10 + 1",
        "1e5 + 1",  # no exponents: 'e' is a letter
        "1.2.3",
        "'a' + 'b'",
        "[1, 2]",
        "1 if 1 else 2",
        "lambda: 1",
        "1; 2",
        "1\n+ 2; import os",
    ],
)
def test_anything_but_plain_arithmetic_is_refused(text: str) -> None:
    with pytest.raises(InvalidInput):
        calculate(text)


def test_huge_inputs_are_refused() -> None:
    with pytest.raises(InvalidInput, match="too long"):
        calculate("1 + " * MAX_LENGTH + "1")
    with pytest.raises(InvalidInput, match="digits"):
        calculate("1" * 31)
    with pytest.raises(InvalidInput, match="nested"):
        calculate("(" * 40 + "1" + ")" * 40)
    with pytest.raises(InvalidInput, match="nested"):
        calculate("-" * 40 + "1")
    with pytest.raises(InvalidInput, match="too large"):
        calculate("999999999999999999999999999999 * 999999999999999999999999999999")
    with pytest.raises(InvalidInput, match="too large"):
        calculate("1" * 25 + " + 1")


def test_a_deeply_chained_sum_is_fine() -> None:
    assert calculate(" + ".join(["1"] * 45)).value == 45


def test_dividing_by_zero_is_a_plain_refusal() -> None:
    for text in ("1 / 0", "5 / (2 - 2)", "0 / 0"):
        with pytest.raises(InvalidInput, match="divide by zero"):
            calculate(text)
