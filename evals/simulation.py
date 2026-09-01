from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, List, Optional, Sequence, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from core.config import settings
from core.llm import ThinkingLevel, extract_llm_text, get_agent_llm
from evals.config import EvalConfig
from evals.metrics import compute_metrics, detect_tool_names
from evals.scenarios import Scenario
from evals.transcript import Conversation, Turn

BotFn = Callable[[List[BaseMessage], EvalConfig], Awaitable[Tuple[str, Sequence[Any], float]]]

_PERSONA_DONE = "[[DONE]]"


@dataclass
class SimulationResult:
    scenario_id: str
    status: str
    metrics: Dict[str, Any]
    turns: List[Tuple[str, str]] = field(default_factory=list)
    conversation: Optional[Conversation] = None
    error: Optional[str] = None


async def bot_reply(messages: List[BaseMessage], cfg: EvalConfig) -> Tuple[str, Sequence[Any], float]:
    """Run one bot turn through the real LangGraph agent loop."""
    from orchestrator.agent_loop import agent_loop

    start = time.monotonic()
    result = await asyncio.wait_for(
        agent_loop(
            {
                "user_id": cfg.user_id,
                "current_timezone": cfg.timezone,
                "messages": messages,
            }
        ),
        timeout=cfg.per_turn_timeout,
    )
    elapsed = time.monotonic() - start
    update = getattr(result, "update", None) or {}
    out_messages = update.get("messages", []) or []
    text = ""
    for message in reversed(out_messages):
        if isinstance(message, AIMessage):
            text = extract_llm_text(message.content).strip()
            break
    return text, out_messages, elapsed


def _persona_prompt(scenario: Scenario, history: Sequence[Tuple[str, str]]) -> str:
    lines = [scenario.persona or "", "", "Conversation so far:"]
    for role, text in history:
        prefix = "USER" if role == "user" else "ASSISTANT"
        lines.append(f"{prefix}: {text}")
    lines.extend(
        [
            "",
            "Now reply with ONLY your next message as the user, short and natural.",
            f"When the goal is fully achieved, reply with exactly: {_PERSONA_DONE}",
        ]
    )
    return "\n".join(lines)


async def _next_persona_turn(persona_llm: Any, scenario: Scenario, history: Sequence[Tuple[str, str]]) -> str:
    response = await persona_llm.ainvoke(
        [SystemMessage(content="You are simulating a real user for a bot evaluation."),
         HumanMessage(content=_persona_prompt(scenario, history))]
    )
    return extract_llm_text(getattr(response, "content", "")).strip()


async def run_scripted(scenario: Scenario, cfg: EvalConfig, bot: Optional[BotFn] = None) -> SimulationResult:
    bot_fn = bot or bot_reply
    history: List[BaseMessage] = []
    bot_texts: List[str] = []
    tools_per_turn: List[set] = []
    latencies: List[float] = []
    turns: List[Tuple[str, str]] = []
    try:
        for user_text in scenario.user_turns:
            history.append(HumanMessage(content=user_text))
            text, out_messages, elapsed = await bot_fn(history, cfg)
            bot_texts.append(text)
            tools_per_turn.append(detect_tool_names(out_messages))
            latencies.append(elapsed)
            turns.append((user_text, text))
            history.append(AIMessage(content=text))
        metrics = compute_metrics(scenario, bot_texts, tools_per_turn, latencies)
        status = "passed" if metrics["goal_completed"] else "failed"
        conversation = Conversation(
            id=f"sim-{scenario.id}",
            scenario_id=scenario.id,
            turns=[Turn(role="user", text=u) for u, _ in turns]
            + [Turn(role="assistant", text=b) for _, b in turns],
            meta={"metrics": metrics, "status": status},
        )
        return SimulationResult(
            scenario_id=scenario.id,
            status=status,
            metrics=metrics,
            turns=turns,
            conversation=conversation,
        )
    except Exception as exc:  # noqa: BLE001 - a broken turn must not kill the whole run
        return SimulationResult(
            scenario_id=scenario.id,
            status="error",
            metrics={"turns": len(turns), "goal_completed": False},
            turns=turns,
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_persona(scenario: Scenario, cfg: EvalConfig, persona_llm: Any, bot: Optional[BotFn] = None) -> SimulationResult:
    bot_fn = bot or bot_reply
    history: List[BaseMessage] = []
    turns: List[Tuple[str, str]] = []
    bot_texts: List[str] = []
    tools_per_turn: List[set] = []
    latencies: List[float] = []
    goal_completed = False
    try:
        for _ in range(min(scenario.max_turns, cfg.max_turns)):
            persona_text = await _next_persona_turn(persona_llm, scenario, turns)
            if _PERSONA_DONE in persona_text:
                goal_completed = True
                break
            history.append(HumanMessage(content=persona_text))
            text, out_messages, elapsed = await bot_fn(history, cfg)
            bot_texts.append(text)
            tools_per_turn.append(detect_tool_names(out_messages))
            latencies.append(elapsed)
            turns.append((persona_text, text))
            history.append(AIMessage(content=text))
        metrics = compute_metrics(scenario, bot_texts, tools_per_turn, latencies)
        metrics["goal_completed"] = goal_completed and metrics["goal_completed"] and len(turns) > 0
        metrics["persona_done"] = goal_completed
        return SimulationResult(
            scenario_id=scenario.id,
            status="passed" if metrics["goal_completed"] else "failed",
            metrics=metrics,
            turns=turns,
            conversation=Conversation(
                id=f"sim-{scenario.id}",
                scenario_id=scenario.id,
                turns=[Turn(role="user", text=u) for u, _ in turns]
                + [Turn(role="assistant", text=b) for _, b in turns],
                meta={"metrics": metrics, "status": "passed" if metrics["goal_completed"] else "failed"},
            ),
        )
    except Exception as exc:  # noqa: BLE001
        return SimulationResult(
            scenario_id=scenario.id,
            status="error",
            metrics={"turns": len(turns), "goal_completed": False},
            turns=turns,
            error=f"{type(exc).__name__}: {exc}",
        )


def build_persona_llm(model: str):
    return get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.7, model=model)


async def run_scenarios(
    scenarios: Sequence[Scenario],
    cfg: EvalConfig,
    bot: Optional[BotFn] = None,
) -> List[SimulationResult]:
    persona_llm = build_persona_llm(cfg.persona_model) if (cfg.persona_llm and settings.has_llm_key) else None
    results: List[SimulationResult] = []
    for scenario in scenarios:
        if scenario.is_persona:
            if persona_llm is None:
                results.append(
                    SimulationResult(
                        scenario_id=scenario.id,
                        status="error",
                        metrics={"turns": 0, "goal_completed": False},
                        error="persona scenario requires --persona-llm and a configured LLM key",
                    )
                )
                continue
            results.append(await run_persona(scenario, cfg, persona_llm, bot=bot))
        else:
            results.append(await run_scripted(scenario, cfg, bot=bot))
    return results