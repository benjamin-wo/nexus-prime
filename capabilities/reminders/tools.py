import json
import re
from typing import Dict, Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from core.config import settings
from core.llm import ThinkingLevel, get_agent_llm


@tool
async def parse_reminder_request(user_text: str) -> Dict[str, Any]:
    """
    Parse a natural-language reminder request into an action and cron schedule.
    Returns {"action": "create"|"list"|"delete", "message", "cron", "timezone", "job_id"}.
    """
    if not settings.has_llm_key:
        return {"action": None}

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.1)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Parse a reminder/scheduling request. Reply with ONLY a JSON object: "
                        '{"action": "create"|"list"|"delete", "message": string, '
                        '"cron": 5-field cron string, "timezone": IANA name, "job_id": number|null}. '
                        "Convert natural schedules to 5-field cron: 'every 2 hours' -> '0 */2 * * *'; "
                        "'every 30 minutes' -> '*/30 * * * *'; 'daily at 9pm' -> '0 21 * * *'; "
                        "'every monday 8am' -> '0 8 * * 1'; 'every weekday 7am' -> '0 7 * * 1-5'. "
                        "For listing requests set action to 'list'. For deletion requests (e.g. "
                        "'delete reminder 3') set action to 'delete' and job_id to the number. "
                        "message is the reminder text itself (e.g. 'drink water'). "
                        "Default timezone: Asia/Singapore."
                    )
                ),
                HumanMessage(content=user_text[:2000]),
            ]
        )
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[REMINDERS] LLM call failed: {exc}")
        return {"action": None}
    try:
        parsed = json.loads(raw)
        action = parsed.get("action")
        if action not in ("create", "list", "delete"):
            return {"action": None}
        return {
            "action": action,
            "message": parsed.get("message") or "",
            "cron": parsed.get("cron") or "",
            "timezone": parsed.get("timezone") or "Asia/Singapore",
            "job_id": parsed.get("job_id"),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[REMINDERS] parse failed: {exc}")
        return {"action": None}
