"""A trip's Prep tab: to-dos, cover and documents (travel insurance, visas and the like),
and prep suggestions worked out in code from the trip. Pure rules, no I/O.

A to-do is a short line with an optional due date, ticked off when done. A cover is a
record of a policy or document: what it is, its reference and the number to call, the
dates it covers and what it cost. Nexus keeps the reference as the user's own, like a
booking reference, and never a card or passport number. What a cover cost is the trip
owner's money (see ``trip_access.without_cover_money``); Nexus only records it, and never
buys or claims anything.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId, clean_text
from nexus.domain.money import Money
from nexus.domain.private import hide_private

MAX_TODOS = 50
MAX_TODO = 80
MAX_COVERS = 30
MAX_COVER_NAME = 80
MAX_COVER_REFERENCE = 60
MAX_COVER_PHONE = 30
MAX_COVER_NOTE = 200

_TODO_ID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_PHONE = re.compile(r"^[0-9+()\- ]+$")


# --- to-dos ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Todo:
    id: str  # short and stable, so a reminder isn't sent twice for the same one
    text: str
    due: date | None = None
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "due": self.due.isoformat() if self.due else None,
            "done": self.done,
        }


def new_todo_id() -> str:
    return uuid4().hex[:8]


def _line(raw: str, limit: int) -> str:
    """One line of text: unprintable and invisible characters dropped, spaces collapsed."""
    printable = "".join(c for c in raw if c.isprintable() or c.isspace())
    return " ".join(printable.split())[:limit]


def from_rows(rows: Any) -> tuple[Todo, ...]:
    """Stored to-dos, skipping anything malformed."""
    items: list[Todo] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        ident, text = row.get("id"), row.get("text")
        if not (isinstance(ident, str) and _TODO_ID.match(ident)):
            continue
        if not (isinstance(text, str) and text.strip()):
            continue
        due = None
        if isinstance(row.get("due"), str):
            try:
                due = date.fromisoformat(row["due"])
            except ValueError:
                due = None
        items.append(Todo(ident, text[:MAX_TODO], due, bool(row.get("done"))))
    return tuple(items[:MAX_TODOS])


def clean_list(items: Iterable[Todo]) -> tuple[Todo, ...]:
    """The list as the user gave it, each to-do once (by its words, ignoring case), blank
    ones dropped, card and passport numbers hidden. A missing, odd or repeated id is
    replaced by a new one. Raises InvalidInput past MAX_TODOS."""
    seen: set[str] = set()
    ids: set[str] = set()
    out: list[Todo] = []
    for item in items:
        text = hide_private(_line(item.text, MAX_TODO))[:MAX_TODO].strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        ident = item.id if _TODO_ID.match(item.id) and item.id not in ids else new_todo_id()
        while ident in ids:  # pragma: no cover - a collision of two random ids
            ident = new_todo_id()
        ids.add(ident)
        out.append(Todo(ident, text, item.due, item.done))
    if len(out) > MAX_TODOS:
        raise InvalidInput(f"keep at most {MAX_TODOS} things on the to-do list")
    return tuple(out)


# --- cover and documents ---------------------------------------------------------------


class CoverKind(StrEnum):
    INSURANCE = "insurance"
    VISA = "visa"
    DOCUMENT = "document"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class CoverDraft:
    """What the user gives for a cover; ``clean_cover`` checks it."""

    kind: CoverKind
    name: str  # "Harbour Cover"
    reference: str | None = None  # the policy or visa number: the user's own
    phone: str | None = None  # an emergency or claims line
    starts: date | None = None
    ends: date | None = None
    cost: Money | None = None  # in any currency; the owner's money
    note: str | None = None

    def describe(self) -> str:
        """For chat: "Harbour Cover (insurance, ref TX-4471, phone +65 6123 4567, 10 Dec to
        18 Dec)". Never the cost."""
        parts = [self.kind.value]
        if self.reference:
            parts.append(f"ref {self.reference}")
        if self.phone:
            parts.append(f"phone {self.phone}")
        if self.starts and self.ends:
            parts.append(f"{self.starts:%d %b} to {self.ends:%d %b}")
        elif self.starts:
            parts.append(f"from {self.starts:%d %b}")
        elif self.ends:
            parts.append(f"until {self.ends:%d %b}")
        return f"{self.name} ({', '.join(parts)})"


@dataclass(frozen=True, slots=True)
class Cover:
    id: UUID
    user_id: UserId  # the trip's owner
    trip_id: UUID
    draft: CoverDraft
    logged_transaction_id: UUID | None  # the expense, once the owner logs the cost
    created_at: datetime
    updated_at: datetime

    @property
    def kind(self) -> CoverKind:
        return self.draft.kind

    @property
    def name(self) -> str:
        return self.draft.name

    @property
    def cost(self) -> Money | None:
        return self.draft.cost

    def describe(self) -> str:
        return self.draft.describe()


