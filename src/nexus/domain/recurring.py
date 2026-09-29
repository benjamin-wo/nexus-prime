"""Recurring payments and subscriptions. Pure rules, no I/O.

A merchant that charged a similar amount on a regular schedule three times in a row
is proposed as a subscription. Nothing is tracked until the user says so, and a
proposal the user turns down isn't made again.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise
from uuid import UUID

from nexus.domain.ledger import UserId
from nexus.domain.money import Money
from nexus.domain.planning import Cadence, due_date

MIN_MATCHES = 3  # charges in a row before a proposal
LOOKBACK = timedelta(days=800)  # enough history to see three yearly charges
# Each of the charges must be within this share of the latest one.
AMOUNT_TOLERANCE = Decimal("0.2")
# A tracked subscription's new charge differing by more than this is a price change.
PRICE_CHANGE = Decimal("0.01")

# The gaps between charges (days) that make each schedule, and how long after the
# expected charge a schedule is still considered running.
_GAPS = {
    Cadence.WEEKLY: (6, 8),
    Cadence.MONTHLY: (26, 35),
    Cadence.YEARLY: (350, 380),
}
_GRACE = {Cadence.WEEKLY: 4, Cadence.MONTHLY: 14, Cadence.YEARLY: 30}
_NOISE = re.compile(r"[#*_]+|\d{3,}")  # reference numbers, not "7-Eleven"
_SPACES = re.compile(r"\s+")


class SubscriptionStatus(StrEnum):
    PROPOSED = "proposed"  # asked, not answered
    ACTIVE = "active"  # the user is tracking it
    DISMISSED = "dismissed"  # the user said no, or stopped tracking it


@dataclass(frozen=True, slots=True)
class Charge:
    transaction_id: UUID
    day: date  # local date of the charge
    amount: Money
    merchant: str  # as recorded


@dataclass(frozen=True, slots=True)
class Candidate:
    key: str
    merchant: str
    cadence: Cadence
    amount: Money  # the latest charge
    last_day: date
    transaction_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class Subscription:
    id: UUID
    user_id: UserId
    key: str  # the merchant, normalised: how charges are matched
    name: str
    cadence: Cadence
    amount: Money
    last_charged_on: date
    status: SubscriptionStatus
    created_at: datetime
    updated_at: datetime
    previous_amount: Money | None = None  # before the latest price change
    price_changed_on: date | None = None


def merchant_key(counterparty: str | None) -> str | None:
    """'NETFLIX.COM 8829' and 'Netflix.com' are one merchant: casefolded, with
    reference numbers (three digits or more) left out."""
    if not counterparty:
        return None
    key = _SPACES.sub(" ", _NOISE.sub(" ", counterparty.casefold())).strip(" .-")
    return key if len(key) >= 2 else None


def display_name(counterparty: str) -> str:
    """The merchant as recorded, less reference numbers: 'Netflix.com 8829' reads
    'Netflix.com'."""
    cleaned = _SPACES.sub(" ", _NOISE.sub(" ", counterparty)).strip(" .-")
    return cleaned or counterparty.strip()


def next_charge(cadence: Cadence, last: date) -> date:
    return due_date(last, cadence, 1)


def cadence_of(days: list[date]) -> Cadence | None:
    """The schedule that fits every gap between these (sorted) days, if one does."""
    gaps = [(b - a).days for a, b in pairwise(days)]
    for cadence, (low, high) in _GAPS.items():
        if gaps and all(low <= g <= high for g in gaps):
            return cadence
    return None


def _similar(amounts: list[Money], latest: Money) -> bool:
    limit = latest.amount * AMOUNT_TOLERANCE
    return all(abs(a.amount - latest.amount) <= limit for a in amounts)


def still_running(cadence: Cadence, last: date, today: date) -> bool:
    return today <= next_charge(cadence, last) + timedelta(days=_GRACE[cadence])


def find_recurring(charges: list[Charge], today: date) -> list[Candidate]:
    """Merchants whose latest charges came on a regular schedule, similar each time,
    and are still coming."""
    groups: dict[tuple[str, str], list[Charge]] = {}
    for c in charges:
        key = merchant_key(c.merchant)
        if key is not None and c.amount.is_positive:
            groups.setdefault((key, c.amount.currency), []).append(c)
    found = []
    for (key, _), group in groups.items():
        # One charge per day: two on the same day are the same visit or a correction.
        by_day = {c.day: c for c in sorted(group, key=lambda c: c.day)}
        recent = list(by_day.values())[-MIN_MATCHES:]
        if len(recent) < MIN_MATCHES:
            continue
        cadence = cadence_of([c.day for c in recent])
        latest = recent[-1]
        if cadence is None or not _similar([c.amount for c in recent], latest.amount):
            continue
        if not still_running(cadence, latest.day, today):
            continue
        found.append(
            Candidate(
                key,
                display_name(latest.merchant),
                cadence,
                latest.amount,
                latest.day,
                tuple(c.transaction_id for c in recent),
            )
        )
    return sorted(found, key=lambda c: c.last_day, reverse=True)


def price_changed(subscription: Subscription, charged: Money) -> bool:
    if charged.currency != subscription.amount.currency:
        return False
    before = subscription.amount.amount
    return abs(charged.amount - before) > before * PRICE_CHANGE


def monthly_cost(subscription: Subscription) -> Money:
    """What it comes to per month, for totals: weekly x 52/12, yearly / 12."""
    factor = {
        Cadence.WEEKLY: Decimal(52) / Decimal(12),
        Cadence.MONTHLY: Decimal(1),
        Cadence.YEARLY: Decimal(1) / Decimal(12),
    }.get(subscription.cadence, Decimal(1))
    amount = (subscription.amount.amount * factor).quantize(Decimal("0.01"))
    return Money(amount, subscription.amount.currency)


CADENCE_WORDS = {Cadence.WEEKLY: "week", Cadence.MONTHLY: "month", Cadence.YEARLY: "year"}
