from datetime import datetime, timezone as dt_timezone
import hashlib
import json
import re
from typing import Optional, Dict, Any, List
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.types import interrupt
from sqlmodel import select
from core.db import async_session_factory
from core.config import settings
from core.llm import ThinkingLevel, get_agent_llm
from core.models import ExpenseTransaction
from capabilities.expenses.schemas import ExtractedExpense
from capabilities.email.tools import apply_gmail_processed_label

async def is_duplicate_expense(source_message_id: Optional[str]) -> bool:
    """Layer 2 Deduplication: check if source_message_id is already in PostgreSQL."""
    if not source_message_id:
        return False
    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.source_message_id == source_message_id)
        )
        return result.scalar_one_or_none() is not None

async def save_expense_transaction(
    user_id: int,
    expense: ExtractedExpense,
    source_message_id: Optional[str] = None,
    is_verified: bool = True,
) -> ExpenseTransaction:
    """Persist ExtractedExpense to PostgreSQL ExpenseTransaction table."""
    async with async_session_factory() as session:
        tx = ExpenseTransaction(
            user_id=user_id,
            amount=expense.amount,
            currency=expense.currency,
            merchant=expense.merchant,
            category=expense.category,
            date=expense.date,
            source_message_id=source_message_id,
            is_verified=is_verified,
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)
        return tx


@tool
async def extract_expense_from_text(user_text: str) -> Dict[str, Any]:
    """
    Extract structured expense fields from a natural-language message.
    Returns amount, currency, merchant, category, date_iso, confidence, needs_clarification.
    """
    if not settings.deepseek_api_key or settings.deepseek_api_key == "test_deepseek_key":
        return {"amount": None}

    llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.1)
    ai_message = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    "Extract an expense from the user's message. Reply with ONLY a JSON object: "
                    '{"amount": number, "currency": string (3-letter code, default USD), '
                    '"merchant": string, "category": string, "date_iso": string (ISO 8601 or empty), '
                    '"confidence": number 0-1, "needs_clarification": boolean}. '
                    "Set confidence below 0.8 or needs_clarification true when the amount or "
                    "merchant is ambiguous. If no expense is present, return {\"amount\": null}."
                )
            ),
            HumanMessage(content=user_text[:2000]),
        ]
    )
    raw = str(getattr(ai_message, "content", "") or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw)
        if not parsed.get("amount"):
            return {"amount": None}
        return {
            "amount": float(parsed["amount"]),
            "currency": parsed.get("currency") or "USD",
            "merchant": parsed.get("merchant") or "Unknown",
            "category": parsed.get("category") or "General",
            "date_iso": parsed.get("date_iso") or "",
            "confidence": float(parsed.get("confidence", 0.9)),
            "needs_clarification": bool(parsed.get("needs_clarification", False)),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[EXPENSES] extraction parse failed: {exc}")
        return {"amount": None}


def expense_source_id(user_id: int, text: str) -> str:
    """Stable dedup key for an expense logged from a Telegram message."""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return f"tg-{user_id}-{digest}"


@tool
async def get_user_expenses(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve the user's most recent expense transactions."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction)
            .where(ExpenseTransaction.user_id == user_id)
            .order_by(ExpenseTransaction.date.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            {
                "id": row.id,
                "amount": row.amount,
                "currency": row.currency,
                "merchant": row.merchant,
                "category": row.category,
                "date": row.date.isoformat(),
                "verified": row.is_verified,
            }
            for row in rows
        ]

@tool
async def process_extracted_expense(
    user_id: int,
    amount: float,
    currency: str,
    merchant: str,
    category: str,
    date_iso: str,
    confidence: float = 0.9,
    needs_clarification: bool = False,
    source_message_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process an extracted expense. Enforces 2-layer deduplication and HITL confirmation on low confidence.
    """
    if await is_duplicate_expense(source_message_id):
        return {"status": "duplicate", "message": f"Message {source_message_id} already processed."}

    try:
        dt = datetime.fromisoformat(date_iso)
    except ValueError:
        dt = datetime.now(dt_timezone.utc)

    expense = ExtractedExpense(
        amount=amount,
        currency=currency,
        merchant=merchant,
        category=category,
        date=dt,
        confidence=confidence,
        needs_clarification=needs_clarification,
    )

    # Low confidence or ambiguous: pause execution and request user confirmation
    if confidence < 0.8 or needs_clarification:
        hitl_payload = {
            "type": "confirm_action",
            "action": "confirm_expense",
            "user_id": user_id,
            "amount": amount,
            "currency": currency,
            "merchant": merchant,
            "category": category,
            "date": date_iso,
            "source_message_id": source_message_id,
            "prompt": f"❓ Found an expense of ${amount:.2f}. Was this at {merchant}?",
            "buttons": [
                {"text": "✅ Confirm", "callback_data": '{"a": "confirm"}'},
                {"text": "✏️ Edit", "callback_data": '{"a": "edit"}'},
                {"text": "❌ Ignore", "callback_data": '{"a": "ignore"}'},
            ],
        }
        # LangGraph interrupt raises NodeInterrupt and suspends checkpoint until resumed
        user_response = interrupt(value=hitl_payload)

        # Once resumed, evaluate user response
        if isinstance(user_response, dict) and user_response.get("action") == "confirm":
            tx = await save_expense_transaction(user_id, expense, source_message_id, is_verified=True)
            if source_message_id:
                await apply_gmail_processed_label.ainvoke({"user_id": user_id, "message_id": source_message_id})
            return {"status": "confirmed_by_user", "transaction_id": tx.id}
        elif isinstance(user_response, dict) and user_response.get("action") == "ignore":
            return {"status": "ignored_by_user"}
        else:
            return {"status": "hitl_resumed", "details": str(user_response)}

    # High confidence (confidence >= 0.8 and not needs_clarification): log silently & tag
    tx = await save_expense_transaction(user_id, expense, source_message_id, is_verified=True)
    if source_message_id:
        await apply_gmail_processed_label.ainvoke({"user_id": user_id, "message_id": source_message_id})
    return {"status": "saved_silently", "transaction_id": tx.id}
