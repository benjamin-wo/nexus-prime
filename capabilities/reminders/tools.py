import json
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from core.config import settings
from core.llm import ThinkingLevel, get_agent_llm, extract_llm_text
from core.tool_guard import identity_bound

# A request must contain explicit repetition language before an eternal cron job may be created.
_RECURRENCE_RE = re.compile(
    r"\b(every\s+\w+|each\s+\w+|daily|weekly|monthly|yearly|nightly|weekdays?|weekends?|"
    r"mornings?|evenings?|afternoons?|annually)\b",
    re.IGNORECASE,
)

_AT_TIME_RE = re.compile(
    r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b|\b(\d{1,2}):(\d{2})\b",
    re.IGNORECASE,
)


def has_recurrence_keyword(text: str) -> bool:
    """True only when the user explicitly asked for repetition (every/daily/weekdays...)."""
    return bool(_RECURRENCE_RE.search(text or ""))


def next_occurrence_delay_seconds(text: str, tz_str: str = "Asia/Singapore") -> Optional[int]:
    """Seconds until the next occurrence of a wall-clock time in the text ('at 9am', 'at 10:31')."""
    try:
        tz = ZoneInfo(tz_str)
    except Exception:
        tz = ZoneInfo("Asia/Singapore")
    now = datetime.now(tz)
    for m in _AT_TIME_RE.finditer(text or ""):
        if m.group(1):
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            meridiem = re.sub(r"\.", "", (m.group(3) or "")).lower()
        else:
            hour = int(m.group(4))
            minute = int(m.group(5))
            meridiem = ""
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return max(int((candidate - now).total_seconds()), 60)
    return None


def _downgrade_ghost_recurring(parsed: Dict[str, Any], user_text: str) -> Dict[str, Any]:
    """Guard against ghost jobs: an LLM 'recurring' verdict without explicit repetition
    language must never become an eternal daily cron. Downgrade to a one-shot at the
    mentioned wall-clock time, or drop the action entirely."""
    tz_name = parsed.get("timezone") or "Asia/Singapore"
    delay = next_occurrence_delay_seconds(user_text, tz_name)
    if delay is None:
        return {"action": None}
    return {
        "action": "create",
        "reminder_type": "once",
        "delay_seconds": delay,
        "message": parsed.get("message") or "",
        "cron": None,
        "timezone": tz_name,
        "job_id": None,
    }


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

    # 3. Relative time expressions (e.g. "in 1 minute", "in one minute", "in 5 mins", "in 2 hours", "in 30s")
    _WORD_TO_NUM = {
        "a": 1,
        "an": 1,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "fifteen": 15,
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
    }
    in_match = re.search(
        r"\bin\s+(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty|forty|fifty|sixty)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)\b",
        text,
        re.IGNORECASE,
    )
    if in_match:
        raw_qty = in_match.group(1).lower()
        qty = int(raw_qty) if raw_qty.isdigit() else _WORD_TO_NUM.get(raw_qty, 1)
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
            r"^(?:(?:can|could|please|will|would)?\s*(?:you\s+)?(?:remind\s+(?:me\s+)?(?:to\s+|that\s+|about\s+|for\s+)?|set\s+(?:a\s+)?reminder\s+(?:to\s+|that\s+|about\s+|for\s+)?|ping\s+me\s+(?:to\s+)?))+",
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
async def parse_reminder_request(user_text: str, recent_context: str = "") -> Dict[str, Any]:
    """
    Parse a natural-language reminder request into an action, schedule, and message.
    Returns {"action": "create"|"list"|"delete", "reminder_type": "once"|"recurring",
             "delay_seconds": number|null, "message": string, "cron": string|null,
             "timezone": string, "job_id": number|null}.

    recent_context (#35): the last few conversation turns, so a follow-up
    correction ("actually make that every day instead") can be resolved
    against the reminder just discussed. Only reaches the LLM path — the
    deterministic regex fast path above is untouched.
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
                        "   - ONLY use this when the request contains explicit repetition words (every, daily, each day, weekdays, weekly).\n"
                        "   - set reminder_type to 'recurring'\n"
                        "   - set cron to 5-field cron string (e.g. '0 */2 * * *', '0 21 * * *', '0 7 * * 1-5')\n"
                        "   - set delay_seconds to null\n"
                        "   - NEVER invent a recurring schedule for a one-time request like 'remind me at 10am to text X' — that must be 'once'\n"
                        "3. LISTING: action = 'list'\n"
                        "4. DELETING (e.g. 'delete reminder 3'): action = 'delete', job_id = 3\n"
                        "Default timezone: Asia/Singapore.\n"
                        "If recent conversation is provided, use it ONLY to resolve a correction or "
                        "continuation of a reminder already being set up (e.g. 'actually every day') — "
                        "the current message is always the request to parse; never invent a reminder "
                        "from unrelated earlier conversation."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Recent conversation:\n{recent_context}\n\n---\n\n{user_text[:2000]}"
                        if recent_context
                        else user_text[:2000]
                    )
                ),
            ]
        )
        raw = extract_llm_text(getattr(ai_message, "content", "")).strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[REMINDERS] LLM call failed: {exc}")
        return regex_res or {"action": None}

    try:
        parsed = json.loads(raw)
        action = parsed.get("action")
        if action not in ("create", "list", "delete"):
            return regex_res or {"action": None}
        result = {
            "action": action,
            "reminder_type": parsed.get("reminder_type") or ("once" if parsed.get("delay_seconds") else "recurring"),
            "delay_seconds": parsed.get("delay_seconds"),
            "message": parsed.get("message") or "",
            "cron": parsed.get("cron") or "",
            "timezone": parsed.get("timezone") or "Asia/Singapore",
            "job_id": parsed.get("job_id"),
        }
        if (
            action == "create"
            and result["reminder_type"] == "recurring"
            and not has_recurrence_keyword(user_text)
        ):
            return _downgrade_ghost_recurring(result, user_text)
        return result
    except Exception as exc:  # noqa: BLE001
        print(f"[REMINDERS] parse failed: {exc}")
        return regex_res or {"action": None}


# --- Agent-callable scheduling tools ----------------------------------------
# parse_reminder_request above stays available as an optional deterministic
# time-parsing assist, but the agent decides create/list/delete itself now --
# these are the actual write actions, each independently agent-callable.
# list is covered by capabilities/general/tools.py's list_my_reminders.


def _format_delay(delay_seconds: int) -> str:
    if delay_seconds < 60:
        return f"{delay_seconds}s"
    if delay_seconds < 3600:
        mins = delay_seconds // 60
        return f"{mins} minute{'s' if mins != 1 else ''}"
    if delay_seconds < 86400:
        hrs = delay_seconds // 3600
        return f"{hrs} hour{'s' if hrs != 1 else ''}"
    days = delay_seconds // 86400
    return f"{days} day{'s' if days != 1 else ''}"


@tool
@identity_bound
async def create_one_time_reminder(
    message: str, delay_seconds: int, timezone: str = "Asia/Singapore", user_id: int = 0
) -> str:
    """
    Set a one-time reminder that fires once, after a relative delay from now
    (e.g. "remind me in 5 minutes to check the oven", "in 2 hours call mom").
    Compute delay_seconds yourself from the user's phrasing. For a repeating
    schedule (every/daily/weekly), use create_recurring_reminder instead.

    Args:
        message: what to remind the user about.
        delay_seconds: seconds from now to fire, e.g. 300 for "5 minutes".
        timezone: IANA timezone for display, default "Asia/Singapore".
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    from datetime import datetime as _dt, timedelta as _td
    import zoneinfo

    from core.scheduler import schedule_one_shot_reminder

    try:
        tz = zoneinfo.ZoneInfo(timezone)
    except Exception:  # noqa: BLE001
        tz = zoneinfo.ZoneInfo("Asia/Singapore")
        timezone = "Asia/Singapore"

    delay = max(1, int(delay_seconds or 60))
    run_time = _dt.now(tz) + _td(seconds=delay)
    try:
        task = await schedule_one_shot_reminder(
            user_id=int(user_id or 0),
            message=(message or "Reminder").strip(),
            run_date=run_time,
            timezone_str=timezone,
        )
    except Exception as exc:  # noqa: BLE001
        return f"[reminders] Couldn't schedule that: {exc}"
    time_str = run_time.strftime("%I:%M %p").lstrip("0")
    return (
        f'Reminder set (#{task.id}): "{message}". '
        f"I'll ping you in {_format_delay(delay)} (at {time_str})."
    )


