"""C5 probes with execution traces (scratch DB)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAPTURE_DIR = ROOT / ".capture"
DB = CAPTURE_DIR / "c5_probes.sqlite"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"

from langchain_core.messages import HumanMessage  # noqa: E402
from sqlmodel import SQLModel, select  # noqa: E402

from core.db import async_session_factory, engine, init_db  # noqa: E402
from core.models import CapabilityRequestLog  # noqa: E402
from orchestrator.insufficiency import insufficiency_message  # noqa: E402
from orchestrator.plan_router import plan_dispatch  # noqa: E402


def _state(message: str):
    return {"user_id": 702, "active_domain": None, "last_decision": None, "messages": [HumanMessage(content=message)]}


async def _latest_gap(user_id: int) -> CapabilityRequestLog | None:
    async with async_session_factory() as session:
        result = await session.execute(
            select(CapabilityRequestLog).where(CapabilityRequestLog.user_id == user_id).order_by(CapabilityRequestLog.id.desc()).limit(1)
        )
        return result.scalar_one_or_none()


async def main() -> None:
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    await init_db()
    traces = []
    for message, expected_kind in [
        ("book a table for two at 7", "no_integration"),
        ("transfer $100 to Alice", "needs_human"),
    ]:
        command = await plan_dispatch(_state(message))
        reply = str(command.update["messages"][-1].content)
        gap = await _latest_gap(702)
        traces.append(
            {
                "probe": 1,
                "input": message,
                "planner_decision": {
                    "capabilities": [],
                    "insufficient": list(command.update.get("missing_capability_tags") or []),
                },
                "capability_calls_made": [],
                "final_telegram_text": reply,
                "gap_record": {"id": gap.id, "intent_type": gap.intent_type, "tags": gap.missing_capability_tags} if gap else None,
                "expected_kind": expected_kind,
                "kind_message": insufficiency_message(expected_kind, command.update.get("missing_capability_tags") or []),
                "checks": {
                    "starts_with_i_cant": reply.startswith("I can't"),
                    "no_fake_confirmation": ("done" not in reply.lower()) and ("saved" not in reply.lower()),
                    "gap_record_written": gap is not None,
                },
            }
        )
    out = ROOT / "c5" / "probe-traces.jsonl"
    out.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces), encoding="utf-8")
    for t in traces:
        print(t["input"], t["checks"])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
