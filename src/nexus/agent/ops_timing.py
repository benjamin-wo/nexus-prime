"""Times each model call in a chat turn and notes which model answered, for the
turn's ops events, and how long the turn spent building its context (the graph's
"kernel" step: the money snapshot and memories) and running tools. Only model names,
timings, token counts and error types: never the prompt or the reply."""

import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler
from langchain_core.outputs import LLMResult

from nexus.application import ops


def _model_of(serialized: dict[str, Any] | None, params: dict[str, Any] | None) -> str:
    for source in (params or {}, (serialized or {}).get("kwargs") or {}):
        for key in ("model", "model_name"):
            if source.get(key):
                return str(source[key])
    return str((serialized or {}).get("name") or "unknown")


# The graph steps whose time a turn reports, by the name the graph gives them.
_CONTEXT_NODE = "kernel"
_TOOLS_NODE = "tools"


class TurnTimer(AsyncCallbackHandler):
    """Collects a turn's model calls and records one "model" event for each."""

    def __init__(self, primary: str | None) -> None:
        self.primary = primary
        self.calls: list[dict[str, Any]] = []
        self.context_ms = 0
        self.tools_ms = 0
        self._started: dict[UUID, tuple[float, str]] = {}
        self._nodes: dict[UUID, tuple[float, str]] = {}

    async def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        node = (metadata or {}).get("langgraph_node")
        if node in (_CONTEXT_NODE, _TOOLS_NODE) and kwargs.get("name") == node:
            self._nodes[run_id] = (time.monotonic(), node)

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._node_done(run_id)

    async def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._node_done(run_id)

    def _node_done(self, run_id: UUID) -> None:
        started = self._nodes.pop(run_id, None)
        if started is None:
            return
        began, node = started
        ms = int((time.monotonic() - began) * 1000)
        if node == _CONTEXT_NODE:
            self.context_ms += ms
        else:
            self.tools_ms += ms

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        invocation_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._started[run_id] = (time.monotonic(), _model_of(serialized, invocation_params))

    async def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        self._done(run_id, None, _tokens(response))

    async def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._done(run_id, type(error).__name__, {})

    def _done(self, run_id: UUID, error: str | None, tokens: dict[str, int]) -> None:
        started = self._started.pop(run_id, None)
        if started is None:
            return
        began, model = started
        ms = (time.monotonic() - began) * 1000
        fallback = self.primary is not None and model != self.primary
        call = {"model": model, "ms": int(ms), "ok": error is None, "fallback": fallback}
        self.calls.append(call)
        ops.emit("model", model, ok=error is None, ms=ms, error=error, fallback=fallback, **tokens)

    @property
    def model_ms(self) -> int:
        return sum(c["ms"] for c in self.calls)

    @property
    def fell_back(self) -> bool:
        return any(c["fallback"] and c["ok"] for c in self.calls)

    @property
    def failures(self) -> int:
        return sum(not c["ok"] for c in self.calls)


def _tokens(response: LLMResult) -> dict[str, int]:
    usage = (response.llm_output or {}).get("token_usage") or {}
    found = {
        "tokens_in": usage.get("prompt_tokens"),
        "tokens_out": usage.get("completion_tokens"),
    }
    return {k: int(v) for k, v in found.items() if isinstance(v, int)}
