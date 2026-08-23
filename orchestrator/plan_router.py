"""Plan execution adapter: runs a Decision through the plugin registry and emits Command."""

from __future__ import annotations

import json
import asyncio
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from langgraph.graph import END

from capabilities.retrieval import RetrievalResult
from core.config import settings
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


def _log_plan(decision: Decision) -> None:
    print(f"[PLANNER] plan={json.dumps(decision_to_dict(decision), ensure_ascii=False)}")


async def _execute_capabilities(
    decision: Decision,
    state: AssistantState,
) -> tuple[list[str], list[dict[str, Any]], str]:
    from orchestrator.router import CAPABILITY_REGISTRY

    outputs: list[str] = []
    state_updates: list[dict[str, Any]] = []
    for cap_id in decision.ordering:
        plugin = CAPABILITY_REGISTRY.get(cap_id)
        if plugin is None:
            continue
        output = await plugin.execute(state)
        outputs.append(str(output.message.content))
        state_updates.append(output.state_update)
    reply_parts = list(outputs)
    if decision.insufficient and decision.insufficient.message:
        reply_parts.append(decision.insufficient.message)
    reply = "\n\n".join(part for part in reply_parts if part)
    if not reply:
        reply = decision.insufficient.message or "I couldn't work out what to do with that."
    return outputs, state_updates, reply


_PLANNING_SIGNALS = (
    "trip", "travel", "flight", "villa", "hotel", "airbnb", "stay", "booked", "booking",
    "itinerary", "lunch", "dinner", "breakfast", "brunch", "restaurant", "eat",
    "club", "beach", "party", "bachelor", "activity", "tour", "gym", "fitness",
    "yoga", "spa", "reservation", "check in", "check-in", "pack", "headcount",
    "friday", "saturday", "sunday", "monday",
)


def _has_planning_signal(text: str) -> bool:
    lowered = (text or "").lower()
    return any(signal in lowered for signal in _PLANNING_SIGNALS)


