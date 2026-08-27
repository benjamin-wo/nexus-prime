"""Structural identity binding for agent-callable tools.

Replaces the old pattern (orchestrator/router.py's GeneralPlugin tool loop
used to keep a hardcoded tuple of tool names and force-override `user_id` on
just those) with a decorator applied at tool-definition time. A sensitive
tool guarded this way is safe by construction the moment it's written; an
*unguarded* owner-scoped tool is now the visible exception a reviewer should
question, not an easy-to-forget entry omitted from a growing allowlist.

Usage::

    @tool
    @identity_bound
    async def process_extracted_expense(user_id: int, ...): ...

`@identity_bound` must sit *between* `@tool` and the function body (i.e.
`@tool` on top) so LangChain's schema introspection still sees the original
signature (via `functools.wraps`'s `__wrapped__`) while the trusted user_id
is injected before the tool body ever runs -- regardless of what the model
did or didn't pass for `user_id`.
"""

from __future__ import annotations

import contextvars
import functools
from typing import Awaitable, Callable, Optional, TypeVar

# Unset (None) outside of an agent-loop turn -- e.g. core/scheduler.py's
# background email sweep, app/ingress.py's slash-command handlers, and
# orchestrator/recipes.py's playbooks all call these same @tool functions
# directly today with an explicit, already-trusted user_id, and none of them
# call bind_user_id(). Set only by orchestrator/agent_loop.py at the top of
# a turn, from the trusted, server-resolved user_id (never from anything the
# model could influence). identity_bound only overrides when this is set, so
# those direct/internal callers keep working unmodified while any agent-
# initiated tool call is guarded regardless of what the model passed.
current_user_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "current_user_id", default=None
)

F = TypeVar("F", bound=Callable[..., Awaitable[object]])


def bind_user_id(user_id: int) -> contextvars.Token:
    """Set the trusted user_id for the current agent-loop turn. Returns a
    token for `current_user_id.reset(token)` once the turn completes --
    callers should always reset in a `finally` so one turn's identity never
    leaks into the next task on the same event loop."""
    return current_user_id.set(int(user_id or 0))


def identity_bound(fn: F) -> F:
    """Wrap an async tool function so that, ONLY while a `bind_user_id()`
    scope is active (i.e. we're inside an agent-loop turn processing a
    model-initiated tool call), any `user_id` kwarg the model supplied or
    omitted is unconditionally replaced with the trusted bound value before
    the tool body runs. Outside such a scope -- a trusted direct/internal
    caller -- the explicit user_id it passed flows through untouched.

    The override is intentionally unconditional within an active scope --
    no "only if missing" branch -- because a model-supplied user_id there is
    not a hint to fall back on, it's untrusted input that must never reach a
    DB query or write.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        bound = current_user_id.get()
        if bound is not None:
            kwargs["user_id"] = int(bound)
        return await fn(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
