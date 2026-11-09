"""One payment recorded twice: a bank's card alert and the shop's own receipt, or an
entry the user typed and the email that followed. Pure rules, no I/O.

Nothing is ever merged on a guess: a match only lets Kaya ask. Two rides home at
the same price on the same day are real, so the rule is narrow: the same amount
and direction within a day, by what looks like the same merchant.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from nexus.domain.ledger import Direction, Source, Transaction
from nexus.domain.money import Money

# A card alert and a receipt can be dated a day apart (a late-night ride).
NEAR_DAYS = 1

# Two amounts in different currencies are one payment when, converted at their days' rates,
# they are this close: a card that does its own FX adds a markup.
FX_TOLERANCE = Decimal("0.03")

# An amount in the user's home currency on a local day, or None without a rate for it. The
# application supplies it (it looks the rates up); this module does no I/O.
type Valuer = Callable[[Money, date], Money | None]

# Card statements shorten merchant names: "GRB*" is Grab.
_ALIASES = {"GRB": "GRAB", "GRABPAY": "GRAB", "AMZN": "AMAZON", "SHP": "SHOPEE"}
# Words that say nothing about who was paid.
_GENERIC = frozenset(
    "PTE LTD LIMITED INC LLC SINGAPORE SG SGP THE AND CO COM WWW HTTPS PAYMENT PAYMENTS "
    "TRANSACTION PURCHASE CARD ONLINE SHOP STORE".split()
)
_WORD = re.compile(r"[A-Z0-9]+")


def _words(name: str | None) -> set[str]:
    found = set()
    for word in _WORD.findall((name or "").upper()):
        word = _ALIASES.get(word, word)
        if len(word) >= 3 and not any(c.isdigit() for c in word) and word not in _GENERIC:
            found.add(word)
    return found


def same_merchant(a: str | None, b: str | None) -> bool:
    """Whether two merchant names could be the same place: they share a word that
    names it ("Grab* A-7KXP…" and "Grab Singapore"), or one side has no name."""
    first, second = _words(a), _words(b)
    if not first or not second:
        return True
    return bool(first & second)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A payment as either side of a possible match: a ledger row or an email draft."""

    direction: Direction
    amount: Money
    occurred_at: datetime
    merchant: str | None
    # Where it came from, and the email's subject or the row's notes.
    source: Source
    kind: str | None


def candidate(tx: Transaction) -> Candidate:
    return Candidate(tx.direction, tx.amount, tx.occurred_at, tx.counterparty, tx.source, tx.notes)


def _same_kind(a: Candidate, b: Candidate) -> bool:
    """Two records of the same kind are two payments: two entries the user made
    (a second kopi), two statement lines, or two emails with the same subject (two
    card alerts). Only records from different places can be one payment twice."""
    if a.source is not b.source:
        return False
    if a.source is Source.EMAIL:
        return (a.kind or "").casefold() == (b.kind or "").casefold()
    return True


def _named_alike(a: str | None, b: str | None) -> bool:
    """Both have a name and share a word that names the place."""
    return bool(_words(a) & _words(b))


def _close_in_value(a: Money, b: Money, a_day: date, b_day: date, value: Valuer) -> bool:
    first, second = value(a, a_day), value(b, b_day)
    if first is None or second is None or first.currency != second.currency:
        return False
    biggest = max(first.amount, second.amount)
    return biggest > 0 and abs(first.amount - second.amount) <= biggest * FX_TOLERANCE


def likely_same(
    a: Candidate,
    b: Candidate,
    tz: ZoneInfo,
    *,
    any_source: bool = False,
    value: Valuer | None = None,
) -> bool:
    """Whether two records look like one payment. ``any_source``: for a bill marked
    paid, where an entry of any kind for the same amount is the bill already logged.

    Amounts in two currencies (a shop's receipt in euros, the card's alert in the home
    currency) match only through ``value``, and only when both sides name the merchant and
    share a word: stricter than for one currency, where a record with no name may match.
    Without ``value``, or without a rate, they never match."""
    if a.direction is not b.direction:
        return False
    a_day, b_day = a.occurred_at.astimezone(tz).date(), b.occurred_at.astimezone(tz).date()
    if abs((a_day - b_day).days) > NEAR_DAYS:
        return False
    if not (any_source or not _same_kind(a, b)):
        return False
    if a.amount.currency != b.amount.currency:
        return (
            value is not None
            and _named_alike(a.merchant, b.merchant)
            and _close_in_value(a.amount, b.amount, a_day, b_day, value)
        )
    return a.amount == b.amount and same_merchant(a.merchant, b.merchant)


def _score(name: str) -> tuple[int, int, int]:
    """Lower is more readable: no "*", fewer digits, then shorter."""
    return ("*" in name, sum(c.isdigit() for c in name), len(name))


def better_name(a: str | None, b: str | None) -> str | None:
    """The more readable of two merchant names: "Grab Singapore" over the bank's
    "Grab* A-7KXPLMQZRTWB". A tie keeps the first."""
    if not a or not b:
        return a or b
    return b if _score(b) < _score(a) else a


def pair_key(a: object, b: object) -> tuple[str, str]:
    """The same key for a pair whichever way round it's given."""
    first, second = sorted((str(a), str(b)))
    return first, second