async def plan_dispatch(state: AssistantState) -> Command[str]:
    text, is_user = _user_text(state)
    if not is_user:
        return Command(goto=END)

    from core.audit import perform_conversation_audit, should_audit_conversation

    user_message_count = sum(
        1
        for message in state.get("messages", [])
        if getattr(message, "type", "") == "human"
    )
    audit_due = should_audit_conversation(user_message_count)

    def schedule_turn_audit(reply_text: str) -> None:
        """Audit the completed turn, not the previous tail of a long thread."""
        if not audit_due:
            return
        asyncio.create_task(
            perform_conversation_audit(
                user_id=state.get("user_id", 0),
                thread_id=str(state.get("user_id", 0)),
                messages=[
                    HumanMessage(content=text),
                    AIMessage(content=reply_text),
                ],
            )
        )

    from capabilities.registry import load_registry
    from capabilities.retrieval import build_index
    from orchestrator.fastpath import should_take_fast_path
    from orchestrator.insufficiency import (
        classify_insufficiency,
        insufficiency_message,
        record_gap,
    )
    from orchestrator.planner import plan_with_llm
    from capabilities.expenses.tools import parse_incoming_transaction_text

    user_id = state.get("user_id")
    is_admin = settings.is_admin(user_id)
    retrieval: RetrievalResult = build_index(is_admin=is_admin).retrieve_with_recovery(text, k=5)

    fast_path, skipped_stages = should_take_fast_path(text, load_registry(is_admin=is_admin), retrieval)
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
        schedule_turn_audit(str(output.message.content))
        return Command(goto=END, update=update)

    from orchestrator.planner import (
        CapabilitySelection,
        is_email_connection_request,
        is_email_disconnect_request,
    )

    if parse_incoming_transaction_text(text) is not None:
        # Incoming-money messages are deterministic finance writes. Keep them
        # out of the generic LLM planning path so they cannot be mislabeled as
        # an unsupported capability such as #income_tracking.
        from orchestrator.planner import CapabilitySelection

        decision = Decision(
            capabilities=[
                CapabilitySelection(
                    id="expenses",
                    reason="incoming-money transaction logging",
                    confidence=0.98,
                )
            ],
            ordering=["expenses"],
            confidence=0.98,
            source="deterministic-income",
            retrieval_used=False,
            rationale="Explicit incoming-money language and amount matched the finance parser.",
        )
    elif is_email_connection_request(text) or is_email_disconnect_request(text):
        # Mailbox onboarding and revocation are email capability operations,
        # not missing account-linking capabilities.
        decision = Decision(
            capabilities=[
                CapabilitySelection(id="email", reason="email provider access request", confidence=0.98)
            ],
            ordering=["email"],
            confidence=0.98,
            source="deterministic-email-connect",
            retrieval_used=False,
            rationale="Mailbox connection requests are handled by EmailPlugin OAuth onboarding.",
        )
    else:
        decision = await plan_with_llm(text, state, retrieval) or deterministic_plan(text, state, retrieval)

    # Active planning threads stay on the board: when both planner paths resolve
    # to plain chat but the conversation is an ongoing plan, route to the
    # whiteboard intake so follow-ups mutate the board instead of dissolving.
    from orchestrator.planner import in_planning_thread

    if (
        [c.id for c in decision.capabilities] == ["general"]
        and in_planning_thread(state, text)
        and _has_planning_signal(text)
    ):
        from orchestrator.planner import CapabilitySelection

        decision = Decision(
            capabilities=[
                CapabilitySelection(id="whiteboard", reason="planning follow-up in active board thread", confidence=0.85)
            ],
            ordering=["whiteboard"],
            confidence=0.85,
            source=decision.source,
            retrieval_used=decision.retrieval_used,
            rationale="Planning-signal follow-up while a whiteboard thread is active; overriding general fallback.",
        )
        _log_plan(decision)
    _log_plan(decision)

    if decision.question:
        schedule_turn_audit(decision.question)
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=decision.question)],
                "active_domain": state.get("active_domain"),
                "intent_type": "needs_clarification",
                "last_decision": decision_to_dict(decision),
                "plan": decision_to_dict(decision),
            },
        )

    if decision.insufficient and not decision.capabilities:
        await record_gap(state.get("user_id", 0), text, decision)
        kind = classify_insufficiency(decision.insufficient.missing_capabilities, text)
        refusal_text = insufficiency_message(kind, decision.insufficient.missing_capabilities)
        schedule_turn_audit(refusal_text)
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=refusal_text)],
                "active_domain": None,
                "intent_type": "unsupported_transaction",
                "missing_capability_tags": decision.insufficient.missing_capabilities,
                "last_decision": decision_to_dict(decision),
                "plan": decision_to_dict(decision),
            },
        )

    if decision.recipe:
        from orchestrator.recipes import execute_recipe

        reply = await execute_recipe(decision.recipe, state, decision)
        primary = _primary(decision)
        schedule_turn_audit(reply)
        return Command(
            goto=END,
            update={
                "messages": [AIMessage(content=reply)],
                "active_domain": primary,
                "intent_type": "in_scope",
                "last_decision": decision_to_dict(decision),
                "plan": decision_to_dict(decision),
                "recipe": decision.recipe,
            },
        )

    from orchestrator.verify import verify_deterministic, verify_with_llm

    outputs, state_updates, reply = await _execute_capabilities(decision, state)
    verify = (
        await verify_with_llm(decision, text, reply, "\n".join(outputs)[:1200], state)
        or verify_deterministic(decision, reply, text)
    )

    if verify.needs_replan:
        print(f"[PLANNER] verify 1: {verify.reason} -> re-planning")
        feedback = verify.missing or verify.reason or "reply did not fulfil the request"
        state_with_feedback = dict(state)
        state_with_feedback["verification_feedback"] = feedback
        decision = (
            await plan_with_llm(text, state_with_feedback, retrieval)
            or deterministic_plan(text, state_with_feedback, retrieval)
        )
        _log_plan(decision)
        outputs, state_updates, reply = await _execute_capabilities(decision, state)
        verify = (
            await verify_with_llm(
                decision, text, reply, "\n".join(outputs)[:1200], state_with_feedback
            )
            or verify_deterministic(decision, reply, text)
        )
        if verify.needs_replan:
            print(
                f"[PLANNER] verify: bounded retry exhausted; sending best reply ({verify.reason})"
            )

    primary = _primary(decision)
    update: dict[str, Any] = {
        "messages": [AIMessage(content=reply)],
        "active_domain": primary,
        "intent_type": _intent_type(decision, primary),
        "last_decision": decision_to_dict(decision),
        "plan": decision_to_dict(decision),
    }
    for state_update in state_updates:
        if state_update:
            update.update(state_update)
    update["active_domain"] = primary
    update["intent_type"] = _intent_type(decision, primary)
    if decision.insufficient:
        update["missing_capability_tags"] = decision.insufficient.missing_capabilities
        await record_gap(state.get("user_id", 0), text, decision)
    schedule_turn_audit(reply)
    return Command(goto=END, update=update)
