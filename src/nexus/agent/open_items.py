"""Open items: things the user said they'd come back to, or that wait on them ("Jumbo
dinner on Sat 24 Oct, about 80; the user will send the exact amount").

A rolling summary can lose such a detail, so the summariser also lists them, in a section
after the summary, and the code carries them in the thread's state: capped, aged out after
a few days, and shown to the model as information it may use, never as an instruction.
Everything here is pure; the graph does the model call and the state writes."""

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TypedDict

MAX_ITEMS = 5
MAX_AGE = timedelta(days=3)
MAX_TEXT = 200  # characters in one item

# The line that starts the section, however the model decorates it ("**OPEN:**", "# Open:").
_SECTION = re.compile(r"^[ \t>#*_-]*OPEN[ \t]*:[ \t*_]*", re.IGNORECASE | re.MULTILINE)
_BULLET = re.compile(r"^(?:[-*•\u2013]+|\d{1,2}[.)])\s+")
_NONE = frozenset({"none", "n/a", "nothing", "no open items", "-", "\u2013"})


class OpenItem(TypedDict):
    text: str
    since: str  # when it was first listed (UTC, ISO)


def split_reply(reply: str) -> tuple[str, list[str] | None]:
    """The summary and the open items in the summariser's reply. The items are None when
    the reply has no OPEN section (the caller keeps what it had); an empty list when it
    says there are none. The section never stays in the summary."""
    found = _SECTION.search(reply)
    if found is None:
        return reply.strip(), None
    summary = reply[: found.start()].strip()
    items: list[str] = []
    # The first line is whatever followed "OPEN:" on its own line ("OPEN: none").
    for line in reply[found.end() :].splitlines():
        text = _BULLET.sub("", line.strip()).strip(" \t*_")
        text = " ".join(text.split())
        if not text or text.strip("()[].").casefold() in _NONE:
            continue
        if len(text) > MAX_TEXT:
            text = text[: MAX_TEXT - 1].rstrip() + "…"
        if text.casefold() not in {i.casefold() for i in items}:
            items.append(text)
    return summary, items[:MAX_ITEMS]


def _age(item: OpenItem, now: datetime) -> timedelta | None:
    try:
        since = datetime.fromisoformat(item["since"])
    except (KeyError, TypeError, ValueError):
        return None
    if since.tzinfo is None:
        since = since.replace(tzinfo=UTC)
    return now - since


def live(items: Sequence[OpenItem] | None, now: datetime) -> list[OpenItem]:
    """The items still worth showing: at most MAX_ITEMS, none older than MAX_AGE, and none
    whose time can't be read (they could never age out)."""
    kept: list[OpenItem] = []
    for item in items or ():
        age = _age(item, now)
        if age is not None and age <= MAX_AGE and str(item.get("text", "")).strip():
            kept.append(item)
    return kept[:MAX_ITEMS]


def carry(previous: Sequence[OpenItem], listed: list[str] | None, now: datetime) -> list[OpenItem]:
    """The items after a summary pass. ``listed`` is what the summariser returned (None:
    no section, so the items so far stay). An item it lists again word for word keeps its
    first-listed time, so it can still age out; a new one starts now."""
    still = live(previous, now)
    if listed is None:
        return still
    since = {i["text"].casefold(): i["since"] for i in still}
    stamp = now.astimezone(UTC).isoformat()
    return [{"text": t, "since": since.get(t.casefold(), stamp)} for t in listed[:MAX_ITEMS]]
