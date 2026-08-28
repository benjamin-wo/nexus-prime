"""core.background.fire_and_forget: a bare `asyncio.create_task(coro())` with
the returned Task discarded is a documented asyncio footgun -- the event loop
only keeps a *weak* reference to a task, so nothing else stops it from being
garbage collected mid-await. app/dashboard_api.py's _schedule_cover_generation
already worked around this correctly (a module-level dict of in-flight tasks
plus a done-callback to clean up); this module generalizes that pattern so
every fire-and-forget call site gets it for free instead of reimplementing
-- or forgetting -- it (as app/webhook.py's webhook dispatch, orchestrator/
agent_loop.py's audit task, app/ingress.py's bug-report task, and
core/scheduler.py's one-shot reminder task all did before this fix)."""
import asyncio

import pytest

from core.background import _background_tasks, fire_and_forget


@pytest.mark.asyncio
async def test_fire_and_forget_holds_a_strong_reference_until_completion():
    """The whole point: the task must be reachable from a module-level
    collection (not just the caller's local variable, which the caller is
    free to drop immediately) for as long as it's running, and cleaned up
    once it's done."""
    started = asyncio.Event()
    finish = asyncio.Event()

    async def worker():
        started.set()
        await finish.wait()

    task = fire_and_forget(worker())
    await started.wait()

    assert task in _background_tasks, "the running task must be tracked, not just returned"

    finish.set()
    await task  # let it actually finish and run its done-callback

    assert task not in _background_tasks, "a completed task must be untracked, not leaked forever"


@pytest.mark.asyncio
async def test_fire_and_forget_runs_the_coroutine_to_completion_with_no_caller_reference():
    """The caller drops every reference it holds (including the return
    value) immediately -- exactly the fire-and-forget call shape used at
    every real call site -- and the work must still complete."""
    result = {}

    async def worker():
        await asyncio.sleep(0)
        result["done"] = True

    fire_and_forget(worker())  # return value intentionally discarded

    await asyncio.sleep(0.05)
    assert result.get("done") is True
