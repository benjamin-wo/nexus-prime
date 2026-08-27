from datetime import datetime, timedelta, timezone as dt_timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import re
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo
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
from core.models import ExpenseTransaction, DeletedExpenseMessage, IncomeTransaction, UserProfile
from core.tool_guard import identity_bound
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


_MERCHANT_STOPWORDS = {
    "the", "and", "of", "at", "my", "card", "purchase", "payment", "transaction",
    "singapore", "pte", "ltd", "limited", "inc", "store", "online",
}


def _merchant_tokens(name: str) -> set:
    """Significant lowercase tokens of a merchant name for fuzzy comparison."""
    tokens = re.findall(r"[a-z0-9]{3,}", (name or "").lower())
    return {t for t in tokens if t not in _MERCHANT_STOPWORDS}


def _merchants_match(a: str, b: str) -> bool:
    """True when two merchant names plausibly refer to the same business."""
    ta, tb = _merchant_tokens(a), _merchant_tokens(b)
    if not ta or not tb:
        return False
    a_l, b_l = (a or "").lower().strip(), (b or "").lower().strip()
    if a_l in b_l or b_l in a_l:
        return True
    return len(ta & tb) >= 1


async def find_cross_source_duplicate(
    user_id: int,
    amount: float,
    currency: str,
    expense_date: datetime,
    sender_domain: str,
    merchant: str,
    body_text: str = "",
) -> Optional[ExpenseTransaction]:
    """
    Layer 3 Deduplication (semantic, cross-source): companies email a receipt while
    banks email a transaction alert for the SAME purchase. Match an incoming email
    against recent transactions by amount/currency/time-window plus fuzzy merchant
    identity, and only across DIFFERENT senders so repeat purchases at the same
    merchant still log normally.
    """
    domain = (sender_domain or "").lower()
    window_start = expense_date - timedelta(hours=24)
    window_end = expense_date + timedelta(hours=24)
    tolerance = max(0.02, abs(amount) * 0.01)

    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction).where(
                ExpenseTransaction.user_id == user_id,
                ExpenseTransaction.currency == currency,
                ExpenseTransaction.amount >= amount - tolerance,
                ExpenseTransaction.amount <= amount + tolerance,
                ExpenseTransaction.date >= window_start.replace(tzinfo=None),
                ExpenseTransaction.date <= window_end.replace(tzinfo=None),
            ).order_by(ExpenseTransaction.date.desc()).limit(20)
        )
        candidates = result.scalars().all()

    body_lower = (body_text or "").lower()
    for tx in candidates:
        existing_domain = (tx.source_sender_domain or "").lower()
        # Cross-source only: same-sender repeats are legitimate purchases.
        if domain and existing_domain and domain == existing_domain:
            continue
        if _merchants_match(merchant, tx.merchant):
            return tx
        # Bank alerts often extract the bank as merchant — look for the stored
        # merchant name inside the incoming email body instead.
        tx_merchant = (tx.merchant or "").strip()
        if len(tx_merchant) >= 4 and tx_merchant.lower() in body_lower:
            return tx
    return None

SPLIT_ALERT_THRESHOLD = 50.0

_MAX_EXTRACTED_DATE_DRIFT_DAYS = 15


def _reconcile_expense_date(
    extracted_dt: Optional[datetime],
    email_dt: Optional[datetime],
) -> datetime:
    """
    Reconcile the LLM-extracted transaction time with reality.

    Anchors: the email receive timestamp is always trustworthy; the extracted
    date is not (LLMs invent years, bank alert bodies contain account-year
    noise like 'member since 2022'). Anything more than 15 days away from the
    anchor is discarded. Date-only extractions adopt the anchor's time instead
    of surfacing as 00:00 rows.
    """
    anchor = email_dt or datetime.now(dt_timezone.utc).replace(tzinfo=None)
    if extracted_dt is None:
        return anchor

    try:
        drift_days = abs((extracted_dt - anchor).total_seconds()) / 86400.0
    except TypeError:
        # mixing naive/aware — normalize to naive UTC and retry
        return _reconcile_expense_date(_to_naive_utc(extracted_dt), _to_naive_utc(email_dt)) if email_dt else anchor

    if drift_days > _MAX_EXTRACTED_DATE_DRIFT_DAYS:
        return anchor

    extracted_naive = extracted_dt
    if hasattr(extracted_dt, "tzinfo") and extracted_dt.tzinfo:
        extracted_naive = extracted_dt.astimezone(dt_timezone.utc).replace(tzinfo=None)
    if (
        extracted_naive.hour == 0
        and extracted_naive.minute == 0
        and extracted_naive.second == 0
        and email_dt is not None
    ):
        # Date-only extraction + trustworthy email time -> merge both
        return datetime.combine(extracted_naive.date(), email_dt.time())
    return extracted_naive


def _to_naive_utc(dt_value: Optional[datetime]) -> Optional[datetime]:
    if dt_value is None:
        return None
    if dt_value.tzinfo is not None:
        return dt_value.astimezone(dt_timezone.utc).replace(tzinfo=None)
    return dt_value


