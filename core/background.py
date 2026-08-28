"""Fire-and-forget asyncio tasks, done safely.

``asyncio.create_task(coro())`` with the returned Task discarded is a well
known footgun: per the stdlib docs, "the event loop only keeps weak
references to tasks... a task that isn't referenced elsewhere may get
garbage collected at any time, even before it's done." In practice this
means a background task can simply vanish mid-await, with no exception and
nothing printed -- exactly the shape of a live incident (chat=149917165,
"Coffee at hive Adelphi Samuel paid me 5.50..."): app/webhook.py's
fire-and-forget dispatch (`asyncio.create_task(telegram_ingress.
handle_update(payload))`, no reference kept) silently stopped executing
partway through -- past its own internal error fallback (the
"[AGENT_LOOP] tool loop failed, using fallback" print did run) but before
ever reaching send_telegram_message -- so the user got no reply at all, not
even the honest "something glitched" fallback, and nothing showed up in
Railway logs to explain it.

app/dashboard_api.py's _schedule_cover_generation already had the right
pattern (a module-level dict of in-flight tasks plus a done-callback to
clean up) -- this module generalizes that into one shared helper so every
fire-and-forget call site in the codebase gets it for free instead of
reimplementing (or forgetting) it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Coroutine

# Strong references to every in-flight background task, keyed by id() so an
# arbitrary number of concurrent tasks (any coroutine, any call site) can be
# tracked without colliding. This is the only thing standing between a task
# and premature GC -- the module attribute itself is what survives for the
# life of the process.
_background_tasks: set[asyncio.Task] = set()


def fire_and_forget(coro: Coroutine[Any, Any, Any]) -> asyncio.Task:
    """Schedule `coro` to run in the background and keep it alive until it
    finishes. Use this instead of a bare `asyncio.create_task(...)` any time
    the result is intentionally not awaited -- which is exactly when the GC
    risk above applies. Returns the Task (rarely needed by the caller, but
    handy for tests)."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task
