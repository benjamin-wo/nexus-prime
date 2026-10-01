"""Reading a bank statement exported as CSV: finding its header row, deciding
which column is which, and turning each row into a date, a description and a
signed amount. Pure: nothing here touches the ledger.

Banks disagree on almost everything: a few lines of account details above the
header, comma, semicolon or tab separators, one signed amount column or
separate withdrawal and deposit columns, day-first or month-first dates,
"1,234.50", "(12.30)" or "12.30 DR". A row that can't be read is reported with
the reason, never guessed.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, UserId

MAX_BYTES = 2_000_000
MAX_ROWS = 5000
_HEADER_SCAN = 20  # rows looked at for the header


class DateOrder(StrEnum):
    DMY = "dmy"  # 28/09/2026, as Singapore banks write it
    MDY = "mdy"  # 09/28/2026
    YMD = "ymd"  # 2026-09-28


class AmountSign(StrEnum):
    NEGATIVE_IS_OUT = "negative_is_out"  # -12.30 is money spent
    POSITIVE_IS_OUT = "positive_is_out"  # some cards list spending as positive


@dataclass(frozen=True, slots=True)
class Mapping:
    """Which column holds what, by index into the header row."""

    date: int
    description: tuple[int, ...]  # joined with " · " when several
    amount: int | None = None  # one signed column...
    debit: int | None = None  # ...or money out and money in in their own columns
    credit: int | None = None
    currency: int | None = None
    date_order: DateOrder = DateOrder.DMY
    sign: AmountSign = AmountSign.NEGATIVE_IS_OUT

    def check(self, width: int) -> None:
        used = [self.date, *self.description, self.amount, self.debit, self.credit, self.currency]
        if any(i is not None and not 0 <= i < width for i in used):
            raise InvalidInput("a mapped column is outside the table")
        if not self.description:
            raise InvalidInput("choose the column with the description")
        if self.amount is None and self.debit is None and self.credit is None:
            raise InvalidInput("choose the amount column, or the money out and in columns")
        if self.amount is not None and (self.debit is not None or self.credit is not None):
            raise InvalidInput("choose one amount column or separate out and in columns, not both")


@dataclass(frozen=True, slots=True)
class Table:
    headers: list[str]
    rows: list[list[str]]  # the rows below the header, each as wide as the header

    @property
    def header_key(self) -> str:
        """The same bank's exports share it, so a saved mapping can be found again."""
        joined = "|".join(" ".join(h.lower().split()) for h in self.headers)
        return hashlib.sha256(joined.encode()).hexdigest()[:32]


class RowStatus(StrEnum):
    READY = "ready"
    UNCLEAR = "unclear"  # the date or amount couldn't be read


@dataclass(frozen=True, slots=True)
class StatementRow:
    index: int  # position among the table's rows
    status: RowStatus
    day: date | None = None
    description: str = ""
    amount: Decimal | None = None  # positive
    direction: Direction | None = None
    currency: str | None = None  # when the statement names one
    problem: str | None = None
    raw: list[str] = field(default_factory=list)

    def fingerprint(self, occurrence: int) -> str:
        """Stable for the same row in a re-exported file; ``occurrence`` tells apart
        identical rows in one statement (two 1.80 kopis on the same day)."""
        text = "|".join(
            [
                self.day.isoformat() if self.day else "",
                str(self.amount),
                self.direction.value if self.direction else "",
                " ".join(self.description.lower().split()),
                str(occurrence),
            ]
        )
        return "csv:" + hashlib.sha256(text.encode()).hexdigest()[:40]


# --- reading the file ------------------------------------------------------------------

_DATE_WORDS = ("date",)
_AMOUNT_WORDS = ("amount", "debit", "credit", "withdrawal", "deposit", "value", "sgd")


def read_table(text: str) -> Table:
    if len(text.encode()) > MAX_BYTES:
        raise InvalidInput("the file is larger than 2 MB")
    text = text.lstrip("﻿")
    if not text.strip():
        raise InvalidInput("the file is empty")
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    rows = [
        [cell.strip() for cell in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)
    ]
    rows = [r for r in rows if any(r)]
    start = _header_row(rows)
    headers = rows[start]
    width = len(headers)
    body = [(r + [""] * width)[:width] for r in rows[start + 1 :]]
    if len(body) > MAX_ROWS:
        raise InvalidInput(f"the file has more than {MAX_ROWS} rows")
    if not body:
        raise InvalidInput("no rows under the header")
    return Table(headers, body)