def _private_free(raw: str, *, what: str) -> str:
    """The text, or InvalidInput when it holds a card or passport number (it is refused,
    never stored half hidden)."""
    text = _line(raw, 10_000)
    if hide_private(text) != text:
        raise InvalidInput(f"a {what} can't hold a card or passport number; leave it out")
    return text


def clean_cover(draft: CoverDraft) -> CoverDraft:
    """The draft checked and tidied. InvalidInput for a blank or too long name, a
    reference or note that holds a card or passport number, a phone number with anything
    but digits, +, spaces, - and brackets, dates the wrong way round, or a cost of zero."""
    try:
        kind = CoverKind(draft.kind)
    except ValueError:
        raise InvalidInput("a cover is insurance, a visa, a document or other") from None
    name = clean_text(
        hide_private(_line(draft.name, 10_000)), field_name="name", limit=MAX_COVER_NAME
    )
    if name is None:
        raise InvalidInput("a cover needs a name")
    reference = None
    if draft.reference and draft.reference.strip():
        reference = clean_text(
            _private_free(draft.reference, what="reference"),
            field_name="reference",
            limit=MAX_COVER_REFERENCE,
        )
        if reference and "passport" in name.casefold():
            raise InvalidInput("a passport's number isn't kept; leave the reference out")
    phone = None
    if draft.phone and draft.phone.strip():
        phone = " ".join(draft.phone.split())
        if not _PHONE.match(phone) or not any(c.isdigit() for c in phone):
            raise InvalidInput("a phone number can only have digits, +, spaces, - and brackets")
        phone = clean_text(
            _private_free(phone, what="phone number"), field_name="phone", limit=MAX_COVER_PHONE
        )
    note = None
    if draft.note and draft.note.strip():
        note = clean_text(
            hide_private(_line(draft.note, 10_000)), field_name="note", limit=MAX_COVER_NOTE
        )
    if draft.starts and draft.ends and draft.ends < draft.starts:
        raise InvalidInput("a cover can't end before it starts")
    if draft.cost is not None and not draft.cost.is_positive:
        raise InvalidInput("a cost must be more than zero")
    return CoverDraft(kind, name, reference, phone, draft.starts, draft.ends, draft.cost, note)


# --- suggestions -----------------------------------------------------------------------

# The keys of the suggestions, in the order they are offered.
KEYS = ("insurance", "visa", "passport", "money")


@dataclass(frozen=True, slots=True)
class TripFacts:
    """What the suggestions are worked out from."""

    destination: str
    nights: int  # the trip's days less one
    abroad: bool  # spent in another currency than the owner's home one


@dataclass(frozen=True, slots=True)
class Suggestion:
    key: str  # what "Not needed" remembers
    text: str
    sub: str
    action: str  # "add_cover" opens the cover form, "add_todo" adds the text as a to-do


def country_of(destination: str) -> str:
    """ "Japan" for "Tokyo, Japan"; the destination itself when it has one part."""
    parts = [p.strip() for p in destination.split(",") if p.strip()]
    return parts[-1] if parts else destination.strip()


def _mentions(todos: Iterable[Todo], *words: str) -> bool:
    return any(w in t.text.casefold() for t in todos for w in words)


def suggestions(
    facts: TripFacts,
    covers: Sequence[Cover],
    todos: Sequence[Todo],
    dismissed: Iterable[str],
) -> list[Suggestion]:
    """What most trips like this still need, most important first, left out once it is
    done (a cover or a to-do covers it) or the user said it isn't needed."""
    if not facts.abroad:
        return []
    kinds = {c.kind for c in covers}
    found: list[Suggestion] = []
    if CoverKind.INSURANCE not in kinds:
        found.append(
            Suggestion(
                "insurance",
                "Travel insurance",
                "Medical and cancellation cover for the dates",
                "add_cover",
            )
        )
    if CoverKind.VISA not in kinds and not _mentions(todos, "visa", "entry rule"):
        found.append(
            Suggestion(
                "visa",
                f"Check entry rules for {country_of(facts.destination)}",
                "Visas and passport validity",
                "add_todo",
            )
        )
    if not _mentions(todos, "passport"):
        found.append(
            Suggestion(
                "passport",
                "Passport valid 6 months after you're back",
                "Many countries ask for it at the border",
                "add_todo",
            )
        )
    if facts.nights >= 1 and not _mentions(todos, "money", "cash", "card"):
        found.append(
            Suggestion(
                "money",
                "Tell your bank / sort a travel card",
                "So your card works while you're away",
                "add_todo",
            )
        )
    hidden = set(dismissed)
    return [s for s in found if s.key not in hidden]
