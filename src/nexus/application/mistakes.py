"""Signs that the agent got something wrong, recorded as anonymous ops events of kind
"agent" (see ops.py) so the ops report can count them over a week.

The repository and its issues are public, so nothing a user said, wrote or spent is
kept: an event holds tool names, counts, step numbers, seconds and error class names,
nothing else. A developer turns the counts into made-up eval cases.

The signals (the event's name):

- ``step_limit``: a turn ran out of steps. ``wrote`` (did it change anything), ``tools``.
- ``empty_reply``: the model sent nothing. ``recovered`` (did the retry work).
- ``unknown_tool``: the model called a tool that isn't there. ``tool`` (the real tool it
  most likely meant, if any is close); the made-up name itself is not kept, since a model
  can put a person's name in it ("split_with_ann").
- ``tool_error``: a tool refused or crashed. ``tool``, ``error`` (a coarse class: NotFound,
  InvalidInput, Conflict, Forbidden, ... or "Refused" when the tool answered "Error:"
  without an exception; for a crash, the exception's class name) and ``crashed``.
- ``undo``: an Undo (the button, typed "undo", or the ``undo_last_change`` tool, or the
  web app's). ``tools`` (what was undone), ``seconds`` since that change, ``quick`` (within
  two minutes: a strong sign the change was wrong).
- ``correction``: the user's next message starts like a correction ("no", "I meant"). Only
  that it matched, and ``tools`` of the turn before (those that changed something, else
  all of them), never the message. Not recorded when the turn before used no tool.
"""

import re
from collections.abc import Collection, Iterable, Sequence
from datetime import datetime

from nexus.application import ops
from nexus.application.clock import utcnow
from nexus.domain import errors
from nexus.domain.ledger import Direction, RevisionKind
from nexus.domain.trip_changes import ChangeKind

KIND = "agent"
STEP_LIMIT = "step_limit"
EMPTY_REPLY = "empty_reply"
UNKNOWN_TOOL = "unknown_tool"
TOOL_ERROR = "tool_error"
UNDO = "undo"
CORRECTION = "correction"
SIGNALS = (STEP_LIMIT, EMPTY_REPLY, UNKNOWN_TOOL, TOOL_ERROR, UNDO, CORRECTION)

QUICK_UNDO_SECONDS = 120
MAX_TOOLS = 5  # tool names kept on one event


def tool_list(names: Iterable[str], known: Collection[str]) -> list[str]:
    """Distinct names of real tools only (the model can type anything), sorted, at most
    ``MAX_TOOLS``."""
    return sorted({n for n in names if n in known})[:MAX_TOOLS]


# Most specific first; the first that the exception is an instance of names it.
_ERROR_KINDS: tuple[tuple[type[Exception], str], ...] = (
    (errors.NothingToUndo, "NothingToUndo"),
    (errors.NotFound, "NotFound"),
    (errors.Forbidden, "Forbidden"),
    (errors.Conflict, "Conflict"),
    (errors.InvalidInput, "InvalidInput"),
    (errors.NexusError, "NexusError"),
)


def error_kind(exc: Exception) -> str:
    """A coarse category for an expected failure, from its class: never its message,
    which can hold what the user said."""
    for cls, name in _ERROR_KINDS:
        if isinstance(exc, cls):
            return name
    return type(exc).__name__


# --- Corrections ------------------------------------------------------------------

# The start of a message that takes back or fixes the last thing Nexus did. "no" must be
# the whole word ("now log lunch" and "nothing else" aren't corrections), and a polite
# "no thanks" answers an offer rather than fixing anything.
_CORRECTION = re.compile(
    r"^\W*(?:no(?!\s+(?:thanks|thank\s+you|need)\b)|nope|not\s+that|not\s+what|i\s+meant"
    r"|wrong|that(?:['\u2019]s|s|\s+is)\s+not|actually)\b",
    re.IGNORECASE,
)


def looks_like_correction(text: str) -> bool:
    return _CORRECTION.match(text) is not None


# --- Events -----------------------------------------------------------------------


def step_limit(*, wrote: bool, tools: Sequence[str]) -> None:
    ops.emit(KIND, STEP_LIMIT, ok=False, wrote=wrote, tools=list(tools) or None)


def empty_reply(*, recovered: bool) -> None:
    ops.emit(KIND, EMPTY_REPLY, ok=False, recovered=recovered)


def unknown_tool(suggested: str | None) -> None:
    ops.emit(KIND, UNKNOWN_TOOL, ok=False, tool=suggested)


def tool_error(tool: str, error: str, *, crashed: bool = False) -> None:
    ops.emit(KIND, TOOL_ERROR, ok=False, tool=tool, error=error, crashed=crashed or None)


def correction(tools: Sequence[str]) -> None:
    ops.emit(KIND, CORRECTION, ok=False, matched=True, tools=list(tools))


def undo(tools: Sequence[str], changed_at: datetime) -> None:
    """An Undo pressed; ``changed_at`` is when the change it reversed was made."""
    seconds = max(0, int((utcnow() - changed_at).total_seconds()))
    ops.emit(
        KIND,
        UNDO,
        ok=False,
        tools=list(tools) or None,
        seconds=seconds,
        quick=seconds <= QUICK_UNDO_SECONDS,
    )


def revision_tool(kind: RevisionKind, direction: Direction) -> str:
    """The tool a ledger change most likely came from (for counting, so approximate)."""
    match kind:
        case RevisionKind.SPLIT:
            return "split_bill"
        case RevisionKind.EDIT:
            return "edit_transaction"
        case RevisionKind.DELETE:
            return "delete_transaction"
        case RevisionKind.RESTORE:
            return "restore_transaction"
        case RevisionKind.CREATE:
            if direction is Direction.IN:
                return "record_income"
            return "log_move" if direction is Direction.MOVE else "log_expense"


TRIP_TOOLS = {
    ChangeKind.ADD: "add_to_itinerary",
    ChangeKind.REMOVE: "remove_from_itinerary",
    ChangeKind.CHANGE: "change_itinerary_entry",
}
