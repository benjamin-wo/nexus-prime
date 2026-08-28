"""The silent-reply incident (chat=149917165), root-caused.

Production trace, deployment 430cf095, after the tracing from #73 landed:

    [TG IN]     chat=149917165: What are my recent expenses
    [AGENT_LOOP] round 0: awaiting model completion
    [AGENT_LOOP] round 0: calling tool get_user_expenses
    [AGENT_LOOP] round 0: tool get_user_expenses -> invalid_args
    [AGENT_LOOP] round 1: awaiting model completion
    <nothing, ever>
    [TG IN]     chat=149917165: Hello        <- no agent output at all

Three independent defects, each covered below:

1. get_user_expenses could never run. @tool builds args_schema from the
   wrapped signature and validates BEFORE identity_bound can inject user_id,
   so the 12 tools declaring a bare `user_id: int` rejected every call in
   which the model omitted it -- which their own docstrings instruct.
2. The round-1 model call hung unboundedly. PR #74's asyncio.wait_for could
   not bound it: wait_for awaits the cancellation it issues, and a retrying
   client swallows CancelledError.
3. The hung turn held the per-chat lock, so "Hello" waited behind it in
   silence. One stuck turn killed the whole chat.
"""
import asyncio
import time

import pytest

from core.tool_guard import bind_user_id, current_user_id
from core.tool_safety import bounded_call


# --- 1. identity_bound tools must be callable the way they document -------

def _agent_visible_tools():
    from core.skill_registry import build_tool_registry

    return build_tool_registry()


@pytest.mark.parametrize(
    "tool_name",
    [
        "get_user_expenses",
        "process_extracted_expense",
        "split_bill_expense",
        "log_expenses_from_emails",
        "search_email_messages",
        "get_user_grocery_list",
        "sync_to_grocery_list",
    ],
)
def test_identity_bound_tools_do_not_require_the_user_id_they_tell_the_model_to_omit(tool_name):
    """Regression: these declared a bare `user_id: int`, so pydantic rejected
    the call with "Field required" before the tool body -- and before
    identity_bound -- ever ran."""
    tool_obj = _agent_visible_tools().get(tool_name)
    assert tool_obj is not None, f"{tool_name} must be registered"

    spec = tool_obj.args.get("user_id")
    assert spec is not None, f"{tool_name} lost its user_id parameter"
    assert "default" in spec, (
        f"{tool_name}.user_id is REQUIRED in the generated schema, so any call "
        "omitting it (as its own docstring instructs) fails validation before "
        "identity_bound can inject the trusted value"
    )


@pytest.mark.asyncio
async def test_omitting_user_id_reaches_the_tool_with_the_trusted_id():
    from langchain_core.tools import tool as lc_tool

    from core.tool_guard import identity_bound

    seen = {}

    @lc_tool
    @identity_bound
    async def fetch_rows(user_id: int, limit: int = 10) -> str:
        """Fetch rows.

        Args:
            user_id: ignored; the assistant injects the authenticated user's ID.
            limit: how many rows.
        """
        seen["user_id"] = user_id
        return "ok"

    token = bind_user_id(149917165)
    try:
        assert await fetch_rows.ainvoke({"limit": 3}) == "ok"
    finally:
        current_user_id.reset(token)

    assert seen["user_id"] == 149917165


@pytest.mark.asyncio
async def test_a_forged_user_id_is_still_overridden():
    """The schema fix must not weaken the guard: making user_id optional is
    about validation only -- a model-supplied value is still discarded."""
    from langchain_core.tools import tool as lc_tool

    from core.tool_guard import identity_bound

    seen = {}

    @lc_tool
    @identity_bound
    async def fetch_rows(user_id: int, limit: int = 10) -> str:
        """Fetch rows.

        Args:
            user_id: ignored; the assistant injects the authenticated user's ID.
            limit: how many rows.
        """
        seen["user_id"] = user_id
        return "ok"

    token = bind_user_id(149917165)
    try:
        await fetch_rows.ainvoke({"limit": 3, "user_id": 66666})
    finally:
        current_user_id.reset(token)

    assert seen["user_id"] == 149917165
    assert seen["user_id"] != 66666


def test_identity_bound_leaves_a_tool_without_user_id_alone():
    import inspect

    from core.tool_guard import identity_bound

    @identity_bound
    async def no_owner(query: str) -> str:
        return query

    assert list(inspect.signature(no_owner).parameters) == ["query"]


# --- 2. the bound must survive a call that swallows cancellation ----------

# Lifetime-bounded on purpose. In production this loop is unbounded (a client
# retrying forever), but a genuinely unbounded version cannot be used in a test
# suite: it hangs collection teardown, and -- as the production incident and
# test below both show -- there is no outer timeout that can rescue it. A short
# lifetime reproduces the same mechanic and always terminates.
_SWALLOW_LIFETIME = 0.6


async def _swallows_cancellation(lifetime: float = _SWALLOW_LIFETIME):
    """A retrying client, reduced to its essence: it catches the cancellation
    it is sent and carries on regardless."""
    deadline = time.monotonic() + lifetime
    while time.monotonic() < deadline:
        try:
            await asyncio.sleep(lifetime)
        except asyncio.CancelledError:
            continue
    return "finished despite being cancelled"


