"""Category rules: a word or phrase that files new expenses under a category.

Pure rules, no I/O. A rule only ever changes because the user asked for it; a
correction to one transaction never rewrites a rule on its own.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId

MIN_PATTERN = 2
MAX_PATTERN = 60
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class CategoryRule:
    id: UUID
    user_id: UserId
    pattern: str  # normalised: casefolded, single spaces
    category_id: UUID
    explanation: str  # why the rule exists, in the user's words and dates
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.archived_at is None


def normalize(text: str) -> str:
    """Casefold and collapse whitespace, so 'Grab  Food' and 'grab food' are one."""
    return _SPACES.sub(" ", text).strip().casefold()


def clean_pattern(text: str) -> str:
    pattern = normalize(text).strip(".,;:!?'\"()[]")
    if len(pattern) < MIN_PATTERN:
        raise InvalidInput(f"a rule needs at least {MIN_PATTERN} characters to match")
    if len(pattern) > MAX_PATTERN:
        raise InvalidInput(f"a rule can match at most {MAX_PATTERN} characters")
    return pattern


def matches(pattern: str, text: str | None) -> bool:
    """Whole words only: 'grab' matches 'Grab ride' but not 'grabbed'."""
    if not text:
        return False
    return re.search(rf"(?<!\w){re.escape(pattern)}(?!\w)", normalize(text)) is not None


def best_rule(
    rules: Iterable[CategoryRule], counterparty: str | None, notes: str | None
) -> CategoryRule | None:
    """The rule that files an expense. A match on the merchant beats one on the notes;
    then the longest (most specific) pattern wins; then the oldest rule."""
    ranked: list[tuple[int, int, datetime, str, CategoryRule]] = []
    for rule in rules:
        if not rule.active:
            continue
        if matches(rule.pattern, counterparty):
            place = 0
        elif matches(rule.pattern, notes):
            place = 1
        else:
            continue
        ranked.append((place, -len(rule.pattern), rule.created_at, str(rule.id), rule))
    return min(ranked, key=lambda r: r[:4])[4] if ranked else None


def pattern_for(counterparty: str | None) -> str | None:
    """The pattern a correction would suggest: the merchant, if it makes a usable one."""
    if not counterparty:
        return None
    try:
        return clean_pattern(counterparty)
    except InvalidInput:
        return None
