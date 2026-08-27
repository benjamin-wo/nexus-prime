"""Personal memory slice #1: loyalty points/miles balances.

Structured, per-user records keyed by (issuer, program). A new statement
upserts the existing balance rather than appending; recall lists them back.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from sqlmodel import select

from core.config import settings
from core.db import async_session_factory
from core.llm import ThinkingLevel, get_agent_llm
from core.models import PointsBalance
from core.tool_guard import identity_bound

KNOWN_ISSUERS = ("dbs", "citibank", "citi", "uob", "ocbc", "maybank", "krisflyer", "sia", "amex", "american express")


def _normalize_issuer(raw: str) -> str:
    lowered = (raw or "").strip().lower()
    if lowered in {"citi", "citibank"}:
        return "Citibank"
    if lowered in {"krisflyer", "sia"}:
        return "KrisFlyer"
    if lowered in {"american express", "amex"}:
        return "Amex"
    if lowered in {"dbs", "posb"}:
        return "DBS"
    if lowered in {"uob"}:
        return "UOB"
    if lowered in {"ocbc"}:
        return "OCBC"
    if lowered in {"maybank"}:
        return "Maybank"
    return (raw or "").strip().title() or "Unknown"


def _regex_extract_points(text: str) -> Optional[Dict[str, Any]]:
    """Deterministic fallback when no LLM key is available."""
    lowered = (text or "").lower()
    # Number before unit: "12000 DBS reward points", "45000 miles".
    before = re.search(
        r"(\d[\d,.]*)\s+(?:[a-z0-9&' ]+?\s+){0,3}(?:reward\s*)?(?:points|miles)\b", lowered
    )
    # Number after unit: "miles balance is 45000", "points: 12000".
    after = re.search(
        r"\b(?:points|miles)\b[^\d]{0,30}?(\d[\d,.]*)", lowered
    )
    match = before or after
    if not match:
        return None
    balance = float((match.group(1) or match.group(2)).replace(",", ""))
    issuer = None
    for known in KNOWN_ISSUERS:
        if known in lowered:
            issuer = _normalize_issuer(known)
            break
    program = None
    prog_match = re.search(r"([a-z0-9&' ]+?)\s+(?:reward\s*)?points", lowered)
    if prog_match:
        candidate = prog_match.group(1).strip()
        if candidate and candidate not in {"i have", "have", "earned", "got", "for", "with", "about", "my"}:
            program = candidate.title()
    return {"issuer": issuer, "program": program, "balance": balance}


async def extract_points_balance(user_text: str) -> Dict[str, Any]:
    """Extract a points/miles balance mention into structured fields."""
    if not settings.has_llm_key:
        return _regex_extract_points(user_text) or {}

    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.0)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Extract a loyalty points/miles balance from the user's message. "
                        "Reply with ONLY JSON: "
                        '{"issuer": string|null, "program": string|null, "balance": number|null, '
                        '"expiry": string|null (ISO date)}. '
                        'issuer is the bank/airline (DBS, Citibank, UOB, KrisFlyer, Amex, ...). '
                        "If the message does not contain a points/miles balance statement, "
                        'return {"balance": null}. Never invent values.'
                    )
                ),
                HumanMessage(content=(user_text or "")[:2000]),
            ]
        )
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        import json

        parsed = json.loads(raw)
        balance = parsed.get("balance")
        if balance is None:
            return {}
        return {
            "issuer": _normalize_issuer(parsed.get("issuer") or ""),
            "program": (parsed.get("program") or "").strip().title() or None,
            "balance": float(balance),
            "expiry": parsed.get("expiry") or None,
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[MEMORY] extraction LLM failed, using regex: {exc}")
        return _regex_extract_points(user_text) or {}


async def upsert_points_balance(
    user_id: int,
    issuer: str,
    program: Optional[str] = None,
    balance: Optional[float] = None,
    expiry: Optional[str] = None,
) -> Optional[PointsBalance]:
    """Upsert a points/miles balance by (user_id, issuer, program)."""
    clean_issuer = _normalize_issuer(issuer)
    clean_program = (program or "").strip() or ""
    async with async_session_factory() as session:
        result = await session.execute(
            select(PointsBalance).where(
                PointsBalance.user_id == user_id,
                PointsBalance.issuer == clean_issuer,
                PointsBalance.program == clean_program,
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            record = PointsBalance(
                user_id=user_id,
                issuer=clean_issuer,
                program=clean_program,
                balance=balance or 0.0,
                updated_at=datetime.now(dt_timezone.utc),
            )
        else:
            if balance is not None:
                record.balance = balance
            record.updated_at = datetime.now(dt_timezone.utc)
        if expiry:
            try:
                record.expiry_date = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            except Exception:
                pass
        session.add(record)
        await session.commit()
        await session.refresh(record)
        return record


async def query_points_balances(user_id: int) -> List[Dict[str, Any]]:
    """List all stored points/miles balances for a user."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(PointsBalance).where(PointsBalance.user_id == user_id).order_by(PointsBalance.issuer)
        )
        rows = result.scalars().all()
        return [
            {
                "issuer": r.issuer,
                "program": r.program or None,
                "balance": r.balance,
                "expiry": r.expiry_date.isoformat() if r.expiry_date else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


@tool
@identity_bound
async def record_points_balance(text: str, user_id: int = 0) -> str:
    """
    Remember a loyalty points/miles balance the user just told you, e.g. "I
    have 12000 DBS points" or "my Citibank miles balance is 45000". Extracts
    issuer/program/balance/expiry from natural language and stores it,
    updating the existing record for that issuer/program rather than
    duplicating it. Use query_my_points_balances to recall stored balances --
    this tool is for recording a NEW statement only.

    Args:
        text: the user's natural-language points/miles balance statement.
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    extracted = await extract_points_balance(text)
    if not extracted.get("balance"):
        return "[memory] Couldn't find a points/miles balance in that message."
    record = await upsert_points_balance(
        user_id=int(user_id or 0),
        issuer=extracted.get("issuer") or "Unknown",
        program=extracted.get("program"),
        balance=float(extracted["balance"]),
        expiry=extracted.get("expiry"),
    )
    label = record.program or record.issuer
    expiry_note = (
        f", expiring {record.expiry_date.strftime('%d %b %Y')}"
        if record.expiry_date
        else ""
    )
    return f"Saved {label}: {record.balance:,.0f} points/miles{expiry_note}."