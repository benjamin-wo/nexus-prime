from datetime import datetime, timezone as dt_timezone
from email.utils import parsedate_to_datetime
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
from core.llm import (
    ThinkingLevel,
    extract_llm_text,
    get_agent_llm,
    get_multimodal_llm,
)
from core.models import ExpenseTransaction, DeletedExpenseMessage
from capabilities.expenses.schemas import ExtractedExpense
from capabilities.email.tools import apply_gmail_processed_label, apply_email_processed_tag

async def is_duplicate_expense(source_message_id: Optional[str]) -> bool:
    """Layer 2 Deduplication: check if source_message_id is in PostgreSQL or was previously deleted."""
    if not source_message_id:
        return False
    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.source_message_id == source_message_id)
        )
        if result.scalar_one_or_none() is not None:
            return True
        del_result = await session.execute(
            select(DeletedExpenseMessage).where(DeletedExpenseMessage.source_message_id == source_message_id)
        )
        return del_result.scalar_one_or_none() is not None
def normalize_category_name(raw: Optional[str]) -> str:
    """Canonical category mapping for incoming receipts and messages."""
    if not raw:
        return "General"
    c = raw.strip().lower()
    if any(k in c for k in ["dining", "food", "restaurant", "cafe", "hawker", "beverage", "drink", "coffee", "meal", "bar", "cider", "bakery"]):
        return "Dining"
    if any(k in c for k in ["grocer", "supermarket", "mart", "fairprice", "cold storage", "shengsiong", "convenience", "7-eleven", "cheers"]):
        return "Groceries"
    if any(k in c for k in ["transport", "transit", "bus", "mrt", "grab", "taxi", "gojek", "comfort", "ride"]):
        return "Transport"
    if any(k in c for k in ["shop", "retail", "uniqlo", "clothes", "apparel", "electronics", "amazon", "lazada", "shopee", "department"]):
        return "Shopping"
    if any(k in c for k in ["bill", "utilit", "telco", "singtel", "starhub", "subscri", "netflix", "spotify", "rent", "insurance", "telecom"]):
        return "Bills"
    if c in ["other", "unknown", "misc", "miscellaneous"]:
        return "General"
    return raw.strip().title()


async def save_expense_transaction(
    user_id: int,
    expense: ExtractedExpense,
    source_message_id: Optional[str] = None,
    is_verified: bool = True,
) -> ExpenseTransaction:
    """Persist ExtractedExpense to PostgreSQL ExpenseTransaction table with normalized category."""
    async with async_session_factory() as session:
        norm_cat = normalize_category_name(expense.category)
        tx = ExpenseTransaction(
            user_id=user_id,
            amount=expense.amount,
            currency=expense.currency,
            merchant=expense.merchant,
            category=norm_cat,
            date=expense.date,
            source_message_id=source_message_id,
            is_verified=is_verified,
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)
        return tx


