"""Counts each chat model call's tokens and cost, from the model's own reply.

``CostCallback`` is attached to every chat model the factory builds, so it fires for every
call however the model is used (plain, with tools, structured output, as a fallback) and
no call site changes. OpenRouter adds ``usage.cost`` (US dollars) to a reply when the
request asks for it (``"usage": {"include": true}``); other providers send tokens only,
which are counted with a cost of zero. A reply with no usage at all still counts as a call.
Input tokens the provider served from its prompt cache are counted too (a subset of the
input tokens, billed far lower). Only numbers are read: never the prompt or the reply.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from nexus.application import costs

log = logging.getLogger(costs.log.name)

# The keys providers use, in the order they are tried.
INPUT_KEYS = ("prompt_tokens", "input_tokens")
OUTPUT_KEYS = ("completion_tokens", "output_tokens")
COST_KEYS = ("cost", "total_cost")
_MAX_RUNS = 2000


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = Decimal(0)
    cached_tokens: int = 0  # part of input_tokens


def _first(source: dict[str, Any], keys: tuple[str, ...]) -> object:
    for key in keys:
        if source.get(key) is not None:
            return source[key]
    return None


def _cached(source: dict[str, Any]) -> object:
    """Cached input tokens: OpenRouter's ``prompt_tokens_details.cached_tokens``, or
    LangChain's ``input_token_details.cache_read``."""
    for key, name in (("prompt_tokens_details", "cached_tokens"),
                      ("input_token_details", "cache_read")):  # fmt: skip
        details = source.get(key)
        if isinstance(details, dict) and details.get(name) is not None:
            return details[name]
    return None


def _sources(result: LLMResult) -> list[dict[str, Any]]:
    """Every place a reply can carry its usage, the model-level total first."""
    found: list[Any] = []
    output = result.llm_output or {}
    found += [output.get("token_usage"), output.get("usage")]
    for generations in result.generations:
        for generation in generations:
            message = getattr(generation, "message", None)
            if message is None:
                continue
            metadata = getattr(message, "response_metadata", None) or {}
            found += [metadata.get("token_usage"), metadata.get("usage")]
            found.append(getattr(message, "usage_metadata", None))
    return [s for s in found if isinstance(s, dict) and s]


def usage_of(result: LLMResult) -> Usage:
    """Tokens and dollars from a reply; zero for whatever it doesn't say."""
    sources = _sources(result)
    inputs = outputs = cached = 0
    cost = Decimal(0)
    for source in sources:
        inputs = costs.to_count(_first(source, INPUT_KEYS))
        if inputs:
            break
    for source in sources:
        outputs = costs.to_count(_first(source, OUTPUT_KEYS))
        if outputs:
            break
    for source in sources:
        cost = costs.to_cost(_first(source, COST_KEYS))
        if cost:
            break
    for source in sources:
        cached = costs.to_count(_cached(source))
        if cached:
            break
    return Usage(inputs, outputs, cost, min(cached, inputs))


def _model_of(serialized: dict[str, Any] | None, params: dict[str, Any] | None) -> str | None:
    for source in (params or {}, (serialized or {}).get("kwargs") or {}):
        for key in ("model", "model_name"):
            if source.get(key):
                return str(source[key])
    return None


class CostCallback(BaseCallbackHandler):
    """Records a call's cost when it ends, under the feature and user in force then."""

    # Inline, in the caller's task: the context variables that name the feature and user are
    # the caller's, and recording is only a dictionary update.
    run_inline = True
    raise_error = False

    def __init__(self) -> None:
        self._models: dict[UUID, str] = {}

    def _started(
        self,
        serialized: dict[str, Any] | None,
        run_id: UUID,
        invocation_params: dict[str, Any] | None,
    ) -> None:
        if len(self._models) >= _MAX_RUNS:  # runs that never ended; don't grow forever
            self._models.clear()
        found = _model_of(serialized, invocation_params)
        if found:
            self._models[run_id] = found

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        invocation_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._started(serialized, run_id, invocation_params)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        invocation_params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._started(serialized, run_id, invocation_params)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        model = self._models.pop(run_id, None)
        try:
            model = model or str((response.llm_output or {}).get("model_name") or "")
            used = usage_of(response)
            costs.record(
                model or costs.UNKNOWN,
                input_tokens=used.input_tokens,
                output_tokens=used.output_tokens,
                cost=used.cost,
                cached_tokens=used.cached_tokens,
            )
        except Exception:  # counting a call must never break it
            log.debug("couldn't count a model call", exc_info=True)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._models.pop(run_id, None)


# One for the whole app: it keeps nothing but the model name of calls in flight.
COST_CALLBACK = CostCallback()
