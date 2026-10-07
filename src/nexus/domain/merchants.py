"""Suggestions for who an expense was paid to, from the user's own past entries: so
"foodcourt abc", eaten at every day, is a tap away instead of typed again. Pure rules,
no I/O."""

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nexus.domain.ledger import Transaction
from nexus.domain.money import Money

MAX_SUGGESTIONS = 8
LOOKBACK_DAYS = 365  # entries older than this don't suggest anything
MAX_ENTRIES = 2000  # the most recent entries looked at
MAX_QUERY = 60


def merchant_key(name: str) -> str:
    """The same key for the same merchant however it's typed: "Foodcourt ABC",
    " foodcourt  abc", "FOODCOURT-ABC"."""
    return " ".join(re.findall(r"[^\W_]+", name.casefold()))


@dataclass(frozen=True, slots=True)
class MerchantSuggestion:
    name: str  # as last written
    category_id: UUID | None  # the category used most for it
    amount: Money  # the amount paid most often (the latest when none repeats)
    times: int  # how often it's in the ledger
    last: datetime


def _match(key: str, wanted: str) -> int | None:
    """How well a merchant matches what's typed: 0 starts with it, 1 a word starts
    with it, 2 contains it; None when it doesn't."""
    if not wanted:
        return 0
    if key.startswith(wanted):
        return 0
    if any(word.startswith(wanted) for word in key.split()[1:]):
        return 1
    if wanted in key:
        return 2
    return None


def suggest(
    entries: list[Transaction], typed: str, *, limit: int = MAX_SUGGESTIONS
) -> list[MerchantSuggestion]:
    """Merchants from past entries (newest first) that match what's typed: the best
    match first, then the most used, then the most recent. With nothing typed, the
    most used."""
    wanted = merchant_key(typed[:MAX_QUERY])
    groups: dict[str, list[Transaction]] = {}
    for tx in entries:
        if tx.counterparty and (key := merchant_key(tx.counterparty)):
            groups.setdefault(key, []).append(tx)
    ranked = []
    for key, txs in groups.items():
        how = _match(key, wanted)
        if how is None or key == wanted:
            continue  # nothing to suggest when it's already typed in full
        latest = max(txs, key=lambda t: (t.occurred_at, t.created_at))
        ranked.append((how, -len(txs), -latest.occurred_at.timestamp(), _suggestion(txs, latest)))
    ranked.sort(key=lambda r: r[:3])
    return [r[3] for r in ranked[:limit]]


def _suggestion(txs: list[Transaction], latest: Transaction) -> MerchantSuggestion:
    newest_first = sorted(txs, key=lambda t: (t.occurred_at, t.created_at), reverse=True)
    amounts = Counter(t.amount for t in newest_first)
    top_amount, seen = amounts.most_common(1)[0]
    categories = Counter(t.category_id for t in newest_first if t.category_id)
    category = categories.most_common(1)[0][0] if categories else None
    return MerchantSuggestion(
        name=(latest.counterparty or "").strip(),
        category_id=category,
        amount=top_amount if seen > 1 else latest.amount,
        times=len(txs),
        last=latest.occurred_at,
    )