def _header_row(rows: list[list[str]]) -> int:
    """The first row naming a date column and an amount-like column."""
    for i, row in enumerate(rows[:_HEADER_SCAN]):
        cells = [c.lower() for c in row]
        if any(w in c for c in cells for w in _DATE_WORDS) and any(
            w in c for c in cells for w in _AMOUNT_WORDS
        ):
            return i
    # No recognisable header: the widest early row is the best guess.
    early = rows[:_HEADER_SCAN]
    if not early:
        raise InvalidInput("the file has no rows")
    widest = max(len([c for c in r if c]) for r in early)
    return next(i for i, r in enumerate(early) if len([c for c in r if c]) == widest)


# --- suggesting a mapping ---------------------------------------------------------------


def _find(headers: list[str], *words: str, avoid: tuple[str, ...] = ()) -> int | None:
    for word in words:
        for i, h in enumerate(headers):
            low = h.lower()
            if word in low and not any(a in low for a in avoid):
                return i
    return None


_STRONG = ("description", "details", "narrative", "merchant", "payee", "particulars", "memo")
_WEAK = ("reference", "ref")


def _descriptions(table: Table, taken: set[int | None]) -> list[int]:
    """Up to two description columns: those named like one, else reference-like ones,
    else any other; the ones with the most text first, then in table order."""
    h = [name.lower() for name in table.headers]
    free = [i for i in range(len(h)) if i not in taken and "balance" not in h[i]]
    for words in (_STRONG, _WEAK, ("",)):
        found = [i for i in free if any(w in h[i] for w in words)]
        if found:
            break
    sample = table.rows[:50]

    def text(i: int) -> float:
        return sum(len(r[i]) for r in sample) / max(len(sample), 1)

    return sorted(sorted(found, key=text, reverse=True)[:2])


def suggest_mapping(table: Table) -> Mapping | None:
    """A best guess from the header names and the dates in the rows; None if the
    date or description can't be found."""
    h = table.headers
    day = _find(h, "transaction date", "trans date", "posting date", "date", avoid=("value",))
    if day is None:
        day = _find(h, "date")
    debit = _find(h, "withdrawal", "debit", "money out", "paid out", "spent")
    credit = _find(h, "deposit", "credit", "money in", "paid in", "received")
    amount = None
    if debit is None or credit is None:
        debit = credit = None
        amount = _find(h, "amount", "value", avoid=("balance",))
    described = _descriptions(table, taken={day, debit, credit, amount})
    currency = _find(h, "currency", "ccy")
    if day is None or not described or (amount is None and debit is None):
        return None
    return Mapping(
        date=day,
        description=tuple(described[:2]),
        amount=amount,
        debit=debit,
        credit=credit,
        currency=currency,
        date_order=guess_date_order([r[day] for r in table.rows]),
    )


# --- dates ------------------------------------------------------------------------------

_MONTHS = {
    m: n
    for n, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}  # fmt: skip
_NUMERIC = re.compile(r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})")
_WORDY = re.compile(r"^(\d{1,2})[\s\-/]*([A-Za-z]{3,9})[\s\-/,]*(\d{2,4})")
_WORDY_US = re.compile(r"^([A-Za-z]{3,9})[\s\-/]*(\d{1,2}),?[\s\-/]*(\d{2,4})")


def guess_date_order(values: list[str]) -> DateOrder:
    """From the numbers: a first part over 12 means day first, a second over 12
    month first, a four-digit first part year first. Otherwise day first."""
    for value in values:
        m = _NUMERIC.match(value.strip())
        if not m:
            continue
        a, b, _ = (int(x) for x in m.groups())
        if len(m.group(1)) == 4:
            return DateOrder.YMD
        if a > 12:
            return DateOrder.DMY
        if b > 12:
            return DateOrder.MDY
    return DateOrder.DMY


def _year(value: int) -> int:
    return value + 2000 if value < 100 else value


def parse_date(value: str, order: DateOrder) -> date | None:
    text = value.strip()
    try:
        if m := _NUMERIC.match(text):
            a, b, c = (int(x) for x in m.groups())
            if len(m.group(1)) == 4:
                return date(a, b, c)
            if order is DateOrder.MDY:
                return date(_year(c), a, b)
            if order is DateOrder.YMD:
                return date(_year(a), b, c)
            return date(_year(c), b, a)
        if m := _WORDY.match(text):
            month = _MONTHS.get(m.group(2).lower())
            return date(_year(int(m.group(3))), month, int(m.group(1))) if month else None
        if m := _WORDY_US.match(text):
            month = _MONTHS.get(m.group(1).lower())
            return date(_year(int(m.group(3))), month, int(m.group(2))) if month else None
    except ValueError:
        return None
    return None


