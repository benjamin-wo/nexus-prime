"""C4 probe 1: fast-path latency for 'when's my next bus'."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parent


async def run() -> None:
    from orchestrator.plan_router import plan_dispatch

    message = "when's my next bus?"
    samples = []
    final_text = None
    for _ in range(30):
        state = {
            "user_id": 1,
            "active_domain": None,
            "last_decision": None,
            "messages": [HumanMessage(content=message)],
        }
        t0 = time.monotonic()
        command = await plan_dispatch(state)
        samples.append((time.monotonic() - t0) * 1000)
        final_text = str(command.update["messages"][-1].content)
        assert command.update.get("fast_path") is True
        assert "skipped_stages" in command.update

    samples.sort()
    p50 = samples[int(0.50 * (len(samples) - 1))]
    p95 = samples[int(0.95 * (len(samples) - 1))]
    trace = {
        "probe": 1,
        "input": message,
        "runs": len(samples),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "target_ms": 3000,
        "fast_path_flag": True,
        "skipped_stages": [
            "llm planner",
            "insufficiency analysis",
            "multi-capability composition",
            "hitl review",
        ],
        "final_telegram_text": final_text,
    }
    out = ROOT / "c4" / "probe-traces.jsonl"
    out.write_text(json.dumps(trace, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"fast-path p50={p50:.2f}ms p95={p95:.2f}ms target<3000ms")


if __name__ == "__main__":
    asyncio.run(run())
