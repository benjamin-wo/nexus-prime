"""Plan execution adapter: runs a Decision through the plugin registry and emits Command."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import Command
from langgraph.graph import END

from capabilities.retrieval import RetrievalResult
from orchestrator.planner import Decision, decision_to_dict, deterministic_plan
from orchestrator.state import AssistantState


def _user_text(state: AssistantState) -> tuple[str, bool]:
    messages = state.get("messages", [])
    if not messages:
        return "", False
    last = messages[-1]
    if isinstance(last, AIMessage):
        return "", False
    content = getattr(last, "content", "")
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return " ".join(parts).strip(), True
    return str(content).strip(), True


def _primary(decision: Decision) -> str | None:
    return decision.ordering[0] if decision.ordering else None


def _intent_type(decision: Decision, primary: str | None) -> str:
    if decision.question:
        return "needs_clarification"
    if decision.insufficient and not decision.capabilities:
        return "unsupported_transaction"
    if primary == "general":
        return "informational_fallback"
    return "in_scope"


async def plan_dispatch(state: AssistantState) -> Command[str]:
    text, is_user = _user_text(state)
    if not is_user:
        return Command(goto=END)

    from capabilities.retrieval import build_index

    retrieval: RetrievalResult = build_index().retrieve_with_recovery(text, k=5)

    from capabilities.registry import load_registry
    from orchestrator.fastpath import should_take_fast_path
    from orchestrator.planner import plan_with_llm

    fast_path, skipped_stages = should_take_fast_path(text, load_registry(), retrieval)
    if fast_path:
        from orchestrator.planner import _candidate_selections, missing_policy

        lowered = text.lower()
        candidate = _candidate_selections(lowered, missing_policy(lowered))[0].id
        from orchestrator.router import CAPABILITY_REGISTRY

        output = await CAPABILITY_REGISTRY[candidate].execute(state)
        update: dict[str, Any] = {
            "messages": [output.message],
            "active_domain": candidate,
            "intent_type": "in_scope",
            "fast_path": True,
            "skipped_stages": skipped_stages,
        }
        if output.state_update:
            update.update(output.state_update)
        update["active_domain"] = candidate
        return Command(
            goto=END,
            update=update,
        )

    decision = await plan_with_llm(text, state, retrieval) or deterministic_plan(text, state, retrieval)

    if decision.question:
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=decision.question)],
                "active_domain": state.get("active_domain"),
                "intent_type": "needs_clarification",
                "last_decision": decision_to_dict(decision),
            },
        )

    from orchestrator.router import CAPABILITY_REGISTRY
    from orchestrator.insufficiency import (
        classify_insufficiency,
        insufficiency_message,
        record_gap,
    )

    # Pure refusal: no capability call happens. Insufficiency is the decision, not a fallback.
    if decision.insufficient and not decision.capabilities:
        await record_gap(state.get("user_id", 0), text, decision)
        kind = classify_insufficiency(decision.insufficient.missing_capabilities, text)
        refusal_text = insufficiency_message(kind, decision.insufficient.missing_capabilities)
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=refusal_text)],
                "active_domain": None,
                "intent_type": "unsupported_transaction",
                "missing_capability_tags": decision.insufficient.missing_capabilities,
                "last_decision": decision_to_dict(decision),
            },
        )

    if decision.recipe:
        from orchestrator.recipes import execute_recipe

        reply = await execute_recipe(decision.recipe, state, decision)
        primary = _primary(decision)
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=reply)],
                "active_domain": primary,
                "intent_type": "in_scope",
                "last_decision": decision_to_dict(decision),
                "recipe": decision.recipe,
            },
        )

    outputs: list[str] = []
    state_updates: list[dict[str, Any]] = []
    for cap_id in decision.ordering:
        plugin = CAPABILITY_REGISTRY.get(cap_id)
        if plugin is None:
            continue
        output = await plugin.execute(state)
        outputs.append(str(output.message.content))
        state_updates.append(output.state_update)

    reply_parts = outputs
    if decision.insufficient and decision.insufficient.message:
        reply_parts.append(decision.insufficient.message)
    reply = "\n\n".join(p for p in reply_parts if p)
    if not reply:
        reply = decision.insufficient.message or "I couldn't work out what to do with that."

    primary = _primary(decision)
    update: dict[str, Any] = {
        "messages": [AIMessage(content=reply)],
        "active_domain": primary,
        "intent_type": _intent_type(decision, primary),
        "last_decision": decision_to_dict(decision),
    }
    for state_update in state_updates:
        if state_update:
            update.update(state_update)
    update["active_domain"] = primary
    update["intent_type"] = _intent_type(decision, primary)
    if decision.insufficient:
        update["missing_capability_tags"] = decision.insufficient.missing_capabilities
        await record_gap(state.get("user_id", 0), text, decision)
    return Command(goto=END, update=update)
