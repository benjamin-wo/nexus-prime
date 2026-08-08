"""Fixed-shape capability recipes: coherent multi-tool orchestration.

Recipes call the underlying capability tools directly so the output is a
composed digest, not a concatenation of unrelated plugin replies. They stay
read-only unless the user explicitly asks for a write (e.g. a reminder), and
never fabricate data: missing API keys or failed calls produce honest notes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from capabilities.email.tools import search_email_messages
from capabilities.expenses.tools import get_user_expenses, log_expenses_from_emails
from capabilities.general.tools import search_web
from capabilities.recipes.tools import get_user_grocery_list
from capabilities.routes.tools import plan_route
from core.code_sandbox import SandboxConfig, get_sandbox
from core.scheduler import list_active_jobs

SPEND_AUTOPSY_CODE = """
from collections import Counter
import json
totals = {}
counts = Counter()
cats = Counter()
for row in data:
    merchant = row.get("merchant") or "Unknown"
    totals[merchant] = totals.get(merchant, 0) + float(row.get("amount", 0))
    counts[merchant] += 1
    cats[row.get("category") or "General"] += 1
print(json.dumps({
  "total": sum(totals.values()),
  "count": len(data),
  "top_merchants": sorted(totals.items(), key=lambda kv: -kv[1])[:5],
  "top_categories": sorted(cats.items(), key=lambda kv: -kv[1])[:5],
}))
"""


async def execute_recipe(
    recipe_id: str,
    state: dict[str, Any],
    decision: Any = None,
) -> str:
    text = ""
    messages = state.get("messages", [])
    if messages:
        content = getattr(messages[-1], "content", "")
        text = str(content) if isinstance(content, str) else ""
    if recipe_id == "briefing":
        return await _briefing(state)
    if recipe_id == "spend_autopsy":
        return await _spend_autopsy(state)
    if recipe_id == "grocery_run":
        return await _grocery_run(state, text)
    if recipe_id == "commute_conditions":
        return await _commute_conditions(state, text)
    if recipe_id == "bill_watch":
        return await _bill_watch(state)
    return "That recipe isn't built yet."


async def _briefing(state: dict[str, Any]) -> str:
    user_id = state.get("user_id", 0)
    parts: list[str] = []
    try:
        emails = await search_email_messages.ainvoke({"user_id": user_id})
        logged = await log_expenses_from_emails.ainvoke(
            {"user_id": user_id, "emails": emails}
        )
        logged_items = logged.get("logged") or []
        if logged_items:
            lines = [f"📧 Auto-logged {len(logged_items)} expense(s):"]
            for item in logged_items[:5]:
                lines.append(
                    f"• {item['currency']} {item['amount']:.2f} — {item['merchant']}"
                )
            parts.append("\n".join(lines))
        elif emails:
            parts.append(f"📬 {len(emails)} financial email(s) waiting — nothing new to log.")
        else:
            parts.append("📬 No new financial emails.")
    except Exception:  # noqa: BLE001
        parts.append("📬 Email scan unavailable right now.")

    try:
        jobs = await list_active_jobs(user_id=user_id)
        if jobs:
            lines = ["⏰ Reminders:"]
            for job in jobs[:5]:
                lines.append(
                    f"• {job['job_name']} (next: {job.get('next_run_time') or 'not scheduled'})"
                )
            parts.append("\n".join(lines))
        else:
            parts.append("⏰ No active reminders.")
    except Exception:  # noqa: BLE001
        parts.append("⏰ Reminders unavailable right now.")

    parts.append("💡 Ask me for expenses, bus times, or a route whenever you're ready.")
    return "\n\n".join(parts)


async def _spend_autopsy(state: dict[str, Any]) -> str:
    user_id = state.get("user_id", 0)
    rows = await get_user_expenses.ainvoke({"user_id": user_id, "limit": 500})
    if not rows:
        return "💰 No expenses logged yet — tell me what you spent or ask me to check your email."
    data = [
        {
            "amount": row["amount"],
            "merchant": row["merchant"],
            "category": row["category"],
            "date": row["date"],
        }
        for row in rows
    ]
    result = await get_sandbox().run_code(
        SPEND_AUTOPSY_CODE,
        data=data,
        config=SandboxConfig(timeout_seconds=15),
    )
    if not result.ok or not result.output:
        return (
            f"💰 Found {len(rows)} expenses, but the analysis sandbox failed "
            f"({result.error or 'no output'}). Nothing was fabricated."
        )
    try:
        stats = json.loads(result.output.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return "💰 Analysis ran but returned unreadable output."
    lines = [
        f"💰 Spend autopsy — {stats['count']} transactions, total {stats['total']:.2f}"
    ]
    lines.append("Top merchants:")
    for merchant, amount in stats["top_merchants"]:
        lines.append(f"• {merchant}: {amount:.2f}")
    lines.append("Top categories:")
    for category, count in stats["top_categories"]:
        lines.append(f"• {category}: {count}")
    return "\n".join(lines)


async def _grocery_run(state: dict[str, Any], text: str) -> str:
    user_id = state.get("user_id", 0)
    items = await get_user_grocery_list.ainvoke({"user_id": user_id})
    if not items:
        return "🛒 Your grocery list is empty. Paste a recipe or tell me what to add."
    lines = [f"🛒 Grocery list ({len(items)} items):"]
    for item in items[:15]:
        lines.append(f"• {item['name']} × {item['quantity']}")

    lowered = text.lower()
    origin = re.search(r"(?:from|at|near)\s+([a-z0-9 ,'-]+)", lowered)
    destination = re.search(r"(?:to)\s+([a-z0-9 ,'-]+)", lowered)
    if origin and destination:
        res = await plan_route.ainvoke(
            {
                "origin": origin.group(1).strip(" ,'-"),
                "destination": destination.group(1).strip(" ,'-"),
                "mode": "transit",
            }
        )
        if res.get("error") == "route_provider_not_configured":
            lines.append("🗺️ Route planning isn't configured (missing Google Maps key) — list is ready though.")
        elif res.get("error"):
            lines.append(f"🗺️ Couldn't plan the route ({res['error']}).")
        else:
            lines.append(
                f"🗺️ {res['origin']} → {res['destination']}: ~{res['eta_minutes']} min"
            )
    elif origin:
        lines.append(f"🗺️ I can route you from {origin.group(1).strip()} — say 'to <supermarket>'.")
    else:
        lines.append("🗺️ Say 'grocery run from <place> to <supermarket>' and I'll add the route.")
    if "remind" in lowered:
        lines.append("⏰ Reminder: say e.g. 'remind me to buy groceries tomorrow at 5pm' and I'll set it.")
    return "\n".join(lines)


async def _commute_conditions(state: dict[str, Any], text: str) -> str:
    parts: list[str] = []
    lowered = text.lower()
    origin = re.search(r"(?:from|at|near)\s+([a-z0-9 ,'-]+)", lowered)
    destination = re.search(r"(?:to)\s+([a-z0-9 ,'-]+)", lowered)
    if origin and destination:
        res = await plan_route.ainvoke(
            {
                "origin": origin.group(1).strip(" ,'-"),
                "destination": destination.group(1).strip(" ,'-"),
                "mode": "transit",
            }
        )
        if res.get("error") == "route_provider_not_configured":
            parts.append("🗺️ Route planning isn't configured (missing Google Maps key).")
        elif res.get("error"):
            parts.append(f"🗺️ Couldn't plan the route ({res['error']}).")
        else:
            parts.append(
                f"🚇 {res['origin']} → {res['destination']}: ~{res['eta_minutes']} min "
                f"({res['distance_km']} km)"
            )
    else:
        parts.append("🗺️ Tell me 'commute from <home> to <work>' and I'll get the ETA.")
    try:
        weather = await search_web.ainvoke({"query": "weather in Singapore today"})
        if weather and not weather.startswith("[search]"):
            parts.append("🌦️ " + weather.splitlines()[0])
        else:
            parts.append("🌦️ Weather unavailable right now (no web search key).")
    except Exception:  # noqa: BLE001
        parts.append("🌦️ Weather unavailable right now.")
    if "remind" in lowered:
        parts.append("⏰ Reminder: say e.g. 'remind me to leave at 7am' and I'll set it.")
    return "\n\n".join(parts)


async def _bill_watch(state: dict[str, Any]) -> str:
    user_id = state.get("user_id", 0)
    lines: list[str] = []
    try:
        emails = await search_email_messages.ainvoke(
            {
                "user_id": user_id,
                "custom_query": 'subject:(bill OR statement OR invoice OR "amount due") newer_than:14d',
            }
        )
        if emails:
            lines.append(f"📬 Bill-like emails in the last 14 days ({len(emails)}):")
            for email in emails[:8]:
                lines.append(
                    f"• {email.get('sender', '?')}: {email.get('subject', '(no subject)')}"
                )
        else:
            lines.append("📬 No bill-like emails found in the last 14 days.")
    except Exception:  # noqa: BLE001
        lines.append("📬 Email scan unavailable right now.")

    try:
        rows = await get_user_expenses.ainvoke({"user_id": user_id, "limit": 20})
        if rows:
            lines.append("💰 Recent payments:")
            for row in rows[:10]:
                lines.append(
                    f"• {row['date'][:10]} {row['amount']:.2f} — {row['merchant']}"
                )
        else:
            lines.append("💰 No recent expenses logged.")
    except Exception:  # noqa: BLE001
        lines.append("💰 Expenses unavailable right now.")

    try:
        jobs = await list_active_jobs(user_id=user_id)
        if jobs:
            lines.append("⏰ Payment reminders set: " + ", ".join(j["job_name"] for j in jobs[:5]))
        else:
            lines.append("⏰ No payment reminders set.")
    except Exception:  # noqa: BLE001
        lines.append("⏰ Reminders unavailable right now.")

    lines.append(
        "💡 Full bill↔payment matching and due-date reminders need a small addition: "
        "bill due-date extraction from email bodies."
    )
    return "\n".join(lines)
