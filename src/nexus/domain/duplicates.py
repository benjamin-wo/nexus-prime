"""One payment recorded twice: a bank's card alert and the shop's own receipt, or an
entry the user typed and the email that followed. Pure rules, no I/O.

Nothing is ever merged on a guess: a match only lets Nexus ask. Two rides home at
the same price on the same day are real, so the rule is narrow: the same amount
and direction within a day, by what looks like the same merchant.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from nexus.domain.ledger import Direction, Source, Transaction
from nexus.domain.money import Money

# A card alert and a receipt can be dated a day apart (a late-night ride).
NEAR_DAYS = 1

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


def likely_same(a: Candidate, b: Candidate, tz: ZoneInfo, *, any_source: bool = False) -> bool:
    """Whether two records look like one payment. ``any_source``: for a bill marked
    paid, where an entry of any kind for the same amount is the bill already logged."""
    if a.direction is not b.direction or a.amount != b.amount:
        return False
    days = abs((a.occurred_at.astimezone(tz).date() - b.occurred_at.astimezone(tz).date()).days)
    if days > NEAR_DAYS:
        return False
    return (any_source or not _same_kind(a, b)) and same_merchant(a.merchant, b.merchant)


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