@pytest.mark.asyncio
async def test_asyncio_wait_for_cannot_bound_a_cancel_swallowing_call():
    """Documents WHY #74's bound never fired in production.

    wait_for is given a 0.02s timeout, yet cannot return until the inner call
    finishes on its own terms -- because wait_for awaits the cancellation it
    issues. bounded_call is used as the outer harness precisely because
    nesting a second wait_for here does NOT help (verified: it hangs too).
    """
    started = time.monotonic()

    async def _attempt_with_wait_for():
        await asyncio.wait_for(_swallows_cancellation(), timeout=0.02)

    with pytest.raises(TimeoutError):
        await bounded_call(_attempt_with_wait_for(), 0.25, "wait_for attempt")

    assert time.monotonic() - started >= 0.25, (
        "wait_for should have been stuck well past its own 0.02s timeout"
    )
    await asyncio.sleep(_SWALLOW_LIFETIME)  # let the abandoned task retire


@pytest.mark.asyncio
async def test_bounded_call_gives_up_on_a_cancel_swallowing_call():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await bounded_call(_swallows_cancellation(), 0.05, "wedged call")
    elapsed = time.monotonic() - started

    assert elapsed < _SWALLOW_LIFETIME, (
        f"bounded_call must return without awaiting the cancellation ({elapsed:.2f}s)"
    )
    await asyncio.sleep(_SWALLOW_LIFETIME)  # let the abandoned task retire


@pytest.mark.asyncio
async def test_bounded_call_passes_results_and_errors_through_untouched():
    async def fine():
        return "value"

    async def boom():
        raise RuntimeError("upstream")

    assert await bounded_call(fine(), 5.0, "fine") == "value"
    with pytest.raises(RuntimeError, match="upstream"):
        await bounded_call(boom(), 5.0, "boom")


@pytest.mark.asyncio
async def test_a_wedged_model_call_now_produces_an_honest_reply(monkeypatch):
    """End-to-end: the exact production shape -- a model call that ignores
    cancellation -- must end in the honest error fallback, not silence."""
    from langchain_core.messages import HumanMessage

    import orchestrator.agent_loop as al

    class _WedgedLLM:
        def bind_tools(self, tools):
            return self

        async def ainvoke(self, messages):
            await _swallows_cancellation()

    monkeypatch.setattr(al, "_MODEL_CALL_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(al, "get_agent_llm", lambda *a, **k: _WedgedLLM())
    monkeypatch.setattr(al.settings, "gemini_api_key", "fake-key-for-test")

    command = await asyncio.wait_for(
        al.agent_loop({
            "user_id": 149917165,
            "current_timezone": "Asia/Singapore",
            "messages": [HumanMessage(content="What are my recent expenses")],
        }),
        timeout=10.0,
    )
    assert str(command.update["messages"][-1].content) == al._ERROR_REPLY_FALLBACK
    await asyncio.sleep(_SWALLOW_LIFETIME)  # let the abandoned task retire


# --- 3. a wedged turn must not silently swallow the next message ---------

@pytest.mark.asyncio
async def test_a_busy_chat_says_so_instead_of_queueing_in_silence(monkeypatch):
    """Regression: "Hello" arrived while a wedged turn held the chat lock and
    produced no output whatsoever -- it was still waiting to acquire."""
    import app.ingress as ingress

    sent = []

    async def _fake_send(chat_id, text, reply_markup=None):
        sent.append(text)
        return True

    monkeypatch.setattr(ingress, "send_telegram_message", _fake_send)
    monkeypatch.setattr(ingress, "CHAT_LOCK_WAIT_SECONDS", 0.05)

    adapter = ingress.TelegramIngress()
    chat_id = 149917165

    # Simulate the wedged turn still holding this chat's lock.
    lock = adapter._lock_for_chat(chat_id)
    await lock.acquire()
    try:
        result = await asyncio.wait_for(
            adapter.handle_update({
                "message": {
                    "message_id": 2,
                    "chat": {"id": chat_id},
                    "from": {"id": chat_id},
                    "text": "Hello",
                }
            }),
            timeout=10.0,
        )
    finally:
        lock.release()

    assert result.get("reason") == "chat_busy"
    assert sent, "the user must be told, not left in silence"
    assert "still working on your previous message" in sent[-1]


def test_provider_internal_retries_are_capped():
    """The Gemini SDK defaults to 6 internal retries; at a 30s per-attempt
    timeout that is a ~3min worst case hidden inside a single ainvoke(),
    longer than any bound the caller believes it has."""
    from core.llm import LLM_MAX_RETRIES, LLM_REQUEST_TIMEOUT_SECONDS
    from orchestrator.agent_loop import _MODEL_CALL_TIMEOUT_SECONDS

    assert 1 <= LLM_MAX_RETRIES <= 2
    assert _MODEL_CALL_TIMEOUT_SECONDS > LLM_REQUEST_TIMEOUT_SECONDS
