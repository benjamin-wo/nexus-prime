"""C8 probe traces."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.ambient import should_deliver

ROOT = Path(__file__).resolve().parent


def _sgt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 8, hour, minute, tzinfo=ZoneInfo("Asia/Singapore"))


def main() -> None:
    scenarios = [
        {
            "probe": 1,
            "trigger": {"kind": "expense_mismatch", "trigger_id": "t-1", "amount_diff": 4.0},
            "local_time": "02:40 SGT",
            "expect": False,
        },
        {
            "probe": 2,
            "trigger": {"kind": "expense_mismatch", "trigger_id": "t-2", "amount_diff": 500.0},
            "local_time": "02:40 SGT",
            "expect": True,
        },
        {
            "probe": "2b",
            "trigger": {"kind": "scheduled_job", "trigger_id": "t-3", "message": "URGENT security alert from your bank"},
            "local_time": "02:40 SGT",
            "expect": True,
        },
        {
            "probe": 3,
            "trigger": None,
            "local_time": "14:00 SGT",
            "expect": False,
        },
        {
            "probe": 4,
            "trigger": {"kind": "expense_mismatch", "trigger_id": "t-4", "amount_diff": 4.0},
            "local_time": "10:00 SGT",
            "expect": True,
        },
    ]
    traces = []
    for scenario in scenarios:
        hh, mm = scenario["local_time"].split(" ")[0].split(":")
        deliver, reason = should_deliver(
            scenario["trigger"], _sgt(int(hh), int(mm)), "Asia/Singapore"
        )
        traces.append(
            {
                "probe": scenario["probe"],
                "trigger": scenario["trigger"],
                "local_time": scenario["local_time"],
                "deliver": deliver,
                "reason": reason,
                "checks": {"expected": scenario["expect"], "matches": deliver == scenario["expect"]},
            }
        )
    out = ROOT / "c8" / "probe-traces.jsonl"
    out.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in traces), encoding="utf-8")
    for t in traces:
        print(t["probe"], t["deliver"], t["reason"], t["checks"])


if __name__ == "__main__":
    main()
