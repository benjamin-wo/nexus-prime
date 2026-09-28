"""Deterministic intent checks that run before, and never depend on, the model."""

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nexus.domain.errors import InvalidInput
from nexus.domain.money import Money

_CURRENCIES = "SGD|USD|EUR|GBP|JPY|MYR|AUD|NZD|CAD|CHF|CNY|HKD|TWD|KRW|THB|IDR|PHP|VND|INR"
_SYMBOLS = {"S$": "SGD", "US$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "RM": "MYR"}
_MONEY = (
    r"(?:(?P<sym>S\$|US\$|\$|€|£|¥|RM)\s?)?"
    r"(?P<amt>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?P<k>k)?"
    rf"(?:\s?(?P<code>{_CURRENCIES})\b)?"
)
_NAME = r"(?P<name>[A-Za-z][A-Za-z .'-]{0,38}[A-Za-z]|[A-Za-z])"
_NOT_A_PERSON = {"i", "we", "you", "me", "it", "they", "he", "she", "someone"}
_TAIL = r"(?:\s+(?:for|as)\s+(?P<note>.{1,120}?))?\s*[.!]*"

_TERMINATION = re.compile(
    r"^\s*(?:stop|cancel|never ?mind|forget it|abort|quit|that'?s (?:enough|all))\s*[.!]*\s*$",
    re.I,
)
_SELF_DIAGNOSIS = re.compile(
    r"\b(?:are you (?:working|there|alive|ok|okay|up|down)"
    r"|is (?:this|it|the bot|nexus) (?:broken|working|down)"
    r"|what'?s wrong with you"
    r"|why (?:aren'?t|are not|didn'?t|did not|don'?t) you (?:work|respond|reply|answer))\b",
    re.I,
)
_POLITE = r"^\s*(?:please\s+|pls\s+|can you\s+|could you\s+|would you\s+|help me\s+)?"
_UNSUPPORTED: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("transfer", re.compile(_POLITE + rf"(?:transfer|wire|remit|send)\b.*{_MONEY}.*\bto\b", re.I)),
    (
        "payment",
        re.compile(
            _POLITE + r"(?:pay(?!\s?(?:day|check|cheque))|make (?:a )?payment|settle my)\b", re.I
        ),
    ),
    (
        "cancel_subscription",
        re.compile(r"\b(?:cancel|unsubscribe|terminate)\b.*\b(?:subscription|membership)\b", re.I),
    ),
)
_INCOME: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "repayment",
        re.compile(
            rf"^\s*{_NAME}\s+(?:has\s+)?(?:paid|sent|transferred|gave)\s+me\s+(?:back\s+)?"
            rf"{_MONEY}(?:\s+back)?{_TAIL}$",
            re.I,
        ),
    ),
    (
        "repayment",
        re.compile(
            rf"^\s*{_NAME}\s+(?:has\s+)?(?:repaid|returned|paid back)(?:\s+me)?\s+{_MONEY}{_TAIL}$",
            re.I,
        ),
    ),
    (
        "salary",
        re.compile(
            rf"^\s*(?:i\s+)?(?:got paid|salary|payday|pay ?check|paycheque)"
            rf"(?:\s+(?:of|is|was|came in|:))?\s*:?\s*{_MONEY}\s*[.!]*$",
            re.I,
        ),
    ),
    (
        "income",
        re.compile(
            rf"^\s*(?:i\s+)?(?:received|got|earned|was reimbursed|got reimbursed|got refunded)"
            rf"\s+{_MONEY}(?:\s+from\s+{_NAME})?{_TAIL}$",
            re.I,
        ),
    ),
    (
        "income",
        re.compile(
            rf"^\s*(?:income|refund|reimbursement|bonus)\s*(?:of|:)?\s*{_MONEY}"
            rf"(?:\s+from\s+{_NAME})?{_TAIL}$",
            re.I,
        ),
    ),
)


class IncomeKind(StrEnum):
    REPAYMENT = "repayment"
    SALARY = "salary"
    INCOME = "income"


@dataclass(frozen=True, slots=True)
class IncomeIntent:
    kind: IncomeKind
    amount: Money
    counterparty: str | None
    note: str | None


def is_termination(text: str) -> bool:
    return bool(_TERMINATION.match(text))


def is_self_diagnosis(text: str) -> bool:
    return bool(_SELF_DIAGNOSIS.search(text))


def unsupported_intent(text: str) -> str | None:
    """The kind of money movement requested, which the app never performs."""
    for intent, pattern in _UNSUPPORTED:
        if pattern.search(text):
            return intent
    return None


def _money(match: re.Match[str], home_currency: str) -> Money:
    amount = Decimal(match["amt"].replace(",", ""))
    if match["k"]:
        amount *= 1000
    symbol = match["sym"]
    code = match["code"].upper() if match["code"] else None
    symbol_code = _SYMBOLS.get(symbol) if symbol else None
    if code and symbol_code and code != symbol_code:
        raise InvalidInput("the currency symbol and code disagree")
    return Money.of(amount, code or symbol_code or home_currency)


def parse_income(text: str, home_currency: str) -> IncomeIntent | None:
    """Recognise a clear report of money received. Anything else returns None."""
    if len(text) > 200:
        return None
    for kind, pattern in _INCOME:
        match = pattern.match(text)
        if not match:
            continue
        groups = match.groupdict()
        name = (groups.get("name") or "").strip() or None
        if name and name.casefold() in _NOT_A_PERSON:
            return None
        try:
            amount = _money(match, home_currency)
        except InvalidInput:
            return None
        if not amount.is_positive:
            return None
        note = (groups.get("note") or "").strip() or None
        return IncomeIntent(IncomeKind(kind), amount, name, note)
    return None