async def _is_quiet_hours(user_id: int) -> bool:
    """True before the quiet-hours cutoff (09:00 local) — smart alerts stay low-intrusion."""
    from core.ambient import QUIET_HOUR_END
    from core.models import UserProfile

    tz_name = "Asia/Singapore"
    async with async_session_factory() as session:
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )).scalar_one_or_none()
        if profile and profile.current_timezone:
            tz_name = profile.current_timezone
    try:
        local = datetime.now(dt_timezone.utc).astimezone(ZoneInfo(tz_name))
    except Exception:
        return False
    return local.hour < QUIET_HOUR_END


async def _send_split_alert_batch(user_id: int, candidates: List[Dict[str, Any]]) -> set:
    """Send ONE consolidated Telegram alert with a Split Bill button per high-value expense."""
    from app.ingress import send_telegram_message

    # Format transaction times in the user's own timezone, not raw UTC.
    from core.models import UserProfile

    tz_name = "Asia/Singapore"
    async with async_session_factory() as session:
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )).scalar_one_or_none()
        if profile and profile.current_timezone:
            tz_name = profile.current_timezone
    try:
        local_tz = ZoneInfo(tz_name)
    except Exception:
        local_tz = ZoneInfo("UTC")

    def fmt(d: datetime) -> str:
        dt_val = d
        if dt_val.tzinfo is None:
            dt_val = dt_val.replace(tzinfo=dt_timezone.utc)
        return dt_val.astimezone(local_tz).strftime("%d %b %Y, %H:%M")

    alert_text = (
        f"💳 **New High-Value Expense{'s' if len(candidates) > 1 else ''} Logged**\n\n"
        + "\n".join(
            f"• {c['currency']} {c['amount']:.2f} — {c['merchant']} "
            f"(#{c['category']}) · {fmt(c['date'])}"
            for c in candidates
        )
        + "\n\nDid you foot the bill for a group? Split any of these:"
    )
    buttons = [
        [{"text": f"👥 Split {c['currency']} {c['amount']:.2f} — {c['merchant']}", "callback_data": f"sb:{c['tx_id']}"}]
        for c in candidates
    ]
    try:
        await send_telegram_message(
            chat_id=user_id,
            text=alert_text,
            reply_markup={"inline_keyboard": buttons},
        )
    except Exception as notify_err:
        print(f"[EXPENSES] Smart alert notification failed: {notify_err}")
        return set()
    return {c["tx_id"] for c in candidates}


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


def normalize_income_category(raw: Optional[str]) -> str:
    """Map incoming-money phrases to the categories used by the ledger."""
    value = (raw or "").strip().lower()
    if any(word in value for word in ("salary", "payroll", "wage", "bonus")):
        return "Salary"
    if any(word in value for word in ("repay", "repaid", "paid back", "paid me", "returned")):
        return "Friend Repayment"
    if any(word in value for word in ("reimburse", "refund")):
        return "Reimbursement"
    if any(word in value for word in ("claim", "insur")):
        return "Claim Payout"
    if "transfer" in value:
        return "Transfer"
    return "Other"


def parse_incoming_transaction_text(text: str) -> Optional[Dict[str, Any]]:
    """Parse an explicit incoming-money message into ledger fields."""
    normalized = " ".join((text or "").strip().split())
    lowered = normalized.lower()
    incoming_markers = (
        "received",
        "got paid",
        "salary",
        "payroll",
        "repaid",
        "paid me back",
        "paid me",
        "reimbursement",
        "reimbursed",
        "insurance claim",
        "claim payout",
        "refund",
        "credited",
    )
    if not any(marker in lowered for marker in incoming_markers):
        return None

    amount_match = re.search(
        r"(?:S\$|SGD|USD|EUR|MYR|JPY|\$)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)"
        r"|\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:SGD|USD|EUR|MYR|JPY)\b"
        r"|(?:^|\s)(?:received|credited|credit|salary|got paid)\s+([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        normalized,
        re.IGNORECASE,
    )
    if amount_match is None:
        return None
    raw_amount = amount_match.group(1) or amount_match.group(2) or amount_match.group(3) or ""
    amount = round(float(raw_amount.replace(",", "")), 2)

    currency = "SGD"
    currency_match = re.search(r"\b(SGD|USD|EUR|MYR|JPY)\b|S\$|\$", normalized, re.IGNORECASE)
    if currency_match:
        token = currency_match.group(0).upper()
        currency = "SGD" if token in {"$", "S$"} else token

    category = normalize_income_category(normalized)
    source = "Other"
    from_match = re.search(
        r"\bfrom\s+([A-Za-z][A-Za-z0-9 .&'_-]{1,79}?)(?:\s+(?:for|on|via|as)\b|$)",
        normalized,
        re.IGNORECASE,
    )
    repaid_match = re.search(
        r"^([A-Za-z][A-Za-z0-9 .&'_-]{1,79}?)\s+(?:already\s+)?(?:repaid|paid me back|paid me|returned)\b",
        normalized,
        re.IGNORECASE,
    )
    if from_match:
        source = from_match.group(1).strip(" .,-").title()
    elif repaid_match:
        source = repaid_match.group(1).strip(" .,-").title()
    elif category == "Salary":
        source = "Employer"
    elif category == "Claim Payout":
        source = "Insurer"
    elif category == "Reimbursement":
        source = "Reimbursement"

    if category == "Claim Payout" and source.lower().endswith(" claim"):
        source = source[:-6].strip()

    transaction_date = datetime.now(dt_timezone.utc)
    if re.search(r"\byesterday\b", lowered):
        transaction_date -= timedelta(days=1)

    return {
        "amount": amount,
        "currency": currency,
        "source": source,
        "category": category,
        "date_iso": transaction_date.isoformat(),
        "notes": normalized,
    }


