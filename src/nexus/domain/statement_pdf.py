"""Reading transactions from the text of a PDF statement. Pure: it works on the
lines of text, so it can be tested without a PDF.

A transaction line starts with one or two dates and ends with an amount:

    17 AUG 16 AUG  PAYMENT - THANK YOU          120.00CR   (card: post and trans date)
    03/09  GRAB*RIDE                                42.10   (card, one date)
    05 SEP 2026  FAST PAYMENT ANN     40.00     1,234.56   (account: amount, balance)

On a card statement a plain amount is money out and "CR" money in. On an account
statement each line also carries the balance, and whether it went up or down
says which way the money moved. Totals and balance lines are read, not imported,
and used to check that the rows add up to what the statement says.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from nexus.domain.ledger import Direction

_MONTHS = {
    m: n
    for n, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
# One date at the start of a line: "17 AUG", "17 AUG 2026", "17/08", "17/08/2026", "2026-08-17".
_DATE = (
    rf"(?:\d{{1,2}}\s?{_MON}(?:\s?(?:19|20)\d{{2}}(?!\d))?"
    r"|\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?"
    r"|\d{4}-\d{2}-\d{2})"
)
_LEADING = re.compile(rf"^\s*(?P<first>{_DATE})(?:\s+(?P<second>{_DATE}))?\s+(?P<rest>.+)$", re.I)
_AMOUNT = r"\(?-?[\d,]*\d\.\d{2}\)?(?:\s?(?:CR|DR))?-?"
_TRAILING = re.compile(rf"^(?P<text>.*?)\s+(?P<a>{_AMOUNT})(?:\s+(?P<b>{_AMOUNT}))?\s*$", re.I)
_FOREIGN = re.compile(r"^\s*([A-Z]{3})\s+([\d,]+\.\d{2})\s*$")
_FULL_DATE = rf"\b(?:\d{{1,2}}\s{_MON}\s\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})\b"
_OPENING = re.compile(
    r"^\s*(?:previous balance|balance b/?f|balance brought forward|opening balance)", re.I
)
_CLOSING = re.compile(
    r"^\s*(?:total balance|new balance|closing balance|balance c/?f|balance carried forward)",
    re.I,
)
_SKIP_DESCRIPTION = re.compile(
    r"^(?:previous balance|balance b/?f|balance c/?f|balance brought|balance carried|"
    r"opening balance|closing balance|sub ?total|total)\b",
    re.I,
)
_REFERENCE = re.compile(r"^\s*(?:ref(?:erence)?\.?\s*(?:no\.?)?\s*:)", re.I)
MAX_CONTINUATION = 2


class Kind(StrEnum):
    CARD = "card"  # one amount a line; CR is money in
    ACCOUNT = "account"  # amount and running balance


@dataclass(frozen=True, slots=True)
class PdfRow:
    day: date
    description: str
    amount: Decimal  # signed: negative is money out
    line: int


@dataclass(frozen=True, slots=True)
class PdfStatement:
    kind: Kind
    rows: list[PdfRow]
    statement_date: date | None
    opening: Decimal | None  # previous balance(s), as the statement states them
    closing: Decimal | None
    unread: list[int] = field(default_factory=list)  # lines that looked like transactions

    @property
    def reconciles(self) -> bool | None:
        """Whether the rows take the opening balance to the closing one; None when
        the statement doesn't state both."""
        if self.opening is None or self.closing is None:
            return None
        moved = sum((r.amount for r in self.rows), Decimal(0))
        if self.kind is Kind.CARD:  # a card balance is what's owed: spending adds to it
            return self.opening - moved == self.closing
        return self.opening + moved == self.closing


def _money(text: str) -> Decimal | None:
    """An amount token as a number, with its sign: CR, a trailing or leading minus
    and brackets are negative here; the caller decides what that means."""
    raw = text.strip().upper()
    negative = False
    if raw.endswith("CR"):
        negative, raw = True, raw[:-2].strip()
    elif raw.endswith("DR"):
        raw = raw[:-2].strip()
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1]
    if raw.endswith("-"):
        negative, raw = True, raw[:-1]
    if raw.startswith("-"):
        negative, raw = True, raw[1:]
    try:
        value = Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None
    return -value if negative else value


def _parse_date(text: str, statement: date | None) -> date | None:
    t = text.strip().lower()
    try:
        if m := re.fullmatch(rf"(\d{{1,2}})\s?({_MON})(?:\s?(\d{{4}}))?", t):
            day, month = int(m.group(1)), _MONTHS[m.group(2)[:3]]
            year = int(m.group(3)) if m.group(3) else _year_for(month, statement)
            return date(year, month, day) if year else None
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", t):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2,4}))?", t):
            day, month = int(m.group(1)), int(m.group(2))
            if m.group(3):
                year = int(m.group(3))
                year = year + 2000 if year < 100 else year
            else:
                year = _year_for(month, statement) or 0
            return date(year, month, day) if year else None
    except ValueError:
        return None
    return None