@tool
@identity_bound
async def create_recurring_reminder(
    message: str, cron_expression: str, timezone: str = "Asia/Singapore", user_id: int = 0
) -> str:
    """
    Set a recurring reminder on a cron schedule (e.g. "remind me to drink
    water every 2 hours", "daily standup reminder at 9am weekdays"). Only use
    this when the user explicitly asked for repetition -- a one-off request
    belongs in create_one_time_reminder instead.

    Args:
        message: what to remind the user about, repeated at each firing.
        cron_expression: standard 5-field cron, e.g. "0 */2 * * *" for every
            2 hours, "0 9 * * 1-5" for 9am weekdays.
        timezone: IANA timezone the cron is evaluated in, default "Asia/Singapore".
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    from core.scheduler import schedule_proactive_task, scheduler as _aps_scheduler

    message = (message or "Reminder").strip()
    try:
        job = await schedule_proactive_task(
            user_id=int(user_id or 0),
            job_name=message[:50],
            cron_expression=cron_expression,
            instruction_prompt=message,
            timezone_str=timezone,
        )
    except Exception as exc:  # noqa: BLE001
        return (
            f'[reminders] Couldn\'t parse "{cron_expression}" as a schedule -- '
            f"try something like \"every 2 hours\" or \"daily at 9pm\" ({exc})."
        )
    aps_job = _aps_scheduler.get_job(str(job.id))
    next_run_time = getattr(aps_job, "next_run_time", None)
    next_run = next_run_time.strftime("%a, %b %d at %I:%M %p") if next_run_time else "soon"
    return (
        f'Recurring reminder set (#{job.id}): "{message}". '
        f"Schedule: {cron_expression} ({timezone}). Next run: {next_run}."
    )


@tool
@identity_bound
async def delete_reminder(job_id: int, user_id: int = 0) -> str:
    """
    Delete/cancel an existing reminder or scheduled job by its ID (from
    list_my_reminders). Only deletes reminders owned by the requesting user.

    Args:
        job_id: the reminder/job ID to delete.
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    from core.scheduler import delete_scheduled_job

    deleted = await delete_scheduled_job(int(job_id), int(user_id or 0))
    return f"Reminder #{job_id} deleted." if deleted else f"[reminders] No reminder #{job_id} found."