# --- amounts ------------------------------------------------------------------------------

_CURRENCY = re.compile(r"\b[A-Z]{3}\b|[$€£¥]|S\$|US\$|RM")


def parse_amount(value: str) -> Decimal | None:
    """A signed amount: "-12.30", "(12.30)" and "12.30 DR" are negative, "12.30 CR"
    positive. Empty or unreadable is None."""
    text = value.strip()
    if not text or text in {"-", "—"}:
        return None
    negative = False
    upper = text.upper()
    if upper.endswith("DR"):
        negative, text = True, text[:-2]
    elif upper.endswith("CR"):
        text = text[:-2]
    text = _CURRENCY.sub("", text).replace(",", "").replace(" ", "").strip()
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.startswith("-"):
        negative, text = not negative, text[1:]
    elif text.endswith("-"):
        negative, text = not negative, text[:-1]
    text = text.lstrip("+")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    return -amount if negative else amount


# --- rows --------------------------------------------------------------------------------


def read_rows(table: Table, mapping: Mapping) -> list[StatementRow]:
    mapping.check(len(table.headers))
    return [_row(i, raw, mapping) for i, raw in enumerate(table.rows)]


def _row(index: int, raw: list[str], m: Mapping) -> StatementRow:
    description = " · ".join(raw[i] for i in m.description if raw[i])[:200]
    day = parse_date(raw[m.date], m.date_order)
    currency = raw[m.currency].strip().upper() if m.currency is not None else None
    if currency is not None and not re.fullmatch(r"[A-Z]{3}", currency):
        currency = None
    signed: Decimal | None
    if m.amount is not None:
        signed = parse_amount(raw[m.amount])
        marker = raw[m.amount].strip().upper()[-2:]
        if signed is not None and marker in {"CR", "DR"}:
            signed = abs(signed) if marker == "CR" else -abs(signed)  # the bank said which
        elif signed is not None and m.sign is AmountSign.POSITIVE_IS_OUT:
            signed = -signed
    else:
        out = parse_amount(raw[m.debit]) if m.debit is not None else None
        into = parse_amount(raw[m.credit]) if m.credit is not None else None
        if out and into:
            signed = None  # both filled: can't tell which
        elif out:
            signed = -abs(out)
        elif into:
            signed = abs(into)
        else:
            signed = None
    if day is None:
        return StatementRow(
            index, RowStatus.UNCLEAR, None, description, None, None, currency,
            "can't read the date", raw,
        )  # fmt: skip
    if signed is None or signed == 0:
        return StatementRow(
            index, RowStatus.UNCLEAR, day, description, None, None, currency,
            "can't read the amount", raw,
        )  # fmt: skip
    direction = Direction.OUT if signed < 0 else Direction.IN
    return StatementRow(
        index, RowStatus.READY, day, description, abs(signed), direction, currency, None, raw
    )


def fingerprints(rows: list[StatementRow]) -> dict[int, str]:
    """Each readable row's fingerprint, numbering repeats within the file."""
    seen: dict[str, int] = {}
    result: dict[int, str] = {}
    for row in rows:
        if row.status is not RowStatus.READY:
            continue
        base = row.fingerprint(0)
        seen[base] = seen.get(base, 0) + 1
        result[row.index] = row.fingerprint(seen[base] - 1)
    return result


# --- saved layouts and confirmed imports ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class SavedMapping:
    id: UUID
    user_id: UserId
    name: str  # the user's name for it, usually the bank's
    header_key: str
    mapping: Mapping
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StatementImport:
    id: UUID
    user_id: UserId
    file_name: str
    transaction_ids: list[UUID]
    created_at: datetime
    undone_at: datetime | None = None


def mapping_to_json(m: Mapping) -> dict[str, Any]:
    return {
        "date": m.date,
        "description": list(m.description),
        "amount": m.amount,
        "debit": m.debit,
        "credit": m.credit,
        "currency": m.currency,
        "date_order": m.date_order.value,
        "sign": m.sign.value,
    }


def mapping_from_json(data: dict[str, Any]) -> Mapping:
    try:
        return Mapping(
            date=int(data["date"]),
            description=tuple(int(i) for i in data["description"]),
            amount=_optional_int(data.get("amount")),
            debit=_optional_int(data.get("debit")),
            credit=_optional_int(data.get("credit")),
            currency=_optional_int(data.get("currency")),
            date_order=DateOrder(data.get("date_order", DateOrder.DMY)),
            sign=AmountSign(data.get("sign", AmountSign.NEGATIVE_IS_OUT)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidInput("that column layout isn't valid") from exc


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)
