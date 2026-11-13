"""Exact arithmetic on a typed expression, for the chat's ``calculate`` tool.

Numbers, ``+ - * /``, a leading minus or plus, and parentheses; nothing else. It is a small
hand-written parser over ``Decimal``, never ``eval``, so there is nothing to call, no names
to look up and no power operator to blow up. Thousands commas, currency symbols and ISO
currency codes are stripped first ("SGD 1,234.50 + 987.25" works). Pure: no I/O.
"""

import re
from dataclasses import dataclass
from decimal import (
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
)

from nexus.domain.errors import InvalidInput

MAX_LENGTH = 200  # characters of the expression as given
MAX_DIGITS = 30  # digits in one number
MAX_DEPTH = 20  # nested parentheses
MAX_RESULT = Decimal(10) ** 18  # beyond this the answer is no use for money
PRECISION = 40

# Codes stripped when they sit beside a number; any other word is refused, not ignored.
_CODES = frozenset(
    "SGD USD EUR GBP JPY MYR AUD NZD CAD CHF CNY HKD TWD KRW THB IDR PHP VND INR AED".split()
)
_WORD = re.compile(r"(?<![A-Za-z])[A-Za-z]{3}(?![A-Za-z])")
# U+2212 minus, U+2013 en dash, U+00D7 times, U+00F7 divided by, then currency signs.
_SYMBOLS = str.maketrans(
    {
        "\u2212": "-",
        "\u2013": "-",
        "\u00d7": "*",
        "\u00f7": "/",
        **dict.fromkeys("$\u20ac\u00a3\u00a5\u20b9\u0e3f\u20a9", " "),
    }
)
_TOKEN = re.compile(r"\s*(?:(?P<number>\d+(?:\.\d+)?|\.\d+)|(?P<op>[-+*/()]))")


@dataclass(frozen=True, slots=True)
class Calculation:
    expression: str  # as evaluated: commas, symbols and currency codes removed
    value: Decimal  # exact, unless ``exact`` is False
    exact: bool  # False when the division did not end (62.1333...)

    @property
    def rounded(self) -> Decimal:
        """To 2 decimal places, half up (a money figure)."""
        out = self.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return out + 0 if out == 0 else out  # no "-0.00"


def clean(text: str) -> str:
    """The expression with thousands commas, currency symbols and ISO codes taken out."""
    cleaned = text.translate(_SYMBOLS).replace(",", "")
    cleaned = _WORD.sub(lambda m: " " if m.group().upper() in _CODES else m.group(), cleaned)
    return " ".join(cleaned.split())


def calculate(text: str) -> Calculation:
    """Evaluate ``text`` exactly. Raises ``InvalidInput`` with a plain reason for anything
    that isn't plain arithmetic, is too big, or divides by zero."""
    if len(text) > MAX_LENGTH:
        raise InvalidInput(f"the expression is too long (at most {MAX_LENGTH} characters)")
    expression = clean(text)
    if not expression:
        raise InvalidInput("give an expression such as 1,234.50 + 987.25 - 42")
    tokens = _tokenize(expression)
    context = Context(prec=PRECISION, traps=[InvalidOperation, DivisionByZero, Overflow])
    parser = _Parser(tokens, context)
    try:
        value = parser.parse()
    except DivisionByZero as exc:
        raise InvalidInput("cannot divide by zero") from exc
    except (InvalidOperation, Overflow) as exc:
        raise InvalidInput("that number is too large to work with") from exc
    if abs(value) >= MAX_RESULT:
        raise InvalidInput("the result is too large to be an amount of money")
    return Calculation(expression, value, not context.flags[Inexact])


def _tokenize(expression: str) -> list[str]:
    tokens: list[str] = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if match is None:
            bad = expression[position:].strip()[:1]
            raise InvalidInput(
                f"can't use {bad!r}: only numbers, + - * / and brackets "
                "(for a percentage write it as a decimal: 18% of 2350 is 0.18 * 2350)"
            )
        token = match.group("number") or match.group("op")
        if match.group("number") and len(token.replace(".", "")) > MAX_DIGITS:
            raise InvalidInput(f"a number has more than {MAX_DIGITS} digits")
        tokens.append(token)
        position = match.end()
    return tokens


class _Parser:
    """expr = term (("+" | "-") term)*; term = unary (("*" | "/") unary)*;
    unary = ("-" | "+") unary | atom; atom = number | "(" expr ")"."""

    def __init__(self, tokens: list[str], context: Context) -> None:
        self.tokens = tokens
        self.context = context
        self.at = 0
        self.depth = 0

    def parse(self) -> Decimal:
        value = self._expr()
        if self.at != len(self.tokens):
            raise InvalidInput(f"unexpected {self.tokens[self.at]!r}")
        return value

    def _peek(self) -> str | None:
        return self.tokens[self.at] if self.at < len(self.tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            raise InvalidInput("the expression ends too soon")
        self.at += 1
        return token

    def _expr(self) -> Decimal:
        value = self._term()
        while self._peek() in ("+", "-"):
            op = self._take()
            right = self._term()
            value = (
                self.context.add(value, right) if op == "+" else self.context.subtract(value, right)
            )
        return value

    def _term(self) -> Decimal:
        value = self._unary()
        while self._peek() in ("*", "/"):
            op = self._take()
            right = self._unary()
            if op == "/" and right == 0:
                raise InvalidInput("cannot divide by zero")
            value = (
                self.context.multiply(value, right)
                if op == "*"
                else self.context.divide(value, right)
            )
        return value

    def _unary(self) -> Decimal:
        sign = self._peek()
        if sign in ("-", "+"):
            self._take()
            self._enter()
            try:
                inner = self._unary()
            finally:
                self.depth -= 1
            return self.context.minus(inner) if sign == "-" else inner
        return self._atom()

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise InvalidInput("the expression is nested too deeply")

    def _atom(self) -> Decimal:
        piece = self._take()
        if piece == "(":
            self._enter()
            try:
                value = self._expr()
            finally:
                self.depth -= 1
            if self._peek() != ")":
                raise InvalidInput("a bracket is not closed")
            self._take()
            return value
        if piece in ")+-*/":
            raise InvalidInput(f"unexpected {piece!r}")
        return Decimal(piece)
