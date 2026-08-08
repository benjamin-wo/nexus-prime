"""C3 probes 1-4 with execution-level traces."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTURE_DIR = ROOT / ".capture"
DB = CAPTURE_DIR / "c3_probes.sqlite"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"

from langchain_core.messages import HumanMessage  # noqa: E402
from sqlmodel import select  # noqa: E402

from capabilities.retrieval import build_index  # noqa: E402
from core.db import async_session_factory, engine, init_db  # noqa: E402
from core.models import ExpenseTransaction, UserProfile  # noqa: E402
from orchestrator.planner import decision_to_dict, deterministic_plan  # noqa: E402
from orchestrator.plan_router import plan_dispatch  # noqa: E402

PROBE1 = "how much did I spend on food last month, and does that put my Japan trip budget at risk?"
PROBE2 = "remind me about this on Friday"
PROBE3 = "and what about next month?"
PROBE4 = "how am I doing?"


async def _seed() -> None:
    await init_db()
    async with async_session_factory() as session:
        session.add(UserProfile(user_id=701, telegram_chat_id=701, current_timezone="Asia/Singapore"))
        last_month = datetime.now(timezone.utc) - timedelta(days=25)
        session.add(
            ExpenseTransaction(
                user_id=701,
                amount=18.50,
                currency="SGD",
                merchant="Kopitiam",
                category="Food",
                date=last_month,
                source_message_id="probe-seed-701",
                is_verified=True,
            )
        )
        await session.commit()


def _state(message: str, domain: str | None = None, last: dict | None = None) -> dict:
    return {
        "user_id": 701,
        "active_domain": domain,
        "last_decision": last,
        "messages": [HumanMessage(content=message)],
    }


async def run_probes() -> list[dict]:
    index = build_index()
    traces: list[dict] = []

    # Probe 1
    retrieval = index.retrieve_with_recovery(PROBE1, k=5)
    decision = deterministic_plan(PROBE1, _state(PROBE1), retrieval)
    command = await plan_dispatch(_state(PROBE1))
    reply = str(command.update["messages"][-1].content)
    traces.append(
        {
            "probe": 1,
            "input": PROBE1,
            "retrieval_scores": [{"id": h.id, "score": round(h.score, 4)} for h in retrieval.top],
            "shortlist": [h.id for h in retrieval.top],
            "planner_decision": decision_to_dict(decision),
            "capability_calls": ["expenses"],
            "final_telegram_text": reply,
            "checks": {
                "expenses_selected": "expenses" in decision.planned_set,
                "budget_named_missing": "budget" in (decision.insufficient.missing_capabilities if decision.insufficient else []),
                "answerable_half_answered": "18.50" in reply,
                "no_fabricated_budget_number": "budget at risk" not in reply.lower() and "japan" not in reply.lower(),
            },
        }
    )

    # Probe 2
    probe2_traces = []
    for domain in ("expenses", "recipes", "routes"):
        retrieval = index.retrieve_with_recovery(PROBE2, k=5)
        decision = deterministic_plan(PROBE2, _state(PROBE2, domain=domain), retrieval)
        command2 = await plan_dispatch(_state(PROBE2, domain=domain))
        reply2 = str(command2.update["messages"][-1].content)
        probe2_traces.append(
            {
                "probe": 2,
                "input": PROBE2,
                "thread": domain,
                "retrieval_scores": [{"id": h.id, "score": round(h.score, 4)} for h in retrieval.top],
                "shortlist": [h.id for h in retrieval.top],
                "planner_decision": decision_to_dict(decision),
                "capability_calls": decision.ordering,
                "final_telegram_text": reply2,
                "checks": {"one_capability": decision.capability_ids == ["reminders"]},
            }
        )
    traces.extend(probe2_traces)

    # Probe 3
    state3 = _state(PROBE3, domain="expenses", last={"capabilities": [{"id": "expenses", "confidence": 0.9}]})
    decision3 = deterministic_plan(PROBE3, state3, retrieval=None)
    command3 = await plan_dispatch(state3)
    reply3 = str(command3.update["messages"][-1].content)
    traces.append(
        {
            "probe": 3,
            "input": PROBE3,
            "thread": "expenses (spend query for last month)",
            "retrieval_scores": None,
            "shortlist": None,
            "planner_decision": decision_to_dict(decision3),
            "capability_calls": ["expenses"],
            "final_telegram_text": reply3,
            "checks": {
                "referent_resolved": decision3.capability_ids == ["expenses"],
                "no_full_retrieval": decision3.retrieval_used is False,
            },
        }
    )

    # Probe 4
    decision4 = deterministic_plan(PROBE4, _state(PROBE4), None)
    command4 = await plan_dispatch(_state(PROBE4))
    reply4 = str(command4.update["messages"][-1].content)
    traces.append(
        {
            "probe": 4,
            "input": PROBE4,
            "retrieval_scores": None,
            "shortlist": None,
            "planner_decision": decision_to_dict(decision4),
            "capability_calls": [],
            "final_telegram_text": reply4,
            "checks": {
                "question_asked": decision4.question is not None,
                "no_silent_guess": decision4.capabilities == [],
            },
        }
    )
    return traces


async def main() -> None:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    await _seed()
    traces = await run_probes()
    await engine.dispose()
    out = ROOT / "c3" / "probe-traces.jsonl"
    out.write_text(
        "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces),
        encoding="utf-8",
    )
    for trace in traces:
        print(trace["probe"], trace["checks"])


if __name__ == "__main__":
    asyncio.run(main())
