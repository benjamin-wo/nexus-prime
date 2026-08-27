"""Bug logging: user-reported bugs flow into the production-bug pipeline."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict

from langchain_core.tools import tool

from core.tool_guard import identity_bound


def _extract_bug_description(text: str) -> str:
    """Strip bug-report framing so the issue body is the actual problem."""
    cleaned = re.sub(
        r"^\s*(?:please\s+)?(?:can you\s+|could you\s+|kindly\s+)?"
        r"(?:log|file|report|record)\s+(?:it|this|that)?\s*(?:as\s+)?(?:a\s+)?"
        r"(?:bug|issue|problem)\b[\.!]?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = re.sub(r"^:\s*", "", cleaned).strip()
    cleaned = re.sub(
        r"\s*(?:please\s+)?(?:log|file|report)\s+(?:it|this|that)\s*(?:as\s+)?"
        r"(?:a\s+)?(?:bug|issue|problem)\b\.?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or text.strip()


def _guess_subsystem(description: str) -> str:
    lowered = description.lower()
    surface = {
        "cockpit": "dashboard",
        "dashboard": "dashboard",
        "icon": "dashboard",
        "splitting": "dashboard",
        "split": "dashboard",
        "transaction": "dashboard",
        "ui": "dashboard",
        "interface": "dashboard",
        "telegram": "telegram",
        "bot": "telegram",
        "email": "email",
        "gmail": "email",
        "expense": "expenses",
        "receipt": "expenses",
        "route": "routes",
        "bus": "routes",
        "reminder": "reminders",
        "recipe": "recipes",
        "grocery": "recipes",
        "whiteboard": "whiteboard",
        "board": "whiteboard",
    }
    for keyword, subsystem in surface.items():
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return subsystem
    return "general"


def _stable_fingerprint(description: str) -> str:
    """Deterministic fingerprint so identical reports dedup into one issue."""
    normalized = re.sub(r"\s+", " ", description.strip().lower())
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
    return f"userbug_{digest}"


async def log_user_bug(
    user_id: int,
    description: str,
    subsystem: str = "general",
) -> Dict[str, Any]:
    """Record a user-reported bug through the production-bug pipeline."""
    from core.audit import record_operation_event

    record = await record_operation_event(
        subsystem=subsystem,
        error_context=description[:2000],
        detection_source="user_reported",
        user_id=user_id,
        fingerprint=_stable_fingerprint(description),
        severity="P3",
        title=f"User-reported: {description[:80]}",
    )
    if not record:
        return {"logged": False}

    url = None
    number = None
    try:
        from core.db import async_session_factory
        from core.models import ProductionBugLog

        async with async_session_factory() as session:
            db_entry = await session.get(ProductionBugLog, record.id)
            if db_entry:
                url = db_entry.github_issue_url
                number = db_entry.github_issue_number
    except Exception:  # noqa: BLE001 - URL is best-effort after the write
        pass

    return {
        "logged": True,
        "bug_id": record.id,
        "github_issue_url": url,
        "github_issue_number": number,
        "occurrence_count": record.occurrence_count,
    }


@tool
@identity_bound
async def log_bug_report(text: str, user_id: int = 0) -> str:
    """
    Log a bug or issue the user noticed (in the cockpit, a skill, or an
    integration) into the production-bug pipeline and GitHub issue backlog.
    Use when the user reports something broken or asks you to file/report a
    bug -- e.g. "log it as a bug: the split icon is missing" or "there's an
    issue with the cockpit".

    Args:
        text: the user's bug report / description of what went wrong.
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    description = _extract_bug_description(text)
    subsystem = _guess_subsystem(description or text)
    result = await log_user_bug(
        user_id=int(user_id or 0), description=description or text, subsystem=subsystem
    )
    if not result.get("logged"):
        return "[bug_logging] Couldn't log that bug right now -- try again in a moment."
    url = result.get("github_issue_url")
    if url:
        return f"Logged as a bug and filed in the tracker: {url}"
    return (
        "Logged as a bug -- recorded locally, will sync to the issue tracker "
        "when GitHub is configured."
    )