def _year_for(month: int, statement: date | None) -> int | None:
    """A date printed without its year falls in the twelve months up to the statement:
    a December charge on a January statement is last year's."""
    if statement is None:
        return None
    return statement.year - 1 if month > statement.month else statement.year


def statement_date(lines: list[str]) -> date | None:
    """The date on the line that names it ("Statement Date ... 13 SEP 2026"), else the
    first full date anywhere."""
    labelled = [line for line in lines if re.search(r"statement\s+date", line, re.I)]
    for line in [*labelled, *lines]:
        for m in re.finditer(_FULL_DATE, line, re.I):
            found = _parse_date(m.group(0), None)
            if found:
                return found
    return None


def _balance_on(line: str) -> Decimal | None:
    amounts = re.findall(_AMOUNT, line, re.I)
    return _money(amounts[-1]) if amounts else None


@dataclass
class _Candidate:
    line: int
    day: date
    text: str
    a: Decimal
    b: Decimal | None


def read_statement_lines(lines: list[str]) -> PdfStatement:
    when = statement_date(lines)
    candidates: list[_Candidate] = []
    unread: list[int] = []
    openings: list[Decimal] = []
    closings: list[Decimal] = []
    last: _Candidate | None = None
    continued = 0
    for n, line in enumerate(lines):
        if _OPENING.match(line):
            if (value := _balance_on(line)) is not None:
                openings.append(value)
            last = None
            continue
        if _CLOSING.match(line):
            if (value := _balance_on(line)) is not None:
                closings.append(value)
            last = None
            continue
        lead = _LEADING.match(line)
        tail = _TRAILING.match(lead.group("rest")) if lead else None
        if lead and tail:
            day = _parse_date(lead.group("second") or lead.group("first"), when)
            a, b = _money(tail.group("a")), _money(tail.group("b")) if tail.group("b") else None
            text = " ".join(tail.group("text").split())
            if _SKIP_DESCRIPTION.match(text):
                if a is not None:
                    (openings if not candidates else closings).append(b if b is not None else a)
                last = None
                continue
            if day is None or a is None:
                unread.append(n)
                last = None
                continue
            last = _Candidate(n, day, text, a, b)
            candidates.append(last)
            continued = 0
            continue
        if lead and not tail and last is None:
            unread.append(n)  # a dated line with no amount: can't be read
            continue
        if _REFERENCE.match(line):
            continue  # a bank reference under the row: skipped, the row stays open
        if last is not None and (m := _FOREIGN.match(line)):
            last.text = f"{last.text} ({m.group(1)} {m.group(2)})"
            continue
        if last is not None and continued < MAX_CONTINUATION and _continues(line):
            last.text = f"{last.text} {' '.join(line.split())}"
            continued += 1
            continue
        last = None
    kind = (
        Kind.ACCOUNT
        if candidates and sum(c.b is not None for c in candidates) * 2 > len(candidates)
        else Kind.CARD
    )
    opening = sum(openings, Decimal(0)) if openings else None
    closing = sum(closings, Decimal(0)) if closings else None
    rows = _signed(candidates, kind, openings[0] if openings else None)
    return PdfStatement(kind, rows, when, opening, closing, unread)


def _continues(line: str) -> bool:
    """A short line of text under a transaction: the rest of its description."""
    text = line.strip()
    if not text or len(text) > 60 or re.search(_AMOUNT, text):
        return False
    lowered = text.lower()
    return not lowered.startswith(("ref no", "page ", "post ", "date ", "transaction", "please"))


def _signed(candidates: list[_Candidate], kind: Kind, opening: Decimal | None) -> list[PdfRow]:
    rows: list[PdfRow] = []
    balance = opening
    for c in candidates:
        amount = abs(c.a)
        if kind is Kind.CARD:
            # Spending is a plain amount; a credit (payment, refund) is marked.
            signed = amount if c.a < 0 else -amount
        elif c.b is not None and balance is not None:
            signed = amount if c.b > balance else -amount
            balance = c.b
        else:
            signed = -amount if c.a >= 0 else amount
            if c.b is not None:
                balance = c.b
        rows.append(PdfRow(c.day, c.text, signed, c.line))
    return rows


def as_direction(amount: Decimal) -> Direction:
    return Direction.OUT if amount < 0 else Direction.IN