def _regex_extract_expense(text: str) -> Dict[str, Any]:
    """Deterministic regex extraction fallback for when LLM quota is unavailable."""
    amount = None
    currency = "SGD"

    # 1. Check with explicit currency prefix ($18.50, SGD 18.50, S$12, USD 25.00)
    m = re.search(r"(?:SGD|S\$|\$|USD|EUR|GBP|€|£|¥)\s*(\d{1,6}(?:\.\d{1,2})?)", text, re.IGNORECASE)
    if m:
        try:
            val = float(m.group(1))
            if 0.01 <= val < 100000.0 and val not in (2024.0, 2025.0, 2026.0, 2027.0):
                amount = val
        except ValueError:
            pass

    # 2. Check with explicit currency suffix ("18.50 SGD", "25 dollars", "15.00 bucks")
    if not amount:
        m = re.search(r"(\d{1,6}(?:\.\d{1,2})?)\s*(?:SGD|S\$|USD|EUR|GBP|dollars|bucks)", text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 0.01 <= val < 100000.0 and val not in (2024.0, 2025.0, 2026.0, 2027.0):
                    amount = val
            except ValueError:
                pass

    # 3. Check "spent/paid/cost/charged/total: 18.50"
    if not amount:
        m = re.search(r"\b(?:spent|paid|cost|charged|total|bill|amount|fee)\s*[:=-]?\s*(?:\$|SGD|S\$)?\s*(\d{1,6}(?:\.\d{1,2})?)", text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 0.01 <= val < 100000.0 and val not in (2024.0, 2025.0, 2026.0, 2027.0):
                    amount = val
            except ValueError:
                pass

    # 4. Check standard decimal price (e.g. 18.50) ONLY if preceded by standard transaction words
    if not amount:
        m = re.search(r"\b(?:payment of|price of|received|subtotal)\s*(\d{1,6}\.\d{2})\b", text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 0.01 <= val < 100000.0 and val not in (2024.0, 2025.0, 2026.0, 2027.0):
                    amount = val
            except ValueError:
                pass

    if not amount or amount <= 0:
        return {"amount": None}

    text_lower = text.lower()
    category = "General"
    if any(k in text_lower for k in ["lunch", "dinner", "breakfast", "coffee", "cafe", "starbucks", "food", "eat", "mcdonald", "toast", "dining", "bar", "drinks"]):
        category = "Dining"
    elif any(k in text_lower for k in ["grab", "gojek", "taxi", "cab", "mrt", "bus", "transport", "petrol", "parking"]):
        category = "Transport"
    elif any(k in text_lower for k in ["ntuc", "fairprice", "cold storage", "supermarket", "groceries", "grocery", "donki", "shengsiong"]):
        category = "Groceries"
    elif any(k in text_lower for k in ["shopee", "lazada", "amazon", "uniqlo", "zara", "shopping", "clothes", "shoes"]):
        category = "Shopping"
    elif any(k in text_lower for k in ["bill", "utilities", "singtel", "starhub", "sp services", "rent", "insurance", "telco"]):
        category = "Bills"

    merchant = "Direct Expense"
    disclaimer_words = [
        "receiving", "this", "my", "your", "the", "an", "a", "us", "here",
        "it", "which", "whose", "whom", "email", "any", "disclaimer", "privacy"
    ]
    m_match = re.search(r"(?:at|from|@)\s+([A-Za-z0-9\s&'-]+?)(?:\s+for|\s+on|\s*[-–:]|\s*$)", text, re.IGNORECASE)
    if m_match:
        cand = m_match.group(1).strip()
        if not any(cand.lower().startswith(w) for w in disclaimer_words):
            merchant = cand
    else:
        for_match = re.search(r"(?:on|for)\s+([A-Za-z0-9\s&'-]+?)(?:\s+at|\s+from|\s*[-–:]|\s*$)", text, re.IGNORECASE)
        if for_match:
            cand = for_match.group(1).strip()
            if not any(cand.lower().startswith(w) for w in disclaimer_words):
                merchant = cand

    return {
        "amount": amount,
        "currency": currency,
        "merchant": merchant[:60] if merchant else "Expense",
        "category": category,
        "date_iso": "",
        "confidence": 0.85,
        "needs_clarification": False,
    }


def clean_sender_name(sender_raw: str) -> str:
    """Extract a human-friendly merchant/brand name from an email sender string."""
    if not sender_raw:
        return ""
    # Extract "Name" from "Name <email@domain.com>"
    match = re.match(r"^[\"'\s]*([^<>\"]+?)[\"'\s]*<.+?>", sender_raw.strip())
    if match:
        name = match.group(1).strip()
        if name and not re.match(r"^(?:no[-_]?reply|notification|alerts?|receipts?|orders?|support|info|billing|service)$", name, re.IGNORECASE):
            return name
    # Extract domain if email only
    email_match = re.search(r"[\w\.-]+@([\w\.-]+)", sender_raw)
    if email_match:
        domain = email_match.group(1).lower()
        parts = [p for p in domain.split(".") if p not in ["com", "sg", "org", "net", "io", "co", "gov", "edu", "email", "mail", "app"]]
        if parts:
            clean_part = parts[-1]
            if clean_part not in ["gmail", "yahoo", "hotmail", "outlook", "icloud"]:
                return clean_part.capitalize()
    return sender_raw.strip()


def _resolve_email_merchant(
    extracted_merchant: Optional[str],
    sender: str = "",
    subject: str = "",
    snippet: str = "",
) -> str:
    """Resolve an accurate merchant name for an email, filtering out email boilerplate/disclaimers."""
    clean_sender = clean_sender_name(sender)
    invalid_fragments = [
        "receiving this", "this email", "email and any", "terms and conditions",
        "privacy policy", "unsubscribe", "do not reply", "no-reply", "unknown",
        "direct expense", "expense", "transaction", "payment", "invoice",
        "receipt", "e-receipt", "tax invoice"
    ]
    if extracted_merchant:
        m_lower = extracted_merchant.strip().lower()
        is_invalid = any(frag in m_lower for frag in invalid_fragments) or len(extracted_merchant.strip()) < 2
        if not is_invalid:
            return extracted_merchant.strip()
    if subject:
        sub_match = re.search(r"(?:from|at)\s+([A-Za-z0-9\s&'-]{2,30})(?:\s+for|\s+order|\s+on|\s*[-–:]|\s*$)", subject, re.IGNORECASE)
        if sub_match:
            sub_cand = sub_match.group(1).strip()
            if not any(frag in sub_cand.lower() for frag in invalid_fragments):
                return sub_cand
    if clean_sender:
        return clean_sender
    return "Email Receipt"


@tool
async def extract_expense_from_text(user_text: str) -> Dict[str, Any]:
    """
    Extract structured expense fields from a natural-language message.
    Returns amount, currency, merchant, category, date_iso, confidence, needs_clarification.
    """
    messages = [
        SystemMessage(
            content=(
                "You are a strict financial transaction extractor. "
                "Analyze the message/receipt/email and extract the EXACT transaction amount paid or spent.\n"
                "RULES:\n"
                "1. If the message is a promotional email, terms update, newsletter, login notification, security alert, or does NOT contain a genuine paid expense, return {\"amount\": null}.\n"
                "2. DO NOT extract years (e.g. 2026), dates (e.g. 21 Aug), phone numbers, account numbers, card numbers, or transaction reference IDs (e.g. Ref: 7873098920963352) as the amount.\n"
                "3. Extract ONLY the total price or amount actually charged/spent.\n"
                "4. Reply with ONLY a JSON object:\n"
                '{"amount": number|null, "currency": string, "merchant": string, "category": string, "date_iso": string, "confidence": number, "needs_clarification": boolean}\n'
                "Default currency: SGD for Singapore."
            )
        ),
        HumanMessage(content=user_text[:2000]),
    ]

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.1)
        ai_message = await llm.ainvoke(messages)
    except Exception as primary_exc:
        # Fallback directly to Gemini if DeepSeek fails or lacks quota
        try:
            from core.llm import get_multimodal_llm
            fallback_llm = get_multimodal_llm(temperature=0.1)
            ai_message = await fallback_llm.ainvoke(messages)
        except Exception as exc:
            print(f"[EXPENSES] extraction parse failed (both primary and fallback): {exc}")
            return _regex_extract_expense(user_text)

    try:
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        if parsed.get("amount") is None:
            return {"amount": None}

        amount_val = float(parsed["amount"])
        # Guard against absurd extracted numbers or years
        if amount_val <= 0 or amount_val >= 100000.0 or amount_val in (2024.0, 2025.0, 2026.0, 2027.0):
            # Check if this was an actual price mentioned with currency symbol
            if not re.search(r"(?:SGD|S\$|\$|USD|EUR|GBP)\s*" + re.escape(str(int(amount_val))), user_text):
                return {"amount": None}

        return {
            "amount": amount_val,
            "currency": parsed.get("currency") or "SGD",
            "merchant": parsed.get("merchant") or "Unknown",
            "category": parsed.get("category") or "General",
            "date_iso": parsed.get("date_iso") or "",
            "confidence": float(parsed.get("confidence", 0.9)),
            "needs_clarification": bool(parsed.get("needs_clarification", False)),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[EXPENSES] JSON parse failed: {exc}")
        return _regex_extract_expense(user_text)


@tool
async def extract_expense_from_photo(
    image_b64: str,
    mime_type: str = "image/jpeg",
    caption: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Extract structured expense fields from a receipt photo using Gemini vision.
    Returns amount, currency, merchant, category, date_iso, confidence, needs_clarification.
    """
    if (
        not settings.active_gemini_api_key
        or settings.active_gemini_api_key == "test_google_key"
    ):
        return {"amount": None}

    llm = get_multimodal_llm(temperature=0.1)
    prompt_text = (
        caption
        or "Extract the expense shown in this receipt photo."
    )
    ai_message = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    "You extract expenses from receipt photos. Reply with ONLY a JSON object: "
                    '{"amount": number, "currency": string (3-letter code, default SGD), '
                    '"merchant": string, "category": string, "date_iso": string (ISO 8601 with time and timezone if mentioned, e.g. 2026-08-16T14:32:00, or YYYY-MM-DD), '
                    '"confidence": number 0-1, "needs_clarification": boolean}. '
                    "Read the TOTAL from the receipt. If there is no legible receipt or amount, "
                    'return {"amount": null}.'
                )
            ),
            HumanMessage(
                content=[
                    {"type": "text", "text": prompt_text},
                    {"type": "media", "mime_type": mime_type, "data": image_b64},
                ]
            ),
        ]
    )
    raw = extract_llm_text(getattr(ai_message, "content", ""))
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        parsed = json.loads(raw)
        if not parsed.get("amount"):
            return {"amount": None}
        return {
            "amount": float(parsed["amount"]),
            "currency": parsed.get("currency") or "SGD",
            "merchant": parsed.get("merchant") or "Unknown",
            "category": parsed.get("category") or "General",
            "date_iso": parsed.get("date_iso") or "",
            "confidence": float(parsed.get("confidence", 0.9)),
            "needs_clarification": bool(parsed.get("needs_clarification", False)),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[EXPENSES] photo extraction parse failed: {exc}")
        return {"amount": None}


def expense_source_id(user_id: int, text: str) -> str:
    """Stable dedup key for an expense logged from a Telegram message."""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return f"tg-{user_id}-{digest}"


@tool
async def get_user_expenses(
    user_id: int,
    limit: int = 10,
    categories: Optional[List[str]] = None,
    since_date: Optional[str] = None,
    until_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieve the user's expense transactions, optionally filtered by category list
    and/or a date range (ISO 8601 strings). Returns up to `limit` rows ordered newest-first.
    """
    from sqlmodel import or_
    async with async_session_factory() as session:
        query = select(ExpenseTransaction).where(ExpenseTransaction.user_id == user_id)

        if categories:
            query = query.where(
                or_(*[ExpenseTransaction.category == cat for cat in categories])
            )
        if since_date:
            try:
                cutoff = datetime.fromisoformat(since_date)
                # DB column is TIMESTAMP WITHOUT TIME ZONE — strip tz to avoid asyncpg mismatch
                if cutoff.tzinfo is not None:
                    from datetime import timezone as _dt_tz
                    cutoff = cutoff.astimezone(_dt_tz.utc).replace(tzinfo=None)
            except ValueError:
                cutoff = None
            if cutoff:
                query = query.where(ExpenseTransaction.date >= cutoff)
        if until_date:
            try:
                cutoff_end = datetime.fromisoformat(until_date)
                if cutoff_end.tzinfo is not None:
                    from datetime import timezone as _dt_tz
                    cutoff_end = cutoff_end.astimezone(_dt_tz.utc).replace(tzinfo=None)
            except ValueError:
                cutoff_end = None
            if cutoff_end:
                query = query.where(ExpenseTransaction.date < cutoff_end)

        query = query.order_by(ExpenseTransaction.date.desc()).limit(limit)
        result = await session.execute(query)
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
async def log_expenses_from_emails(
    user_id: int,
    emails: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Auto-extract and log expenses from fetched email messages.
    Each email ID becomes the dedup key, so re-checking the inbox never double-logs.
    Ambiguous or low-confidence emails are skipped (never sent to HITL buttons).
    """
    logged: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for email_msg in (emails or [])[:10]:
        email_id = str(email_msg.get("id") or "")
        sender = str(email_msg.get("sender") or "")
        subject = str(email_msg.get("subject") or "")
        body_text = str(email_msg.get("body") or email_msg.get("snippet") or "")
        snippet = str(email_msg.get("snippet") or "")

        text = f"Sender: {sender}\nSubject: {subject}\nBody: {body_text}"
        extracted = await extract_expense_from_text.ainvoke({"user_text": text})
        if not extracted or not extracted.get("amount"):
            continue

        merchant = _resolve_email_merchant(
            extracted_merchant=extracted.get("merchant"),
            sender=sender,
            subject=subject,
            snippet=snippet,
        )

        if extracted.get("confidence", 0) < 0.8 or extracted.get("needs_clarification"):
            skipped.append(
                {
                    "amount": extracted["amount"],
                    "currency": extracted.get("currency", "SGD"),
                    "merchant": merchant,
                }
            )
            continue

        if email_id and await is_duplicate_expense(email_id):
            continue

        date_iso = extracted.get("date_iso") or ""
        email_date_str = email_msg.get("date") or ""

        def _parse_raw_dt(v: str) -> Optional[datetime]:
            if not v:
                return None
            try:
                return parsedate_to_datetime(v)
            except Exception:
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00"))
                except Exception:
                    return None

        email_dt = _parse_raw_dt(email_date_str)
        extracted_dt = _parse_raw_dt(date_iso)

        if extracted_dt and (extracted_dt.hour != 0 or extracted_dt.minute != 0 or extracted_dt.second != 0):
            expense_date = extracted_dt
        elif extracted_dt and email_dt:
            # Combine extracted date with email message timestamp
            expense_date = datetime.combine(extracted_dt.date(), email_dt.time())
        elif email_dt:
            # Fall back to exact email header timestamp
            expense_date = email_dt
        elif extracted_dt:
            # Attach polling/logging timestamp
            expense_date = datetime.combine(extracted_dt.date(), datetime.now().time())
        else:
            expense_date = datetime.now()

        if hasattr(expense_date, "tzinfo") and expense_date.tzinfo:
            expense_date = expense_date.astimezone(dt_timezone.utc).replace(tzinfo=None)

        expense = ExtractedExpense(
            amount=float(extracted["amount"]),
            currency=extracted.get("currency") or "SGD",
            merchant=merchant,
            category=extracted.get("category") or "General",
            date=expense_date,
            confidence=float(extracted.get("confidence", 0.9)),
            needs_clarification=False,
        )
        tx = await save_expense_transaction(
            user_id=user_id,
            expense=expense,
            source_message_id=email_id or None,
            is_verified=True,
        )
        if email_id:
            try:
                provider = email_msg.get("provider", "gmail")
                await apply_email_processed_tag.ainvoke(
                    {"user_id": user_id, "message_id": email_id, "provider": provider}
                )
            except Exception as tag_err:
                print(f"[EXPENSES] Failed to apply processed tag to {email_id}: {tag_err}")

        # Smart Low-Intrusion Notification Threshold:
        # Only ping Telegram for high-value / group-sized expenses (>= $50 SGD) with Split Bill shortcut
        if expense.amount >= 50.0:
            try:
                from app.ingress import send_telegram_message
                alert_text = (
                    f"💳 **New Expense Logged: {expense.currency} {expense.amount:.2f} at {expense.merchant}**\n\n"
                    f"📅 {expense.date.strftime('%d %b %Y, %H:%M')}\n"
                    f"🏷️ Category: #{expense.category}\n\n"
                    f"Did you foot the bill for a group?"
                )
                buttons = [[{"text": "👥 Split this bill", "callback_data": f"sb:{tx.id}"}]]
                await send_telegram_message(
                    chat_id=user_id,
                    text=alert_text,
                    reply_markup={"inline_keyboard": buttons},
                )
            except Exception as notify_err:
                print(f"[EXPENSES] Smart alert notification failed: {notify_err}")

        logged.append(
            {
                "amount": expense.amount,
                "currency": expense.currency,
                "merchant": expense.merchant,
                "category": expense.category,
                "transaction_id": tx.id,
            }
        )

    return {"logged": logged, "skipped": skipped}

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
        dt = datetime.fromisoformat(date_iso.replace("Z", "+00:00"))
        if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
            dt = datetime.combine(dt.date(), datetime.now().time())
    except Exception:
        dt = datetime.now()

    if hasattr(dt, "tzinfo") and dt.tzinfo:
        dt = dt.astimezone(dt_timezone.utc).replace(tzinfo=None)

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


@tool
async def split_bill_expense(
    user_id: int,
    total_amount: float,
    merchant: str = "Dinner / Event",
    people: Optional[List[str]] = None,
    people_count: Optional[int] = None,
    transaction_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Split an expense among friends, auto-adjust user's personal spend on dashboard,
    generate copy-pastable WhatsApp group text, and create 1-tap IOU collection tasks.
    """
    from core.models import TaskItem, ExpenseTransaction
    from core.db import async_session_factory
    from sqlmodel import select, desc

    # Parse friends list
    parsed_people = []
    if people:
        for p in people:
            cleaned = p.strip().title()
            if cleaned and cleaned.lower() not in {"me", "myself", "i", "you", "user"}:
                parsed_people.append(cleaned)

    unique_friends = list(dict.fromkeys(parsed_people))

    if people_count and people_count > 1 and len(unique_friends) < (people_count - 1):
        needed = (people_count - 1) - len(unique_friends)
        for i in range(1, needed + 1):
            unique_friends.append(f"Friend {len(unique_friends) + 1}")

    total_splits = len(unique_friends) + 1
    if total_splits < 2:
        total_splits = 2
        unique_friends = ["Friend 1"]

    per_person = round(total_amount / total_splits, 2)
    my_share = round(total_amount - (per_person * len(unique_friends)), 2)

    created_tasks = []
    async with async_session_factory() as session:
        # 1. Update existing parent transaction to user's net share
        target_tx = None
        if transaction_id:
            target_tx = (await session.execute(
                select(ExpenseTransaction).where(ExpenseTransaction.id == transaction_id, ExpenseTransaction.user_id == user_id)
            )).scalar_one_or_none()
        else:
            recent_txs = (await session.execute(
                select(ExpenseTransaction)
                .where(ExpenseTransaction.user_id == user_id)
                .order_by(desc(ExpenseTransaction.date))
                .limit(5)
            )).scalars().all()
            for tx in recent_txs:
                if abs(tx.amount - total_amount) < 0.01 or (merchant.lower() in (tx.merchant or "").lower()):
                    target_tx = tx
                    break

        if target_tx:
            target_tx.amount = my_share
            target_tx.merchant = f"{merchant} (My share of ${total_amount:.2f})"
            session.add(target_tx)

        # 2. Create IOU tasks for each friend
        for friend in unique_friends:
            iou_task = TaskItem(
                user_id=user_id,
                title=f"Collect ${per_person:.2f} from {friend} for {merchant}",
                priority="medium",
                status="todo",
                reminder_type="none",
                description=f"Bill split from ${total_amount:.2f} total ({total_splits} people).",
            )
            session.add(iou_task)
            await session.flush()
            created_tasks.append({
                "task_id": iou_task.id,
                "friend": friend,
                "amount": per_person,
            })

        await session.commit()

    # Format copy-paste text for WhatsApp / Telegram group chat
    breakdown_lines = [f"• {friend}: **${per_person:.2f}**" for friend in unique_friends]
    breakdown_lines.append(f"• You: **${my_share:.2f}** *(Paid)*")

    copy_paste_lines = [f"{friend}: ${per_person:.2f}" for friend in unique_friends]
    copy_paste_lines.append(f"Me: ${my_share:.2f} (Paid)")

    copy_paste_block = (
        f"🧾 *{merchant} Bill Split (${total_amount:.2f})*\n"
        + "\n".join(copy_paste_lines)
        + "\n👉 *PayNow to my mobile number!*"
    )

    full_reply = (
        f"🧾 **Bill Split: {merchant} (${total_amount:.2f} across {total_splits} people)**\n\n"
        + "\n".join(breakdown_lines)
        + f"\n\n📋 **Copy & Paste for Group Chat:**\n<code>{copy_paste_block}</code>\n\n"
        + f"💡 *Adjusted your dashboard expense to **${my_share:.2f}** and created {len(created_tasks)} IOU tasks below.*"
    )

    buttons = [[{"text": f"✅ {t['friend']} Paid (${t['amount']:.2f})", "callback_data": f"td:{t['task_id']}"}] for t in created_tasks]

    return {
        "status": "ok",
        "total_amount": total_amount,
        "my_share": my_share,
        "per_person": per_person,
        "friends": unique_friends,
        "tasks": created_tasks,
        "reply_text": full_reply,
        "buttons": buttons,
    }

