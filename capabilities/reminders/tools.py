import json
import re
from typing import Dict, Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from core.config import settings
from core.llm import ThinkingLevel, get_agent_llm


def _regex_parse_reminder(text: str, default_tz: str = "Asia/Singapore") -> Optional[Dict[str, Any]]:
    """Deterministic regex extraction for relative one-time and recurring reminder expressions."""
    lowered = text.lower().strip()

    # 1. Listing intent
    if any(
        p in lowered
        for p in [
            "list reminder",
            "show reminder",
            "my reminder",
            "view reminder",
            "get reminder",
            "all reminder",
            "/jobs",
        ]
    ):
        return {"action": "list", "timezone": default_tz, "reminder_type": "list"}

    # 2. Deletion intent
    del_match = re.search(r"(?:delete|remove|cancel)\s+(?:reminder|job|task)?\s*#?(\d+)", lowered)
    if del_match:
        return {
            "action": "delete",
            "job_id": int(del_match.group(1)),
            "timezone": default_tz,
            "reminder_type": "delete",
        }

    # 3. Relative time expressions (e.g. "in 1 minute", "in 5 mins", "in 2 hours", "in 30s")
    in_match = re.search(
        r"\bin\s+(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b",
        text,
        re.IGNORECASE,
    )
    if in_match:
        qty = int(in_match.group(1))
        unit = in_match.group(2).lower()
        mult = 1
        if unit.startswith("m"):
            mult = 60
        elif unit.startswith("h"):
            mult = 3600
        elif unit.startswith("d"):
            mult = 86400

        start_idx = in_match.start()
        end_idx = in_match.end()
        before_text = text[:start_idx].strip()
        after_text = text[end_idx:].strip()

        before_clean = re.sub(
            r"^(?:remind\s+(?:me\s+)?(?:to\s+|that\s+|about\s+|for\s+)?|set\s+(?:a\s+)?reminder\s+(?:to\s+|that\s+|about\s+|for\s+)?|ping\s+me\s+(?:to\s+)?)+",
            "",
            before_text,
            flags=re.IGNORECASE,
        ).strip()
        after_clean = re.sub(
            r"^(?:to\s+|that\s+|about\s+|for\s+)",
            "",
            after_text,
            flags=re.IGNORECASE,
        ).strip()

        msg = after_clean if after_clean else before_clean
        if not msg:
            msg = "Reminder"

        return {
            "action": "create",
            "reminder_type": "once",
            "delay_seconds": qty * mult,
            "message": msg,
            "timezone": default_tz,
            "cron": None,
            "job_id": None,
        }

    # 4. Common recurring keyword shortcuts
    if "every 2 hours" in lowered or "every 2 hrs" in lowered:
        msg = re.sub(
            r"^(?:remind\s+(?:me\s+)?(?:to\s+)?|set\s+(?:a\s+)?reminder\s+(?:to\s+)?)",
            "",
            text,
            flags=re.IGNORECASE,
        ).replace("every 2 hours", "").replace("every 2 hrs", "").strip()
        return {
            "action": "create",
            "reminder_type": "recurring",
            "cron": "0 */2 * * *",
            "message": msg or "Reminder",
            "timezone": default_tz,
            "job_id": None,
        }
    if "every 30 minutes" in lowered or "every 30 mins" in lowered:
        msg = re.sub(
            r"^(?:remind\s+(?:me\s+)?(?:to\s+)?|set\s+(?:a\s+)?reminder\s+(?:to\s+)?)",
            "",
            text,
            flags=re.IGNORECASE,
        ).replace("every 30 minutes", "").replace("every 30 mins", "").strip()
        return {
            "action": "create",
            "reminder_type": "recurring",
            "cron": "*/30 * * * *",
            "message": msg or "Reminder",
            "timezone": default_tz,
            "job_id": None,
        }

    return None


@tool
async def parse_reminder_request(user_text: str) -> Dict[str, Any]:
    """
    Parse a natural-language reminder request into an action, schedule, and message.
    Returns {"action": "create"|"list"|"delete", "reminder_type": "once"|"recurring",
             "delay_seconds": number|null, "message": string, "cron": string|null,
             "timezone": string, "job_id": number|null}.
    """
    # 1. Deterministic fast path
    regex_res = _regex_parse_reminder(user_text)
    if regex_res and (regex_res["action"] in ("list", "delete") or regex_res.get("delay_seconds")):
        return regex_res

    if not settings.has_llm_key:
        return regex_res or {"action": None}

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.1)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Parse a reminder/scheduling request. Reply with ONLY a JSON object:\n"
                        '{"action": "create"|"list"|"delete", '
                        '"reminder_type": "once"|"recurring", '
                        '"delay_seconds": number|null, '
                        '"message": string, '
                        '"cron": string|null, '
                        '"timezone": string, '
                        '"job_id": number|null}\n\n'
                        "Guidelines:\n"
                        "1. ONE-TIME / RELATIVE REMINDERS (e.g. 'remind me in 1 minute to check oven', 'in 10 mins call mom'):\n"
                        "   - set reminder_type to 'once'\n"
                        "   - set delay_seconds to the total seconds (e.g. 1 min -> 60, 5 mins -> 300, 2 hours -> 7200)\n"
                        "   - set cron to null\n"
                        "   - message is what to be reminded about (e.g. 'check oven', 'call mom')\n"
                        "2. RECURRING SCHEDULES (e.g. 'every 2 hours', 'daily at 9pm', 'every weekday 7am'):\n"
                        "   - set reminder_type to 'recurring'\n"
                        "   - set cron to 5-field cron string (e.g. '0 */2 * * *', '0 21 * * *', '0 7 * * 1-5')\n"
                        "   - set delay_seconds to null\n"
                        "3. LISTING: action = 'list'\n"
                        "4. DELETING (e.g. 'delete reminder 3'): action = 'delete', job_id = 3\n"
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
        return regex_res or {"action": None}

    try:
        parsed = json.loads(raw)
        action = parsed.get("action")
        if action not in ("create", "list", "delete"):
            return regex_res or {"action": None}
        return {
            "action": action,
            "reminder_type": parsed.get("reminder_type") or ("once" if parsed.get("delay_seconds") else "recurring"),
            "delay_seconds": parsed.get("delay_seconds"),
            "message": parsed.get("message") or "",
            "cron": parsed.get("cron") or "",
            "timezone": parsed.get("timezone") or "Asia/Singapore",
            "job_id": parsed.get("job_id"),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[REMINDERS] parse failed: {exc}")
        return regex_res or {"action": None}

