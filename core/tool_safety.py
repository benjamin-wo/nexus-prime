"""Fault-tolerant tool execution: structured errors, arg self-correction, hang and retry bounds.

Every tool call the agent makes goes through execute_tool_safely() instead of
a bare `await tool.ainvoke(args)` wrapped in a blanket `except Exception`.
The difference is what the model gets back when something goes wrong.

Three failure modes this exists to fix, all observed or structurally possible
in this repo:

1. **Hallucinated / malformed arguments.** A @tool's args_schema is a real
   Pydantic model generated from its signature, so a bad argument raises
   ValidationError -- previously caught by agent_loop's blanket handler and
   handed back as `[tool] failed: <raw multi-line pydantic dump>`. The model
   had to reverse-engineer its own mistake out of a stack-trace-shaped blob.
   Now a ValidationError is rendered as a crisp, actionable correction naming
   the offending fields AND restating the expected schema, so the next round
   is a genuine self-correction rather than a guess.

2. **Endless retry loops.** MAX_TOOL_ROUNDS (40) was the ONLY thing stopping a
   model that kept re-calling the same tool with the same broken arguments --
   it could burn all 40 rounds repeating one mistake. FailureLedger caps
   identical failing calls at MAX_REPEATED_FAILURES and then returns terminal
   guidance telling the model to stop and report honestly instead.

3. **Hangs.** A tool that never returns hangs the whole turn -- and the turn
   runs as a fire-and-forget background task, so nothing upstream is watching.
   TOOL_CALL_TIMEOUT_SECONDS is a hang backstop ONLY, deliberately generous;
   it is not a limit on how long the agent may reason (see agent_loop's
   MAX_TOOL_ROUNDS docstring -- "time is important but it should not limit
   the agent").

GraphBubbleUp (langgraph's interrupt() / Command signal) is never treated as a
failure -- it is re-raised untouched so HITL confirmation keeps working.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from langgraph.errors import GraphBubbleUp

# Pydantic v2 is what this repo runs, but langchain still wraps some tool
# schemas in its v1 compat shim -- catch whichever is importable so a
# validation error is never misclassified as a generic execution failure.
_VALIDATION_ERROR_TYPES: list = []
try:  # pragma: no cover - import shape depends on installed pydantic
    from pydantic import ValidationError as _V2Error

    _VALIDATION_ERROR_TYPES.append(_V2Error)
except ImportError:  # pragma: no cover
    pass
try:  # pragma: no cover
    from pydantic.v1 import ValidationError as _V1Error

    _VALIDATION_ERROR_TYPES.append(_V1Error)
except ImportError:  # pragma: no cover
    pass
VALIDATION_ERRORS: Tuple[type, ...] = tuple(_VALIDATION_ERROR_TYPES)

# Hang backstop, NOT a reasoning budget. Generous on purpose: real tools here
# chain external round-trips (Maps + one live LTA call per transit leg, a
# multi-message email sweep), and bounding those tightly is what caused the
# old ROUTE_RESOLUTION_TIMEOUT_SECONDS-era truncation bugs.
TOOL_CALL_TIMEOUT_SECONDS = 120.0

# How many times the SAME call (tool + identical args) may fail before the
# ledger stops feeding it back as retryable. 2 failures = 2 chances to
# self-correct; the 3rd identical attempt gets terminal guidance.
MAX_REPEATED_FAILURES = 2


async def bounded_call(coro, timeout: float, what: str):
    """Await ``coro``, giving up after ``timeout`` EVEN IF it refuses to die.

    asyncio.wait_for is not sufficient, and this is not theoretical -- it is
    the root cause of the silent-reply incident. wait_for cancels the inner
    task and then *awaits* that cancellation; a task that swallows
    CancelledError therefore hangs wait_for forever, past its own timeout.
    Reproduced directly: a coroutine looping `except CancelledError: continue`
    hung wait_for indefinitely, and even an OUTER wait_for around it could not
    break the deadlock.

    That is exactly the shape of a retrying HTTP/gRPC client (the Gemini SDK
    defaults to 6 internal retries), which is why PR #74's wait_for-based
    bound never fired in production despite being deployed and correct-looking.

    So: run it as a task, wait on the task, and on timeout cancel it
    best-effort and ABANDON it -- never await the cancellation. The orphaned
    task may linger until its own client-level timeout resolves it, which is
    the deliberate trade: a leaked task is survivable, a wedged turn is not
    (it holds the per-chat lock and silently swallows every later message).
    """
    task = asyncio.ensure_future(coro)
    _done, pending = await asyncio.wait({task}, timeout=timeout)
    if task in pending:
        task.cancel()  # best effort; deliberately NOT awaited
        raise TimeoutError(f"{what} did not complete within {timeout:.0f}s (abandoned)")
    return task.result()


@dataclass
class ToolOutcome:
    """Structured result of one tool invocation.

    `observation` is what gets appended to the transcript as a ToolMessage --
    it is written to be read by the model, so every non-success case states
    what went wrong AND what to do about it.
    """

    status: str  # success | invalid_args | error | timeout | unknown_tool | gave_up
    observation: str

    @property
    def ok(self) -> bool:
        return self.status == "success"

    @property
    def retryable(self) -> bool:
        """Whether a corrected retry could plausibly succeed. A validation
        error is the model's to fix; a timeout may be transient. A `gave_up`
        is terminal by construction."""
        return self.status in ("invalid_args", "timeout")


def _schema_hint(tool_obj: Any) -> str:
    """Compact restatement of a tool's expected arguments, so a correction
    message carries the target schema instead of only the complaint."""
    args = getattr(tool_obj, "args", None)
    if not isinstance(args, dict) or not args:
        return ""
    parts = []
    for name, spec in args.items():
        if not isinstance(spec, dict):
            parts.append(str(name))
            continue
        type_name = spec.get("type") or "any"
        desc = str(spec.get("description") or "").strip()
        enum_values = spec.get("enum")
        piece = f"{name} ({type_name}"
        if enum_values:
            piece += f", one of: {', '.join(str(v) for v in enum_values)}"
        piece += ")"
        if desc:
            piece += f" - {desc}"
        parts.append(piece)
    return "Expected arguments: " + "; ".join(parts)


def _format_validation_error(tool_name: str, exc: Exception, tool_obj: Any) -> str:
    """Turn a raw Pydantic ValidationError into a correction the model can act
    on: which field, what was wrong, and what the schema actually wants."""
    lines = []
    raw_errors = getattr(exc, "errors", None)
    if callable(raw_errors):
        try:
            for err in raw_errors():
                location = ".".join(str(p) for p in err.get("loc", ())) or "(root)"
                lines.append(f"  - {location}: {err.get('msg', 'invalid value')}")
        except Exception:  # noqa: BLE001 - never let error formatting itself fail
            lines = []
    detail = "\n".join(lines) if lines else f"  - {exc}"
    hint = _schema_hint(tool_obj)
    message = (
        f"[{tool_name}] INVALID ARGUMENTS - the call was rejected before it ran:\n"
        f"{detail}"
    )
    if hint:
        message += f"\n{hint}"
    message += "\nFix the arguments and call the tool again."
    return message


def _freeze(value: Any) -> Any:
    """Hashable projection of tool args, so repeated identical calls can be
    recognised regardless of dict ordering or nested structures."""
    if isinstance(value, dict):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    return repr(value)


@dataclass
class FailureLedger:
    """Per-turn tally of failing calls, keyed by (tool, exact args).

    Bounds the 'endless retry loop' failure mode: a model that keeps making
    the same broken call gets told to stop rather than being allowed to
    consume the entire MAX_TOOL_ROUNDS budget on one mistake. A call that
    succeeds, or that the model corrects, has a different key and is
    unaffected."""

    counts: Dict[Tuple[str, Any], int] = field(default_factory=dict)

    def exhausted(self, tool_name: str, args: dict) -> bool:
        return self.counts.get((tool_name, _freeze(args)), 0) >= MAX_REPEATED_FAILURES

    def record_failure(self, tool_name: str, args: dict) -> int:
        key = (tool_name, _freeze(args))
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]


async def execute_tool_safely(
    tool_obj: Any,
    args: dict,
    *,
    tool_name: str,
    ledger: FailureLedger | None = None,
    timeout: float = TOOL_CALL_TIMEOUT_SECONDS,
) -> ToolOutcome:
    """Invoke one tool, converting every failure into structured, actionable
    feedback for the model. Never raises for tool-side problems; GraphBubbleUp
    (interrupt()/Command routing) is the sole deliberate exception and is
    re-raised so the graph runtime handles it."""
    if tool_obj is None:
        return ToolOutcome("unknown_tool", f"[{tool_name}] Unknown tool.")

    if ledger is not None and ledger.exhausted(tool_name, args):
        return ToolOutcome(
            "gave_up",
            f"[{tool_name}] This exact call already failed "
            f"{MAX_REPEATED_FAILURES} times. Do not call it again with these "
            "arguments. Either call it differently, use another tool, or tell "
            "the user plainly that this step isn't working.",
        )

    try:
        result = await bounded_call(tool_obj.ainvoke(args), timeout, f"tool {tool_name}")
        return ToolOutcome("success", str(result))

    except GraphBubbleUp:
        # interrupt() / Command routing -- must reach the graph runtime.
        raise

    except TimeoutError:
        if ledger is not None:
            ledger.record_failure(tool_name, args)
        return ToolOutcome(
            "timeout",
            f"[{tool_name}] TIMED OUT after {timeout:.0f}s and was cancelled. "
            "It may be a transient outage. Either try a different approach or "
            "tell the user this lookup isn't responding right now.",
        )

    except VALIDATION_ERRORS as val_err:
        if ledger is not None:
            ledger.record_failure(tool_name, args)
        return ToolOutcome("invalid_args", _format_validation_error(tool_name, val_err, tool_obj))

    except Exception as exec_err:  # noqa: BLE001 - a tool fault must not kill the turn
        if ledger is not None:
            ledger.record_failure(tool_name, args)
        return ToolOutcome(
            "error",
            f"[{tool_name}] FAILED: {exec_err}\n"
            "Relay this honestly to the user if you cannot work around it.",
        )