def income_source_id(user_id: int, text: str) -> str:
    """Build a stable Telegram deduplication key for an incoming transaction."""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return f"tg-income-{user_id}-{digest}"


async def is_duplicate_income(source_message_id: Optional[str]) -> bool:
    """Return whether an incoming transaction source was already recorded."""
    if not source_message_id:
        return False
    async with async_session_factory() as session:
        result = await session.execute(
            select(IncomeTransaction).where(
                IncomeTransaction.source_message_id == source_message_id
            )
        )
        return result.scalar_one_or_none() is not None


async def save_income_transaction(
    user_id: int,
    income: Dict[str, Any],
    source_message_id: Optional[str] = None,
) -> IncomeTransaction:
    """Persist parsed incoming-money fields for one user."""
    async with async_session_factory() as session:
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )).scalar_one_or_none()
        if profile is None:
            session.add(
                UserProfile(
                    user_id=user_id,
                    telegram_chat_id=user_id,
                    current_timezone="Asia/Singapore",
                )
            )
            await session.flush()

        parsed_date = income.get("date") or income.get("date_iso")
        try:
            income_date = datetime.fromisoformat(str(parsed_date).replace("Z", "+00:00"))
        except ValueError:
            income_date = datetime.now(dt_timezone.utc)
        if income_date.tzinfo is not None:
            income_date = income_date.astimezone(dt_timezone.utc).replace(tzinfo=None)

        item = IncomeTransaction(
            user_id=user_id,
            amount=round(float(income["amount"]), 2),
            currency=str(income.get("currency") or "SGD").strip().upper(),
            source=str(income.get("source") or "Other").strip(),
            category=normalize_income_category(str(income.get("category") or "Other")),
            date=income_date,
            notes=str(income.get("notes") or "").strip() or None,
            source_message_id=source_message_id,
            linked_expense_id=income.get("linked_expense_id"),
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


async def save_expense_transaction(
    user_id: int,
    expense: ExtractedExpense,
    source_message_id: Optional[str] = None,
    is_verified: bool = True,
    source_sender_domain: Optional[str] = None,
    logged_at: Optional[datetime] = None,
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
            source_sender_domain=(source_sender_domain or "").lower() or None,
            logged_at=logged_at,
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
async def extract_expense_from_text(user_text: str, recent_context: str = "") -> Dict[str, Any]:
    """
    Extract structured expense fields from a natural-language message.
    Returns amount, currency, merchant, category, date_iso, confidence, needs_clarification.

    recent_context (#35): the last few conversation turns, used ONLY to
    resolve an explicit correction/follow-up on the CURRENT message (e.g.
    "actually make that $20" right after "logged $15 for lunch") -- this is
    a money-writing path, so it must never be used to invent a transaction
    the current message doesn't itself describe. See rule 6 below.
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
                '4. date_iso: the transaction date must be within 14 days of the email\'s own timestamp or the current date. NEVER invent a year or copy a year from account numbers, membership dates (e.g. "member since 2022") or reference IDs. If the message shows only day/month (e.g. "22 Aug"), use the current year; if no transaction date is shown at all, return "".\n'
                "5. Reply with ONLY a JSON object:\n"
                '{"amount": number|null, "currency": string, "merchant": string, "category": string, "date_iso": string, "confidence": number, "needs_clarification": boolean}\n'
                "Default currency: SGD for Singapore.\n"
                "6. A 'Recent conversation' block, if present below, is ONLY for resolving an "
                "explicit correction to the CURRENT message (e.g. 'actually make that $20' "
                "referring back to an amount just discussed). NEVER use it to extract an "
                "expense the current message does not itself describe -- if the current "
                "message alone has no genuine paid expense, return {\"amount\": null} "
                "regardless of what the recent conversation contains."
            )
        ),
        HumanMessage(
            content=(
                (f"Recent conversation:\n{recent_context}\n\n---\n\n" if recent_context else "")
                + user_text[:2000]
            )
        ),
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
    Classify a photo and, only if it's actually a receipt, extract structured
    expense fields from it using Gemini vision.

    Returns amount, currency, merchant, category, date_iso, confidence,
    needs_clarification when it's a receipt. When it isn't, amount is None
    and `description` carries a one-line description of what the image
    actually shows (a points/rewards balance, a screenshot, a random photo,
    etc.) so the caller can respond honestly instead of assuming every photo
    is a failed receipt scan.
    """
    if (
        not settings.active_gemini_api_key
        or settings.active_gemini_api_key == "test_google_key"
    ):
        return {"amount": None, "description": None}

    llm = get_multimodal_llm(temperature=0.1)
    prompt_text = (
        caption
        or "Look at this photo. If it's a receipt, extract the expense; otherwise describe what it shows."
    )
    ai_message = await llm.ainvoke(
        [
            SystemMessage(
                content=(
                    "You look at a photo and first decide whether it is a purchase "
                    "receipt/invoice with a legible total, or something else entirely "
                    "(e.g. a rewards/points/miles balance, a screenshot, an unrelated "
                    "photo). Do not assume it is a receipt just because you were asked "
                    "to look at it. Reply with ONLY a JSON object: "
                    '{"amount": number|null, "currency": string (3-letter code, default SGD), '
                    '"merchant": string, "category": string, "date_iso": string (ISO 8601 with time and timezone if mentioned, e.g. 2026-08-16T14:32:00, or YYYY-MM-DD), '
                    '"confidence": number 0-1, "needs_clarification": boolean, '
                    '"description": string}. '
                    "If it IS a legible receipt, read the TOTAL and fill amount/currency/merchant/etc. "
                    "If it is NOT a receipt (or the total isn't legible), set amount to null and "
                    "put a short, specific description of what the photo actually shows in "
                    "'description' (e.g. \"a DBS rewards points balance screenshot\") — "
                    "never leave description generic like \"an image\"."
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
            return {"amount": None, "description": parsed.get("description") or None}
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
        return {"amount": None, "description": None}


async def extract_itemized_receipt_from_image(
    image_b64: str,
    mime_type: str = "image/jpeg",
) -> Dict[str, Any]:
    """
    Extract itemized dishes/groceries, prices, subtotal, tax, service charge, and total
    from a receipt photo using Gemini Multimodal Vision.
    """
    if (
        not settings.active_gemini_api_key
        or settings.active_gemini_api_key == "test_google_key"
    ):
        return {
            "merchant": "Receipt Merchant",
            "category": "Dining",
            "items": [],
            "subtotal": 0.0,
            "service_charge_pct": 10.0,
            "tax_pct": 9.0,
            "discount": 0.0,
            "total": 0.0,
        }

    try:
        llm = get_multimodal_llm(temperature=0.1)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "You are an expert financial receipt OCR engine. Analyze this receipt photo and extract all individual line items. "
                        "Return ONLY a valid JSON object matching this schema:\n"
                        "{\n"
                        '  "merchant": string,\n'
                        '  "category": string (Dining, Groceries, Shopping, Transport, Bills, General),\n'
                        '  "date_iso": string,\n'
                        '  "currency": string (e.g. SGD, USD, EUR),\n'
                        '  "items": [\n'
                        '    {"name": string, "price": number, "quantity": number}\n'
                        '  ],\n'
                        '  "subtotal": number,\n'
                        '  "service_charge_pct": number,\n'
                        '  "tax_pct": number,\n'
                        '  "discount": number,\n'
                        '  "total": number\n'
                        "}\n"
                        "Extract all items legibly. If no items or receipt found, return empty items list."
                    )
                ),
                HumanMessage(
                    content=[
                        {"type": "text", "text": "Extract itemized receipt line items and tax/service charges."},
                        {"type": "media", "mime_type": mime_type, "data": image_b64},
                    ]
                ),
            ]
        )
        raw = extract_llm_text(getattr(ai_message, "content", ""))
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        items = []
        for it in parsed.get("items", []):
            if isinstance(it, dict) and it.get("name") and it.get("price") is not None:
                items.append({
                    "name": str(it.get("name")),
                    "price": float(it.get("price", 0)),
                    "quantity": int(it.get("quantity", 1)),
                    "assigned_to": it.get("assigned_to") or [],
                })
        
        subtotal = float(parsed.get("subtotal") or sum(it["price"] * it["quantity"] for it in items))
        svc_pct = float(parsed.get("service_charge_pct") or (10.0 if parsed.get("service_charge_amount") else 0.0))
        tax_pct = float(parsed.get("tax_pct") or (9.0 if parsed.get("tax_amount") else 0.0))
        discount = float(parsed.get("discount") or 0.0)
        total = float(parsed.get("total") or (subtotal * (1 + svc_pct/100) * (1 + tax_pct/100) - discount))

        return {
            "merchant": parsed.get("merchant") or "Unknown Merchant",
            "category": parsed.get("category") or "Dining",
            "date_iso": parsed.get("date_iso") or "",
            "currency": parsed.get("currency") or "SGD",
            "items": items,
            "subtotal": round(subtotal, 2),
            "service_charge_pct": svc_pct,
            "tax_pct": tax_pct,
            "discount": round(discount, 2),
            "total": round(total, 2),
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[EXPENSES] itemized receipt OCR failed: {exc}")
        return {
            "merchant": "Unknown Merchant",
            "category": "Dining",
            "items": [],
            "subtotal": 0.0,
            "service_charge_pct": 10.0,
            "tax_pct": 9.0,
            "discount": 0.0,
            "total": 0.0,
        }


def calculate_bill_split(
    items: List[Dict[str, Any]],
    friends: List[str],
    service_charge_pct: float = 10.0,
    tax_pct: float = 9.0,
    discount: float = 0.0,
    total_inclusive: bool = False,
) -> Dict[str, Any]:
    """
    Calculate proportional item-by-item split with service charge and tax distribution.
    """
    if not friends:
        friends = ["Me"]

    friend_subtotals = {f: 0.0 for f in friends}
    friend_items = {f: [] for f in friends}

    for it in items:
        price = float(it.get("price", 0.0)) * int(it.get("quantity", 1))
        assigned = it.get("assigned_to") or []
        # Filter assigned to only valid friends in list
        valid_assigned = [f for f in assigned if f in friends]
        if not valid_assigned:
            valid_assigned = friends  # Split across all if unassigned

        split_share = price / len(valid_assigned)
        for f in valid_assigned:
            friend_subtotals[f] += split_share
            friend_items[f].append({
                "name": it.get("name", "Item"),
                "share_price": round(split_share, 2),
                "is_shared": len(valid_assigned) > 1,
                "shared_with_count": len(valid_assigned),
            })

    total_subtotal = sum(friend_subtotals.values()) or 1.0

    breakdown = []
    for f in friends:
        sub = friend_subtotals[f]
        ratio = sub / total_subtotal if total_subtotal > 0 else (1.0 / len(friends))
        svc_amount = 0.0 if total_inclusive else sub * (service_charge_pct / 100.0)
        tax_amount = 0.0 if total_inclusive else (sub + svc_amount) * (tax_pct / 100.0)
        disc_share = discount * ratio
        friend_total = max(0.0, sub + svc_amount + tax_amount - disc_share)

        breakdown.append({
            "name": f,
            "subtotal": round(sub, 2),
            "service_charge": round(svc_amount, 2),
            "tax": round(tax_amount, 2),
            "discount": round(disc_share, 2),
            "total": round(friend_total, 2),
            "items": friend_items[f],
        })

    if total_inclusive and breakdown:
        # Currency rounding can otherwise make an even split of e.g. $37.05
        # display as $18.52 + $18.52 = $37.04. Put the cent remainder on the
        # final participant so displayed shares always reconcile to the bill.
        target_cents = round(max(0.0, total_subtotal - discount) * 100)
        rounded_cents = sum(round(b["total"] * 100) for b in breakdown)
        remainder_cents = target_cents - rounded_cents
        if remainder_cents:
            last = breakdown[-1]
            last["total"] = round((round(last["total"] * 100) + remainder_cents) / 100, 2)

    return {
        "friends": breakdown,
        "total_bill": round(sum(b["total"] for b in breakdown), 2),
        "service_charge_pct": service_charge_pct,
        "tax_pct": tax_pct,
        "discount": discount,
        "total_inclusive": total_inclusive,
    }


def expense_source_id(user_id: int, text: str) -> str:
    """Stable dedup key for an expense logged from a Telegram message."""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    return f"tg-{user_id}-{digest}"


@tool
@identity_bound
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
                "date": row.date.isoformat() + "+00:00",
                "verified": row.is_verified,
            }
            for row in rows
        ]


async def _parse_ledger_date(value: Optional[str]) -> Optional[datetime]:
    """Normalize an ISO date string to naive UTC for TIMESTAMP WITHOUT TIME ZONE columns."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(dt_timezone.utc).replace(tzinfo=None)
    return parsed


async def query_unified_transactions(
    user_id: int,
    direction: str = "all",
    categories: Optional[List[str]] = None,
    since_date: Optional[str] = None,
    until_date: Optional[str] = None,
    search_text: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Read both money-out (ExpenseTransaction) and money-in (IncomeTransaction) tables
    through one normalized contract. Shared by the dashboard API and the agent-side
    query_transactions tool so filters behave identically on every surface.

    Returns structured data: per-direction totals/counts by currency, net cashflow
    per currency, and up to `limit` merged item rows ordered newest-first.
    """
    from sqlmodel import or_

    since_dt = await _parse_ledger_date(since_date)
    until_dt = await _parse_ledger_date(until_date)
    wanted_directions = {"outgoing", "incoming"} if direction == "all" else {direction}
    pattern = f"%{search_text}%" if search_text else None

    outgoing_items: List[Dict[str, Any]] = []
    incoming_items: List[Dict[str, Any]] = []

    async with async_session_factory() as session:
        if "outgoing" in wanted_directions:
            expense_query = select(ExpenseTransaction).where(
                ExpenseTransaction.user_id == user_id
            )
            if categories:
                expense_query = expense_query.where(
                    or_(*[ExpenseTransaction.category == cat for cat in categories])
                )
            if since_dt:
                expense_query = expense_query.where(ExpenseTransaction.date >= since_dt)
            if until_dt:
                expense_query = expense_query.where(ExpenseTransaction.date < until_dt)
            if pattern:
                expense_query = expense_query.where(
                    or_(
                        ExpenseTransaction.merchant.ilike(pattern),
                        ExpenseTransaction.category.ilike(pattern),
                    )
                )
            expense_rows = (
                await session.execute(expense_query.order_by(ExpenseTransaction.date.desc()))
            ).scalars().all()
            outgoing_items = [
                {
                    "direction": "outgoing",
                    "title": row.merchant,
                    "amount": float(row.amount),
                    "currency": row.currency,
                    "category": row.category,
                    "date": row.date.isoformat(),
                }
                for row in expense_rows
            ]

        if "incoming" in wanted_directions:
            income_query = select(IncomeTransaction).where(
                IncomeTransaction.user_id == user_id
            )
            if categories:
                income_query = income_query.where(
                    or_(*[IncomeTransaction.category == cat for cat in categories])
                )
            if since_dt:
                income_query = income_query.where(IncomeTransaction.date >= since_dt)
            if until_dt:
                income_query = income_query.where(IncomeTransaction.date < until_dt)
            if pattern:
                income_query = income_query.where(
                    or_(
                        IncomeTransaction.source.ilike(pattern),
                        IncomeTransaction.category.ilike(pattern),
                        IncomeTransaction.notes.ilike(pattern),
                    )
                )
            income_rows = (
                await session.execute(income_query.order_by(IncomeTransaction.date.desc()))
            ).scalars().all()
            incoming_items = [
                {
                    "direction": "incoming",
                    "title": row.source,
                    "amount": float(row.amount),
                    "currency": row.currency,
                    "category": row.category,
                    "date": row.date.isoformat(),
                }
                for row in income_rows
            ]

    def _totals(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for item in items:
            bucket = grouped.setdefault(item["currency"], {"total": 0.0, "count": 0})
            bucket["total"] += item["amount"]
            bucket["count"] += 1
        return grouped

    items = sorted(outgoing_items + incoming_items, key=lambda row: row["date"], reverse=True)
    outgoing_totals = _totals(outgoing_items)
    incoming_totals = _totals(incoming_items)
    currencies = sorted(set(outgoing_totals) | set(incoming_totals))
    net = {
        currency: round(
            incoming_totals.get(currency, {}).get("total", 0.0)
            - outgoing_totals.get(currency, {}).get("total", 0.0),
            2,
        )
        for currency in currencies
    }
    return {
        "direction": direction,
        "money_out": outgoing_totals,
        "money_in": incoming_totals,
        "net": net,
        "items": items[: max(1, limit)],
        "total_matched": len(items),
    }




@tool
@identity_bound
async def log_expenses_from_emails(
    user_id: int,
    emails: List[Dict[str, Any]],
    notify: bool = True,
) -> Dict[str, Any]:
    """
    Auto-extract and log expenses from fetched email messages.
    Each email ID becomes the dedup key, so re-checking the inbox never double-logs.
    Ambiguous or low-confidence emails are skipped (never sent to HITL buttons).
    High-value expenses (>= $50) are surfaced as ONE consolidated Telegram alert per run
    with a Split Bill shortcut; quiet-hour runs skip the push entirely.
    """
    logged: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    deduped: List[Dict[str, Any]] = []
    alert_candidates: List[Dict[str, Any]] = []

    def _sender_domain(raw_sender: str) -> str:
        m = re.search(r"@([\w\.-]+)", raw_sender or "")
        return (m.group(1) if m else "").lower()

    for email_msg in (emails or [])[:10]:
        email_id = str(email_msg.get("id") or "")
        sender = str(email_msg.get("sender") or "")
        subject = str(email_msg.get("subject") or "")
        body_text = str(email_msg.get("body") or email_msg.get("snippet") or "")
        snippet = str(email_msg.get("snippet") or "")
        sender_domain = _sender_domain(sender)

        # Avoid re-running extraction on messages already logged. This matters
        # because each poll searches a rolling seven-day window and Gmail may
        # not allow the Assistant/Processed label to be applied.
        if email_id and await is_duplicate_expense(email_id):
            continue

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

        # Trustworthy anchor (email receive time) + drift-guarded extracted date
        reconciled = _reconcile_expense_date(extracted_dt, email_dt)
        if hasattr(reconciled, "tzinfo") and reconciled.tzinfo:
            reconciled = reconciled.astimezone(dt_timezone.utc).replace(tzinfo=None)
        expense_date = _to_naive_utc(reconciled)

        # Layer 3: the same purchase often arrives twice — a receipt from the
        # merchant AND a transaction alert from the bank. Log it once.
        cross_dup = await find_cross_source_duplicate(
            user_id=user_id,
            amount=float(extracted["amount"]),
            currency=extracted.get("currency") or "SGD",
            expense_date=expense_date,
            sender_domain=sender_domain,
            merchant=merchant,
            body_text=body_text,
        )
        if cross_dup is not None:
            deduped.append(
                {
                    "amount": float(extracted["amount"]),
                    "currency": extracted.get("currency", "SGD"),
                    "merchant": merchant,
                    "matched_transaction_id": cross_dup.id,
                    "source_message_id": email_id,
                }
            )
            if email_id:
                # Mark processed so this email is never re-scanned
                try:
                    provider = email_msg.get("provider", "gmail")
                    await apply_email_processed_tag.ainvoke(
                        {"user_id": user_id, "message_id": email_id, "provider": provider}
                    )
                except Exception as tag_err:
                    print(f"[EXPENSES] Failed to tag deduped email {email_id}: {tag_err}")
            continue

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
            source_sender_domain=sender_domain or None,
            logged_at=datetime.utcnow(),
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
        if expense.amount >= SPLIT_ALERT_THRESHOLD:
            alert_candidates.append(
                {
                    "tx_id": tx.id,
                    "amount": expense.amount,
                    "currency": expense.currency,
                    "merchant": expense.merchant,
                    "category": expense.category,
                    "date": expense.date,
                }
            )

        logged.append(
            {
                "amount": expense.amount,
                "currency": expense.currency,
                "merchant": expense.merchant,
                "category": expense.category,
                "transaction_id": tx.id,
            }
        )

    # Batch all high-value alerts into ONE message per run (no per-email bursts),
    # and skip pushes entirely during quiet hours (before 09:00 local).
    notified_ids: set = set()
    if notify and alert_candidates and not await _is_quiet_hours(user_id):
        notified_ids = await _send_split_alert_batch(user_id, alert_candidates)
    for item in logged:
        item["notified"] = item["transaction_id"] in notified_ids

    return {"logged": logged, "skipped": skipped, "deduped": deduped}

@tool
@identity_bound
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
@identity_bound
async def record_incoming_money(text: str, user_id: int = 0) -> str:
    """
    Record money the user received (salary, refund, reimbursement, or a
    friend repaying an IOU) -- e.g. "got my salary $4200", "Loren paid me
    back $13", "received a $20 refund from Grab". Deterministically extracts
    structured fields (amount/source/category) from the text; if the
    category is a friend repayment, this settles the matching open IOU
    (from split_bill_expense) instead of just logging a generic income row.
    Deduped by message text, so re-processing the same message never
    double-logs. Do NOT use this for the user's own spending -- that's
    process_extracted_expense.

    Args:
        text: the user's natural-language incoming-money message.
        user_id: ignored; the assistant injects the authenticated user's ID.
    """
    uid = int(user_id or 0)
    parsed = parse_incoming_transaction_text(text)
    if parsed is None:
        return "[income] Couldn't find an incoming-money statement in that text."

    source_id = income_source_id(uid, text)

    if parsed.get("category") == "Friend Repayment":
        from capabilities.expenses.settlement import settle_matching_iou

        received_at = None
        try:
            received_at = datetime.fromisoformat(
                str(parsed.get("date_iso") or "").replace("Z", "+00:00")
            )
        except ValueError:
            pass
        settlement = await settle_matching_iou(
            user_id=uid,
            participant=str(parsed.get("source") or ""),
            amount=float(parsed.get("amount") or 0.0),
            received_at=received_at,
            notes=str(parsed.get("notes") or "").strip() or None,
        )
        if settlement is not None and settlement.get("status") in {
            "settled",
            "partially_settled",
            "already_settled",
        }:
            status = settlement["status"]
            if status == "already_settled":
                return (
                    f"{settlement['participant']}'s repayment is already marked as paid "
                    f"({settlement['currency']} {settlement['amount_due']:.2f})."
                )
            if status == "partially_settled":
                outstanding = settlement["amount_due"] - settlement["total_received"]
                return (
                    f"Logged {settlement['currency']} {settlement['amount_received']:.2f} from "
                    f"{settlement['participant']}. Their IOU still has "
                    f"{settlement['currency']} {outstanding:.2f} outstanding."
                )
            return (
                f"Logged {settlement['currency']} {settlement['amount_received']:.2f} from "
                f"{settlement['participant']} and marked their IOU as paid."
            )
        # No matching open IOU -- fall through to a plain income record below.

    if await is_duplicate_income(source_id):
        return "[income] That incoming transaction is already logged."

    item = await save_income_transaction(user_id=uid, income=parsed, source_message_id=source_id)
    return f"Logged {item.currency} {item.amount:.2f} from {item.source} ({item.category})."


@tool
@identity_bound
async def split_bill_expense(
    user_id: int,
    total_amount: float,
    merchant: str = "Dinner / Event",
    people: Optional[List[str]] = None,
    people_count: Optional[int] = None,
    transaction_id: Optional[int] = None,
    custom_amounts: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Split an expense among friends, generate copy-pastable WhatsApp group text,
    and create 1-tap IOU collection tasks.

    The parent expense remains at the gross bill total for ledger accuracy. The
    user's personal share and friend receivables are stored in split_data.
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

    normalized_amounts: Dict[str, float] = {}
    if custom_amounts:
        # Custom amounts are final amounts due and must explicitly include the
        # user's own share ("Me") plus every friend being split with.
        for raw_name, raw_amount in custom_amounts.items():
            name = str(raw_name).strip().title()
            if name.lower() in {"me", "myself", "i", "you", "user"}:
                name = "Me"
            try:
                amount = round(float(raw_amount), 2)
            except (TypeError, ValueError):
                return {
                    "status": "needs_adjustment",
                    "message": f"I couldn't read the amount assigned to {raw_name!r}.",
                }
            if amount < 0:
                return {
                    "status": "needs_adjustment",
                    "message": "Custom shares cannot be negative.",
                }
            normalized_amounts[name] = amount
            if name != "Me" and name not in unique_friends:
                unique_friends.append(name)

        expected_people = ["Me", *unique_friends]
        missing_people = [name for name in expected_people if name not in normalized_amounts]
        if missing_people:
            return {
                "status": "needs_adjustment",
                "message": "Enter a final amount for everyone: " + ", ".join(missing_people) + ".",
                "amounts": normalized_amounts,
            }
        amount_sum = round(sum(normalized_amounts[name] for name in expected_people), 2)
        if abs(amount_sum - round(total_amount, 2)) > 0.01:
            return {
                "status": "needs_adjustment",
                "message": (
                    f"Custom shares total ${amount_sum:.2f}, but the bill is ${total_amount:.2f}. "
                    f"Adjust the shares by ${round(total_amount - amount_sum, 2):.2f}."
                ),
                "amounts": normalized_amounts,
            }

    total_splits = len(unique_friends) + 1
    if total_splits < 2:
        total_splits = 2
        unique_friends = ["Friend 1"]

    per_person = None
    if normalized_amounts:
        my_share = normalized_amounts["Me"]
    else:
        per_person = round(total_amount / total_splits, 2)
        my_share = round(total_amount - (per_person * len(unique_friends)), 2)

    share_amounts = {
        "Me": my_share,
        **{
            friend: normalized_amounts.get(friend, per_person) or 0.0
            for friend in unique_friends
        },
    }
    created_tasks = []
    task_ids: Dict[str, int] = {}
    async with async_session_factory() as session:
        # 1. Keep the parent transaction at the gross total and attach the
        # split ledger so the dashboard can show both views.
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

        if target_tx is None:
            target_tx = ExpenseTransaction(
                user_id=user_id,
                amount=round(total_amount, 2),
                currency="SGD",
                merchant=merchant,
                category="Dining",
                date=datetime.utcnow(),
                is_verified=True,
            )
            session.add(target_tx)
            await session.flush()

        existing_split = dict(target_tx.split_data or {})
        existing_paid_status = dict(existing_split.get("paid_status") or {})
        existing_paid_amounts = dict(existing_split.get("paid_amounts") or {})
        existing_task_ids = dict(existing_split.get("task_ids") or {})
        paid_status = {
            "Me": True,
            **{
                friend: bool(existing_paid_status.get(friend, False))
                for friend in unique_friends
            },
        }
        paid_amounts = {
            "Me": my_share,
            **{
                friend: (
                    share_amounts[friend]
                    if paid_status[friend]
                    else round(float(existing_paid_amounts.get(friend, 0.0)), 2)
                )
                for friend in unique_friends
            },
        }
        target_tx.amount = round(total_amount, 2)
        target_tx.split_data = {
            **existing_split,
            "friends": ["Me", *unique_friends],
            "paid_status": paid_status,
            "paid_amounts": paid_amounts,
            "task_ids": existing_task_ids,
            "is_even": not bool(normalized_amounts),
            "split_mode": "custom" if normalized_amounts else "even",
            "custom_amounts": normalized_amounts or None,
            "share_amounts": share_amounts,
            "gross_total": round(total_amount, 2),
            "my_share": my_share,
        }
        session.add(target_tx)

        # 2. Create IOU tasks for each friend
        for friend in unique_friends:
            owed_amount = normalized_amounts.get(friend, per_person)
            if not owed_amount or owed_amount <= 0:
                continue
            existing_task = None
            existing_task_id = existing_task_ids.get(friend)
            if existing_task_id:
                existing_task = (await session.execute(
                    select(TaskItem).where(
                        TaskItem.id == existing_task_id,
                        TaskItem.user_id == user_id,
                    )
                )).scalar_one_or_none()
            if existing_task is None:
                existing_task = (await session.execute(
                    select(TaskItem).where(
                        TaskItem.user_id == user_id,
                        TaskItem.linked_expense_id == target_tx.id,
                        TaskItem.iou_friend == friend,
                    )
                )).scalars().first()

            iou_task = existing_task or TaskItem(
                user_id=user_id,
                title=f"Collect ${owed_amount:.2f} from {friend} for {merchant}",
                priority="medium",
                status="done" if paid_status[friend] else "todo",
                reminder_type="none",
                description=f"Bill split from ${total_amount:.2f} total ({total_splits} people).",
                linked_expense_id=target_tx.id,
                iou_friend=friend,
                iou_amount=owed_amount,
            )
            iou_task.title = f"Collect ${owed_amount:.2f} from {friend} for {merchant}"
            iou_task.description = f"Bill split from ${total_amount:.2f} total ({total_splits} people)."
            iou_task.linked_expense_id = target_tx.id
            iou_task.iou_friend = friend
            iou_task.iou_amount = owed_amount
            if paid_status[friend]:
                iou_task.status = "done"
                iou_task.completed_at = iou_task.completed_at or datetime.utcnow()
                iou_task.is_reminder_active = False
            session.add(iou_task)
            await session.flush()
            task_ids[friend] = iou_task.id
            created_tasks.append({
                "task_id": iou_task.id,
                "friend": friend,
                "amount": owed_amount,
            })

        target_tx.split_data = {
            **(target_tx.split_data or {}),
            "task_ids": task_ids,
        }
        session.add(target_tx)

        await session.commit()

    # Format copy-paste text for WhatsApp / Telegram group chat
    breakdown_lines = [
        f"• {friend}: **${(normalized_amounts.get(friend, per_person) or 0.0):.2f}**"
        for friend in unique_friends
    ]
    breakdown_lines.append(f"• You: **${my_share:.2f}** *(Paid)*")

    copy_paste_lines = [
        f"{friend}: ${(normalized_amounts.get(friend, per_person) or 0.0):.2f}"
        for friend in unique_friends
    ]
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
        + f"💡 *Kept your dashboard expense at the full **${total_amount:.2f}** and recorded your **${my_share:.2f}** share, with {len(created_tasks)} IOU tasks below.*"
    )

    buttons = [[{"text": f"✅ {t['friend']} Paid (${t['amount']:.2f})", "callback_data": f"td:{t['task_id']}"}] for t in created_tasks]

    return {
        "status": "ok",
        "total_amount": total_amount,
        "my_share": my_share,
        "per_person": per_person,
        "custom_amounts": normalized_amounts or None,
        "friends": unique_friends,
        "tasks": created_tasks,
        "reply_text": full_reply,
        "buttons": buttons,
    }
