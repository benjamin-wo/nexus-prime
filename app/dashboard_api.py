"""Dashboard API router for Nexus Prime.

Provides REST endpoints for querying and managing personal assistant data:
- Expenses: Summary statistics, category breakdowns, merchant rankings, and transaction logs.
- Reminders & Scheduled Jobs: Active APScheduler tasks, dynamic timezones, and manual triggers.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Literal, Optional, assert_never
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select, delete, func, desc
from sqlalchemy import or_

from core.db import async_session_factory
from core.config import settings
from core.models import (
    ExpenseTransaction,
    IncomeTransaction,
    DeletedExpenseMessage,
    UserProfile,
    TaskItem,
)
from core.scheduler import (
    list_active_jobs,
    run_now,
    delete_scheduled_job,
    _add_task_to_scheduler,
    remove_task_reminder,
    snooze_task_reminder,
    trigger_task_alert_now,
)
from capabilities.expenses.settlement import IouSettlementCommand, settle_iou

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExpenseCreateRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Expense amount")
    currency: str = Field(default="SGD", description="3-letter currency code")
    merchant: str = Field(..., description="Store or merchant name")
    category: str = Field(default="General", description="Expense category")
    date: Optional[str] = Field(default=None, description="ISO timestamp or date string")
    notes: Optional[str] = Field(default=None, max_length=500)
    user_id: Optional[int] = Field(default=999999, description="Target user ID")


class ExpenseUpdateRequest(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0, description="Expense amount")
    currency: Optional[str] = Field(default=None, description="3-letter currency code")
    merchant: Optional[str] = Field(default=None, description="Store or merchant name")
    category: Optional[str] = Field(default=None, description="Expense category")
    date: Optional[str] = Field(default=None, description="ISO timestamp or date string")
    notes: Optional[str] = Field(default=None, max_length=500)


class IncomeCreateRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Incoming amount")
    currency: str = Field(default="SGD", description="3-letter currency code")
    source: str = Field(..., min_length=1, max_length=120, description="Who or where the money came from")
    category: str = Field(default="Other", max_length=40, description="Salary, repayment, reimbursement, claim, or other")
    date: Optional[str] = Field(default=None, description="ISO timestamp or date string")
    notes: Optional[str] = Field(default=None, max_length=500, description="Optional context")
    user_id: Optional[int] = Field(default=999999, description="Target user ID")


class IncomeUpdateRequest(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0, description="Incoming amount")
    currency: Optional[str] = Field(default=None, description="3-letter currency code")
    source: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = Field(default=None, max_length=40)
    date: Optional[str] = Field(default=None, description="ISO timestamp or date string")
    notes: Optional[str] = Field(default=None, max_length=500)


class TransactionCreateRequest(BaseModel):
    direction: Literal["outgoing", "incoming"] = "outgoing"
    amount: float = Field(..., gt=0)
    currency: str = Field(default="SGD", min_length=3, max_length=3)
    counterparty: str = Field(..., min_length=1, max_length=120)
    category: str = Field(default="Other", max_length=40)
    date: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None, max_length=500)
    user_id: Optional[int] = Field(default=999999)


class TransactionUpdateRequest(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)
    counterparty: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = Field(default=None, max_length=40)
    date: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None, max_length=500)


class IouSettlementRequest(BaseModel):
    participant: str = Field(..., min_length=1, max_length=120)
    amount: Optional[float] = Field(default=None, gt=0)


class TaskCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Task title")
    description: Optional[str] = Field(default=None, description="Task description or notes")
    priority: str = Field(default="medium", description="Priority: low, medium, high")
    due_at: Optional[str] = Field(default=None, description="ISO timestamp for due date")
    reminder_type: str = Field(default="none", description="none, once, recurring")
    reminder_time: Optional[str] = Field(default=None, description="ISO timestamp for reminder")
    cron_expression: Optional[str] = Field(default=None, description="5-field cron expression")
    timezone: str = Field(default="Asia/Singapore", description="IANA timezone")
    user_id: Optional[int] = Field(default=None, description="Target user ID")


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    status: Optional[str] = Field(default=None)  # "todo" | "done"
    priority: Optional[str] = Field(default=None)
    due_at: Optional[str] = Field(default=None)
    reminder_type: Optional[str] = Field(default=None)
    reminder_time: Optional[str] = Field(default=None)
    cron_expression: Optional[str] = Field(default=None)
    timezone: Optional[str] = Field(default=None)
    is_reminder_active: Optional[bool] = Field(default=None)


# ---------------------------------------------------------------------------
# 1. Expenses & Summary Endpoints
# ---------------------------------------------------------------------------

def normalize_category(raw_category: Optional[str]) -> str:
    """Normalize raw/variant category strings into clean canonical groups:
    Dining, Groceries, Transport, Shopping, Bills, General."""
    if not raw_category:
        return "General"
    c = raw_category.strip().lower()
    
    # Dining & Food / Drink
    if any(k in c for k in ["dining", "food", "restaurant", "cafe", "hawker", "beverage", "drink", "coffee", "meal", "bar", "cider", "bakery"]):
        return "Dining"
    
    # Groceries & Supermarkets & Convenience Stores
    if any(k in c for k in ["grocer", "supermarket", "mart", "fairprice", "cold storage", "shengsiong", "convenience", "7-eleven", "cheers"]):
        return "Groceries"
    
    # Transport & Transit & Ride-hailing
    if any(k in c for k in ["transport", "transit", "bus", "mrt", "grab", "taxi", "gojek", "comfort", "ride"]):
        return "Transport"
    
    # Shopping & Retail & Fashion
    if any(k in c for k in ["shop", "retail", "uniqlo", "clothes", "apparel", "electronics", "amazon", "lazada", "shopee", "department"]):
        return "Shopping"
    
    # Bills & Utilities & Subscriptions
    if any(k in c for k in ["bill", "utilit", "telco", "singtel", "starhub", "subscri", "netflix", "spotify", "rent", "insurance", "telecom"]):
        return "Bills"
    
    # Other & Unknown
    if c in ["other", "unknown", "misc", "miscellaneous"]:
        return "General"
        
    return raw_category.strip().title()


async def get_primary_user_id(session: Any) -> int:
    """Resolve the active primary user ID (Telegram admin user or default)."""
    admin_id = 999999
    if settings.admin_telegram_chat_id:
        try:
            admin_id = int(settings.admin_telegram_chat_id)
        except Exception:
            admin_id = 999999

    try:
        # Prioritize admin user profile if configured
        result = await session.execute(
            select(UserProfile).where(UserProfile.user_id == admin_id)
        )
        profile = result.scalar_one_or_none()
        if profile is not None:
            return profile.user_id

        # Fallback to any existing user profile
        result = await session.execute(select(UserProfile).limit(1))
        profile = result.scalar_one_or_none()
        if profile is not None:
            return profile.user_id

        # Create default user profile to ensure foreign key constraints pass
        default_user = UserProfile(
            user_id=admin_id,
            telegram_chat_id=admin_id,
            current_timezone="Asia/Singapore",
            home_currency="SGD",
        )
        session.add(default_user)
        await session.commit()
        return admin_id
    except Exception as e:
        logger.warning(f"Could not resolve or create UserProfile: {e}")
        return admin_id


async def migrate_existing_categories_if_needed(session: Any) -> None:
    """Standardize and clean up legacy raw category strings in the live PostgreSQL database."""
    result = await session.execute(select(ExpenseTransaction))
    rows = result.scalars().all()
    updated = False
    for r in rows:
        norm = normalize_category(r.category)
        if r.category != norm:
            r.category = norm
            session.add(r)
            updated = True
    if updated:
        await session.commit()


@router.get("/summary")
async def get_dashboard_summary(user_id: Optional[int] = Query(default=None)) -> Dict[str, Any]:
    """Retrieve high-level spend analytics, category distribution, and active counts from live database."""
    async with async_session_factory() as session:
        # Run one-time category normalization on legacy records
        await migrate_existing_categories_if_needed(session)

        # Build query for expense transactions
        query = select(ExpenseTransaction)
        if user_id is not None and user_id != 0:
            query = query.where(ExpenseTransaction.user_id == user_id)
        
        query = query.order_by(desc(ExpenseTransaction.date))
        result = await session.execute(query)
        expenses = result.scalars().all()

        income_query = select(IncomeTransaction)
        if user_id is not None and user_id != 0:
            income_query = income_query.where(IncomeTransaction.user_id == user_id)
        income_result = await session.execute(income_query)
        income = income_result.scalars().all()

        now = datetime.now(dt_timezone.utc)
        current_year_month = now.strftime("%Y-%m")

        total_spent_all = sum(e.amount for e in expenses)
        month_expenses = [e for e in expenses if e.date and e.date.strftime("%Y-%m") == current_year_month]
        total_spent_month = sum(e.amount for e in month_expenses) if month_expenses else total_spent_all
        month_income = [i for i in income if i.date and i.date.strftime("%Y-%m") == current_year_month]
        total_income_month = sum(i.amount for i in month_income)
        total_income_all = sum(i.amount for i in income)
        total_transaction_count = len(expenses) + len(income)
        month_transaction_count = len(month_expenses) + len(month_income)
        pending_iou_count = 0
        pending_iou_amount = 0.0
        for expense in expenses:
            _, count, amount = _split_payment_summary(expense.split_data or {})
            pending_iou_count += count
            pending_iou_amount += amount

        # Normalized Category breakdown
        category_totals: Dict[str, float] = {}
        category_counts: Dict[str, int] = {}
        merchant_totals: Dict[str, float] = {}
        merchant_counts: Dict[str, int] = {}

        target_set = month_expenses if month_expenses else expenses
        for e in target_set:
            cat = normalize_category(e.category)
            category_totals[cat] = category_totals.get(cat, 0.0) + e.amount
            category_counts[cat] = category_counts.get(cat, 0) + 1

            merch = e.merchant or "Unknown"
            merchant_totals[merch] = merchant_totals.get(merch, 0.0) + e.amount
            merchant_counts[merch] = merchant_counts.get(merch, 0) + 1

        denom = total_spent_month if total_spent_month > 0 else 1.0
        categories_list = [
            {
                "category": cat,
                "amount": round(amt, 2),
                "count": category_counts[cat],
                "percentage": round((amt / denom) * 100, 1),
            }
            for cat, amt in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
        ]

        merchants_list = [
            {
                "merchant": merch,
                "amount": round(amt, 2),
                "count": merchant_counts[merch],
            }
            for merch, amt in sorted(merchant_totals.items(), key=lambda x: x[1], reverse=True)[:5]
        ]

        # Active scheduled jobs count across all / specified user
        effective_user_id = user_id if (user_id is not None and user_id != 0) else await get_primary_user_id(session)
        active_jobs = await list_active_jobs(user_id=effective_user_id)

        # User profile info
        prof_res = await session.execute(
            select(UserProfile).order_by(desc(UserProfile.created_at)).limit(1)
        )
        profile = prof_res.scalar_one_or_none()

        return {
            "status": "ok",
            "currency": profile.home_currency if profile else "SGD",
            "timezone": profile.current_timezone if profile else "Asia/Singapore",
            "total_spent_month": round(total_spent_month, 2),
            "total_income_month": round(total_income_month, 2),
            "total_income_all": round(total_income_all, 2),
            "income_transactions_count": len(income),
            "net_cash_flow_month": round(total_income_month - total_spent_month, 2),
            "pending_iou_count": pending_iou_count,
            "pending_iou_amount": round(pending_iou_amount, 2),
            "total_transactions_count": total_transaction_count,
            "month_transactions_count": month_transaction_count,
            "categories": categories_list,
            "top_merchants": merchants_list,
            "active_jobs_count": len(active_jobs),
            "is_admin": settings.is_admin(effective_user_id),
        }


@router.get("/expenses")
async def list_expenses(
    user_id: Optional[int] = Query(default=None),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0),
) -> Dict[str, Any]:
    """List detailed expense transactions from the live database."""
    async with async_session_factory() as session:
        query = select(ExpenseTransaction)
        if user_id is not None and user_id != 0:
            query = query.where(ExpenseTransaction.user_id == user_id)

        if category and category.lower() != "all":
            query = query.where(ExpenseTransaction.category.ilike(f"%{category}%"))

        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                (ExpenseTransaction.merchant.ilike(search_pattern))
                | (ExpenseTransaction.category.ilike(search_pattern))
            )

        query = query.order_by(desc(ExpenseTransaction.date)).offset(offset).limit(limit)
        result = await session.execute(query)
        rows = result.scalars().all()

        # Only seed demo expenses if the database has ZERO total expenses
        if not rows and offset == 0 and not search and not category:
            total_count_res = await session.execute(select(func.count(ExpenseTransaction.id)))
            total_in_db = total_count_res.scalar_one() or 0
            if total_in_db == 0:
                demo_uid = await get_primary_user_id(session)
                await seed_demo_expenses(session, demo_uid)
                result = await session.execute(query)
                rows = result.scalars().all()

        items = [
            {
                "id": r.id,
                "amount": r.amount,
                "currency": r.currency,
                "merchant": r.merchant,
                "category": normalize_category(r.category),
                # DB stores naive UTC — emit an explicit UTC marker so browsers
                # convert to the viewer's local timezone instead of showing
                # UTC clock values as if they were local.
                "date": _format_iso(r.date),
                "is_verified": r.is_verified,
                "notes": r.notes,
                "source": "gmail" if r.source_message_id and "gmail" in r.source_message_id.lower() else ("telegram" if r.source_message_id else "manual"),
                "receipt_items": r.receipt_items or [],
                "split_data": r.split_data or {},
            }
            for r in rows
        ]

        return {"status": "ok", "expenses": items, "count": len(items)}


def _income_to_dict(item: IncomeTransaction) -> Dict[str, Any]:
    return {
        "id": item.id,
        "amount": item.amount,
        "currency": item.currency,
        "source": item.source,
        "category": item.category,
        "date": _format_iso(item.date),
        "notes": item.notes,
        "linked_expense_id": item.linked_expense_id,
    }


def _split_payment_summary(split_data: Dict[str, Any]) -> tuple[str, int, float]:
    """Return display status, pending participant count, and pending amount."""
    friends = [name for name in (split_data.get("friends") or []) if name != "Me"]
    share_amounts = dict(
        split_data.get("share_amounts")
        or split_data.get("custom_amounts")
        or {}
    )
    if not friends or not share_amounts:
        return "completed", 0, 0.0

    paid_status = dict(split_data.get("paid_status") or {})
    paid_amounts = dict(split_data.get("paid_amounts") or {})
    pending_amount = 0.0
    pending_count = 0
    paid_count = 0
    for friend in friends:
        amount_due = round(float(share_amounts.get(friend) or 0.0), 2)
        amount_paid = round(float(paid_amounts.get(friend) or 0.0), 2)
        if paid_status.get(friend) is True:
            paid_count += 1
            continue
        remaining = max(0.0, amount_due - amount_paid)
        if remaining > 0.01:
            pending_count += 1
            pending_amount += remaining

    if pending_count == 0:
        return "paid", 0, 0.0
    if paid_count > 0 or any(
        float(paid_amounts.get(friend) or 0.0) > 0 for friend in friends
    ):
        return "partially_paid", pending_count, round(pending_amount, 2)
    return "pending", pending_count, round(pending_amount, 2)


TRANSACTION_ID_WIDTH = 6


def _transaction_public_id(direction: str, record_id: int) -> str:
    prefix = {"outgoing": "out", "incoming": "in"}[direction]
    return f"{prefix}-{record_id:0{TRANSACTION_ID_WIDTH}d}"


def _expense_to_transaction(item: ExpenseTransaction) -> Dict[str, Any]:
    """Serialize an expense using the unified transaction contract."""
    split_data = item.split_data or {}
    split_status, pending_count, pending_amount = _split_payment_summary(split_data)
    return {
        "id": _transaction_public_id("outgoing", item.id),
        "record_id": item.id,
        "direction": "outgoing",
        "type": "expense",
        "amount": item.amount,
        "signed_amount": -abs(item.amount),
        "currency": item.currency,
        "title": item.merchant,
        "counterparty": item.merchant,
        "category": normalize_category(item.category),
        "date": _format_iso(item.date),
        "status": split_status,
        "source": (
            "gmail"
            if item.source_message_id and "gmail" in item.source_message_id.lower()
            else "telegram"
            if item.source_message_id
            else "manual"
        ),
        "notes": item.notes,
        "expense_id": item.id,
        "income_id": None,
        "linked_transaction_id": None,
        "pending_iou_count": pending_count,
        "pending_iou_amount": pending_amount,
        "split_data": split_data,
    }


def _income_to_transaction(item: IncomeTransaction) -> Dict[str, Any]:
    """Serialize incoming money using the unified transaction contract."""
    return {
        "id": _transaction_public_id("incoming", item.id),
        "record_id": item.id,
        "direction": "incoming",
        "type": item.category.lower().replace(" ", "_"),
        "amount": item.amount,
        "signed_amount": abs(item.amount),
        "currency": item.currency,
        "title": item.source,
        "counterparty": item.source,
        "category": item.category,
        "date": _format_iso(item.date),
        "status": "completed",
        "source": "iou" if item.linked_expense_id else "manual",
        "notes": item.notes,
        "expense_id": item.linked_expense_id,
        "income_id": item.id,
        "linked_transaction_id": (
            _transaction_public_id("outgoing", item.linked_expense_id)
            if item.linked_expense_id
            else None
        ),
        "pending_iou_count": 0,
        "pending_iou_amount": 0.0,
        "split_data": {},
    }


def _parse_transaction_key(value: str) -> tuple[str, int] | None:
    """Parse a stable unified transaction key such as ``in-14``."""
    prefix, separator, raw_id = value.partition("-")
    direction = {"out": "outgoing", "in": "incoming"}.get(prefix)
    if not separator or direction is None or not raw_id.isdigit():
        return None
    return direction, int(raw_id)


@router.get("/transactions")
async def list_transactions(
    direction: Literal["all", "outgoing", "incoming"] = Query(default="all"),
    status: Literal["all", "completed", "pending", "partially_paid", "paid"] = Query(default="all"),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    limit: int = Query(default=100, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """List outgoing and incoming records through one normalized ledger contract."""
    async with async_session_factory() as session:
        effective_user_id = (
            user_id if user_id is not None and user_id != 0 else await get_primary_user_id(session)
        )
        transactions: List[Dict[str, Any]] = []
        search_pattern = f"%{search}%" if search else None

        if direction in {"all", "outgoing"}:
            expense_query = select(ExpenseTransaction).where(
                ExpenseTransaction.user_id == effective_user_id
            )
            if category and category.lower() != "all":
                expense_query = expense_query.where(
                    ExpenseTransaction.category.ilike(f"%{category}%")
                )
            if search_pattern:
                expense_query = expense_query.where(
                    or_(
                        ExpenseTransaction.merchant.ilike(search_pattern),
                        ExpenseTransaction.category.ilike(search_pattern),
                    )
                )
            expenses = (await session.execute(expense_query)).scalars().all()
            transactions.extend(_expense_to_transaction(row) for row in expenses)

        if direction in {"all", "incoming"}:
            income_query = select(IncomeTransaction).where(
                IncomeTransaction.user_id == effective_user_id
            )
            if category and category.lower() != "all":
                income_query = income_query.where(
                    IncomeTransaction.category.ilike(f"%{category}%")
                )
            if search_pattern:
                income_query = income_query.where(
                    or_(
                        IncomeTransaction.source.ilike(search_pattern),
                        IncomeTransaction.category.ilike(search_pattern),
                        IncomeTransaction.notes.ilike(search_pattern),
                    )
                )
            income = (await session.execute(income_query)).scalars().all()
            transactions.extend(_income_to_transaction(row) for row in income)

        if status == "pending":
            transactions = [
                row
                for row in transactions
                if row["status"] in {"pending", "partially_paid"}
            ]
        elif status != "all":
            transactions = [row for row in transactions if row["status"] == status]
        transactions.sort(key=lambda row: row["date"] or "", reverse=True)
        total_count = len(transactions)
        return {
            "status": "ok",
            "transactions": transactions[offset : offset + limit],
            "count": total_count,
        }


@router.post("/transactions")
async def create_transaction(
    req: TransactionCreateRequest,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Create either direction of transaction through one entry point."""
    async with async_session_factory() as session:
        target_uid = (
            user_id
            if user_id is not None and user_id != 0
            else req.user_id
            if req.user_id and req.user_id != 999999
            else await get_primary_user_id(session)
        )
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == target_uid)
        )).scalar_one_or_none()
        if profile is None:
            session.add(UserProfile(
                user_id=target_uid,
                telegram_chat_id=target_uid,
                current_timezone="Asia/Singapore",
            ))
            await session.flush()

        transaction_date = _parse_iso_datetime(req.date) if req.date else None
        transaction_date = transaction_date or datetime.utcnow()
        currency = req.currency.strip().upper()

        match req.direction:
            case "outgoing":
                item = ExpenseTransaction(
                    user_id=target_uid,
                    amount=round(req.amount, 2),
                    currency=currency,
                    merchant=req.counterparty.strip(),
                    category=normalize_category(req.category),
                    date=transaction_date,
                    is_verified=True,
                    notes=req.notes.strip() if req.notes else None,
                )
                session.add(item)
                await session.commit()
                await session.refresh(item)
                transaction = _expense_to_transaction(item)
            case "incoming":
                item = IncomeTransaction(
                    user_id=target_uid,
                    amount=round(req.amount, 2),
                    currency=currency,
                    source=req.counterparty.strip(),
                    category=req.category.strip().title() or "Other",
                    date=transaction_date,
                    notes=req.notes.strip() if req.notes else None,
                )
                session.add(item)
                await session.commit()
                await session.refresh(item)
                transaction = _income_to_transaction(item)
            case unreachable:
                assert_never(unreachable)

        return {"status": "ok", "transaction": transaction}


@router.put("/transactions/{transaction_key}")
async def update_transaction(
    transaction_key: str,
    req: TransactionUpdateRequest,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Update one normalized transaction while preserving its direction."""
    parsed_key = _parse_transaction_key(transaction_key)
    if parsed_key is None:
        raise HTTPException(status_code=400, detail="Invalid transaction ID")
    direction, record_id = parsed_key

    async with async_session_factory() as session:
        target_uid = (
            user_id if user_id is not None and user_id != 0 else await get_primary_user_id(session)
        )
        match direction:
            case "outgoing":
                item = (await session.execute(
                    select(ExpenseTransaction).where(
                        ExpenseTransaction.id == record_id,
                        ExpenseTransaction.user_id == target_uid,
                    )
                )).scalar_one_or_none()
                if item is None:
                    raise HTTPException(status_code=404, detail="Transaction not found")
                if req.amount is not None:
                    item.amount = round(req.amount, 2)
                if req.currency is not None:
                    item.currency = req.currency.strip().upper()
                if req.counterparty is not None:
                    item.merchant = req.counterparty.strip()
                if req.category is not None:
                    item.category = normalize_category(req.category)
                if req.date is not None:
                    item.date = _parse_iso_datetime(req.date) or item.date
                if req.notes is not None:
                    item.notes = req.notes.strip() or None
                session.add(item)
                await session.commit()
                await session.refresh(item)
                transaction = _expense_to_transaction(item)
            case "incoming":
                item = (await session.execute(
                    select(IncomeTransaction).where(
                        IncomeTransaction.id == record_id,
                        IncomeTransaction.user_id == target_uid,
                    )
                )).scalar_one_or_none()
                if item is None:
                    raise HTTPException(status_code=404, detail="Transaction not found")
                if req.amount is not None:
                    item.amount = round(req.amount, 2)
                if req.currency is not None:
                    item.currency = req.currency.strip().upper()
                if req.counterparty is not None:
                    item.source = req.counterparty.strip()
                if req.category is not None:
                    item.category = req.category.strip().title() or "Other"
                if req.date is not None:
                    item.date = _parse_iso_datetime(req.date) or item.date
                if req.notes is not None:
                    item.notes = req.notes.strip() or None
                session.add(item)
                await session.commit()
                await session.refresh(item)
                transaction = _income_to_transaction(item)
            case unreachable:
                assert_never(unreachable)

        return {"status": "ok", "transaction": transaction}


@router.delete("/transactions/{transaction_key}")
async def delete_transaction(
    transaction_key: str,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Delete one normalized transaction in a user-scoped operation."""
    parsed_key = _parse_transaction_key(transaction_key)
    if parsed_key is None:
        raise HTTPException(status_code=400, detail="Invalid transaction ID")
    direction, record_id = parsed_key

    async with async_session_factory() as session:
        target_uid = (
            user_id if user_id is not None and user_id != 0 else await get_primary_user_id(session)
        )
        model = ExpenseTransaction if direction == "outgoing" else IncomeTransaction
        item = (await session.execute(
            select(model).where(model.id == record_id, model.user_id == target_uid)
        )).scalar_one_or_none()
        if item is None:
            raise HTTPException(status_code=404, detail="Transaction not found")
        await session.delete(item)
        await session.commit()
        return {"status": "ok", "deleted_id": transaction_key}


@router.post("/transactions/{transaction_key}/settle")
async def settle_transaction(
    transaction_key: str,
    req: IouSettlementRequest,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Record a full or partial IOU repayment through the unified ledger."""
    parsed_key = _parse_transaction_key(transaction_key)
    if parsed_key is None or parsed_key[0] != "outgoing":
        raise HTTPException(status_code=400, detail="Only outgoing split transactions can be settled")
    if user_id is not None and user_id != 0:
        target_uid = user_id
    else:
        async with async_session_factory() as session:
            target_uid = await get_primary_user_id(session)
    settlement = await settle_iou(IouSettlementCommand(
        expense_id=parsed_key[1],
        user_id=target_uid,
        participant=req.participant,
        amount=req.amount,
    ))
    if settlement.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Transaction not found")
    if settlement.get("status") in {"invalid_participant", "invalid_amount"}:
        raise HTTPException(status_code=400, detail=settlement)
    return {"status": "ok", "settlement": settlement}


@router.get("/income")
async def list_income(
    user_id: Optional[int] = Query(default=None),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=100, le=200),
    offset: int = Query(default=0),
) -> Dict[str, Any]:
    """List incoming money separately from expense transactions."""
    async with async_session_factory() as session:
        query = select(IncomeTransaction)
        if user_id is not None and user_id != 0:
            query = query.where(IncomeTransaction.user_id == user_id)
        if category and category.lower() != "all":
            query = query.where(IncomeTransaction.category.ilike(f"%{category}%"))
        if search:
            pattern = f"%{search}%"
            query = query.where(
                IncomeTransaction.source.ilike(pattern)
                | IncomeTransaction.category.ilike(pattern)
                | IncomeTransaction.notes.ilike(pattern)
            )
        query = query.order_by(desc(IncomeTransaction.date)).offset(offset).limit(limit)
        rows = (await session.execute(query)).scalars().all()
        return {"status": "ok", "income": [_income_to_dict(row) for row in rows], "count": len(rows)}


@router.post("/income")
async def create_income(
    req: IncomeCreateRequest,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Record salary, repayments, reimbursements, claims, or other money received."""
    async with async_session_factory() as session:
        target_uid = (
            user_id
            if user_id is not None and user_id != 0
            else (req.user_id if req.user_id and req.user_id != 999999 else await get_primary_user_id(session))
        )
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == target_uid)
        )).scalar_one_or_none()
        if not profile:
            session.add(UserProfile(
                user_id=target_uid,
                telegram_chat_id=target_uid,
                current_timezone="Asia/Singapore",
            ))
            await session.flush()

        income_date = _parse_iso_datetime(req.date) if req.date else None
        item = IncomeTransaction(
            user_id=target_uid,
            amount=round(req.amount, 2),
            currency=(req.currency or "SGD").strip().upper(),
            source=req.source.strip(),
            category=(req.category or "Other").strip().title(),
            date=income_date or datetime.utcnow(),
            notes=req.notes.strip() if req.notes else None,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return {"status": "ok", "message": f"Logged incoming {item.currency} {item.amount:.2f} from {item.source}", "income": _income_to_dict(item)}


@router.put("/income/{income_id}")
async def update_income(
    income_id: int,
    req: IncomeUpdateRequest,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Correct a manually logged incoming transaction."""
    async with async_session_factory() as session:
        query = select(IncomeTransaction).where(IncomeTransaction.id == income_id)
        if user_id is not None and user_id != 0:
            query = query.where(IncomeTransaction.user_id == user_id)
        item = (await session.execute(query)).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Incoming transaction not found")

        if req.amount is not None:
            item.amount = round(req.amount, 2)
        if req.currency is not None:
            item.currency = req.currency.strip().upper()
        if req.source is not None:
            item.source = req.source.strip()
        if req.category is not None:
            item.category = req.category.strip().title()
        if req.date is not None:
            parsed_date = _parse_iso_datetime(req.date)
            if parsed_date is not None:
                item.date = parsed_date
        if req.notes is not None:
            item.notes = req.notes.strip() or None

        session.add(item)
        await session.commit()
        await session.refresh(item)
        return {"status": "ok", "income": _income_to_dict(item)}


@router.delete("/income/{income_id}")
async def delete_income(
    income_id: int,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Remove a manually logged incoming transaction."""
    async with async_session_factory() as session:
        query = select(IncomeTransaction).where(IncomeTransaction.id == income_id)
        if user_id is not None and user_id != 0:
            query = query.where(IncomeTransaction.user_id == user_id)
        item = (await session.execute(query)).scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Incoming transaction not found")
        await session.delete(item)
        await session.commit()
        return {"status": "ok", "deleted_id": income_id}


@router.post("/expenses")
async def create_expense(req: ExpenseCreateRequest) -> Dict[str, Any]:
    """Manually record a new expense linked to the active live user profile."""
    async with async_session_factory() as session:
        target_uid = req.user_id if (req.user_id and req.user_id != 999999) else await get_primary_user_id(session)
        
        # Ensure user profile exists
        prof = await session.execute(select(UserProfile).where(UserProfile.user_id == target_uid))
        if not prof.scalar_one_or_none():
            session.add(UserProfile(user_id=target_uid, telegram_chat_id=target_uid, current_timezone="Asia/Singapore"))
            await session.commit()

        dt = datetime.utcnow()
        if req.date:
            try:
                dt = datetime.fromisoformat(req.date.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass

        tx = ExpenseTransaction(
            user_id=target_uid,
            amount=req.amount,
            currency=req.currency or "SGD",
            merchant=req.merchant,
            category=normalize_category(req.category),
            date=dt,
            is_verified=True,
            notes=req.notes.strip() if req.notes else None,
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

        return {
            "status": "ok",
            "message": f"Logged {tx.currency} {tx.amount:.2f} at {tx.merchant}",
            "transaction_id": tx.id,
        }


@router.post("/expenses/sync-emails")
async def sync_emails_now(user_id: Optional[int] = Query(default=None)) -> Dict[str, Any]:
    """Trigger an immediate email financial sweep to parse and extract receipts."""
    from core.scheduler import _scheduled_email_expense_sweep
    try:
        await _scheduled_email_expense_sweep()
        return {"status": "ok", "message": "Email sweep completed successfully"}
    except Exception as exc:
        logger.error("Failed to run email sweep: %s", exc)
        return {"status": "error", "message": str(exc)}



@router.put("/expenses/{expense_id}")
async def update_expense(expense_id: int, req: ExpenseUpdateRequest) -> Dict[str, Any]:
    """Update an existing expense transaction directly."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        )
        tx = result.scalar_one_or_none()
        if not tx:
            raise HTTPException(status_code=404, detail="Expense not found")

        if req.amount is not None:
            tx.amount = req.amount
        if req.currency is not None:
            tx.currency = req.currency
        if req.merchant is not None:
            tx.merchant = req.merchant
        if req.category is not None:
            tx.category = req.category
        if req.date is not None:
            try:
                tx.date = datetime.fromisoformat(req.date.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
        if req.notes is not None:
            tx.notes = req.notes.strip() or None

        session.add(tx)
        await session.commit()
        await session.refresh(tx)

        return {
            "status": "ok",
            "message": f"Updated expense #{tx.id}",
            "expense": {
                "id": tx.id,
                "amount": tx.amount,
                "currency": tx.currency,
                "merchant": tx.merchant,
                "category": tx.category,
                "date": _format_iso(tx.date),
                "notes": tx.notes,
            },
        }


class ReceiptOCRRequest(BaseModel):
    image_b64: str = Field(..., description="Base64 data URL or raw Base64 string of receipt photo")
    mime_type: Optional[str] = Field(default="image/jpeg", description="MIME type")


class ExpenseDetailsUpdateRequest(BaseModel):
    merchant: Optional[str] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    currency: Optional[str] = None
    date: Optional[str] = None
    notes: Optional[str] = Field(default=None, max_length=500)
    receipt_items: Optional[List[Dict[str, Any]]] = None
    split_data: Optional[Dict[str, Any]] = None


@router.post("/expenses/ocr-receipt")
async def ocr_receipt(req: ReceiptOCRRequest) -> Dict[str, Any]:
    """Parse itemized dishes/groceries and tax rates from a receipt photo using Gemini Vision."""
    from capabilities.expenses.tools import extract_itemized_receipt_from_image
    data_b64 = req.image_b64
    if "," in data_b64:
        data_b64 = data_b64.split(",", 1)[1]
    res = await extract_itemized_receipt_from_image(data_b64, mime_type=req.mime_type or "image/jpeg")
    return {"status": "ok", "receipt": res}


@router.get("/expenses/{expense_id}/details")
async def get_expense_details(
    expense_id: int,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Fetch complete details, itemized line items, and split bill state for an expense."""
    async with async_session_factory() as session:
        query = select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        if user_id is not None and user_id != 0:
            query = query.where(ExpenseTransaction.user_id == user_id)
        result = await session.execute(query)
        tx = result.scalar_one_or_none()
        if not tx:
            raise HTTPException(status_code=404, detail="Expense not found")
        return {
            "status": "ok",
            "expense": {
                "id": tx.id,
                "user_id": tx.user_id,
                "amount": tx.amount,
                "currency": tx.currency,
                "merchant": tx.merchant,
                "category": tx.category,
                "date": _format_iso(tx.date),
                "is_verified": tx.is_verified,
                "notes": tx.notes,
                "receipt_items": tx.receipt_items or [],
                "split_data": tx.split_data or {},
            }
        }


@router.put("/expenses/{expense_id}/details")
async def update_expense_details(
    expense_id: int,
    req: ExpenseDetailsUpdateRequest,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Update an expense record, including receipt line items and bill split breakdown."""
    async with async_session_factory() as session:
        query = select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        if user_id is not None and user_id != 0:
            query = query.where(ExpenseTransaction.user_id == user_id)
        result = await session.execute(query)
        tx = result.scalar_one_or_none()
        if not tx:
            raise HTTPException(status_code=404, detail="Expense not found")
        
        if req.merchant is not None:
            tx.merchant = req.merchant
        if req.amount is not None:
            tx.amount = req.amount
        if req.currency is not None:
            tx.currency = req.currency
        if req.category is not None:
            tx.category = req.category
        if req.date is not None:
            try:
                tx.date = datetime.fromisoformat(req.date.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
        if req.notes is not None:
            tx.notes = req.notes.strip() or None
        if req.receipt_items is not None:
            tx.receipt_items = req.receipt_items
        if req.split_data is not None:
            tx.split_data = req.split_data

        session.add(tx)
        await session.commit()
        await session.refresh(tx)
        return {
            "status": "ok",
            "message": f"Updated details for expense #{tx.id}",
            "expense": {
                "id": tx.id,
                "amount": tx.amount,
                "currency": tx.currency,
                "merchant": tx.merchant,
                "category": tx.category,
                "date": _format_iso(tx.date),
                "notes": tx.notes,
                "receipt_items": tx.receipt_items,
                "split_data": tx.split_data,
            }
        }


class ExpenseBatchDeleteRequest(BaseModel):
    expense_ids: List[int] = Field(..., description="List of expense IDs to delete")


class ExpenseRestoreRequest(BaseModel):
    expenses: List[Dict[str, Any]] = Field(..., description="List of deleted expense records to restore")


@router.delete("/expenses/{expense_id}")
async def delete_expense(expense_id: int) -> Dict[str, Any]:
    """Delete an expense record permanently from PostgreSQL and tombstone its source message ID."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        )
        tx = result.scalar_one_or_none()
        if tx:
            if tx.source_message_id:
                # Tombstone source_message_id to prevent email poller re-ingestion
                existing_tomb = await session.execute(
                    select(DeletedExpenseMessage).where(DeletedExpenseMessage.source_message_id == tx.source_message_id)
                )
                if not existing_tomb.scalar_one_or_none():
                    session.add(DeletedExpenseMessage(user_id=tx.user_id, source_message_id=tx.source_message_id))
            await session.delete(tx)
            await session.commit()
            return {"status": "ok", "deleted_id": expense_id, "rows_affected": 1}
        return {"status": "ok", "deleted_id": expense_id, "rows_affected": 0}


@router.post("/expenses/batch-delete")
async def batch_delete_expenses(req: ExpenseBatchDeleteRequest) -> Dict[str, Any]:
    """Delete multiple expense records in one PostgreSQL transaction and tombstone their source message IDs."""
    if not req.expense_ids:
        return {"status": "ok", "deleted_count": 0, "deleted_ids": []}
    async with async_session_factory() as session:
        result = await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id.in_(req.expense_ids))
        )
        txs = result.scalars().all()
        for tx in txs:
            if tx.source_message_id:
                existing_tomb = await session.execute(
                    select(DeletedExpenseMessage).where(DeletedExpenseMessage.source_message_id == tx.source_message_id)
                )
                if not existing_tomb.scalar_one_or_none():
                    session.add(DeletedExpenseMessage(user_id=tx.user_id, source_message_id=tx.source_message_id))
            await session.delete(tx)
        await session.commit()
        return {
            "status": "ok",
            "deleted_count": len(txs),
            "deleted_ids": req.expense_ids,
        }


@router.post("/expenses/restore")
async def restore_expenses(req: ExpenseRestoreRequest) -> Dict[str, Any]:
    """Restore one or more deleted expenses back into PostgreSQL (Undo Action)."""
    if not req.expenses:
        return {"status": "ok", "restored_count": 0, "restored_ids": []}
    
    restored_records = []
    async with async_session_factory() as session:
        target_uid = await get_primary_user_id(session)
        for item in req.expenses:
            dt = datetime.utcnow()
            if item.get("date"):
                try:
                    dt = datetime.fromisoformat(str(item["date"]).replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    pass
            
            src_msg_id = item.get("source_message_id")
            if src_msg_id:
                # Remove from tombstones so it is active again
                await session.execute(
                    delete(DeletedExpenseMessage).where(DeletedExpenseMessage.source_message_id == src_msg_id)
                )
            
            tx = ExpenseTransaction(
                user_id=item.get("user_id") or target_uid,
                amount=float(item.get("amount", 0.0)),
                currency=item.get("currency") or "SGD",
                merchant=item.get("merchant") or "Unknown",
                category=normalize_category(item.get("category")),
                date=dt,
                source_message_id=src_msg_id,
                is_verified=bool(item.get("is_verified", True)),
            )
            session.add(tx)
            restored_records.append(tx)
        
        await session.commit()
        for tx in restored_records:
            await session.refresh(tx)
        
        return {
            "status": "ok",
            "message": f"Restored {len(restored_records)} transaction(s)",
            "restored_count": len(restored_records),
            "restored_ids": [tx.id for tx in restored_records],
        }


async def seed_demo_expenses(session: Any, user_id: int) -> None:
    """Seed initial demonstration expenses so the user has immediate rich data on first load."""
    sample_data = [
        (45.50, "SGD", "FairPrice Finest", "Groceries", datetime(2026, 8, 14, 18, 30)),
        (14.20, "SGD", "Amoy Street Food Centre", "Dining", datetime(2026, 8, 14, 12, 45)),
        (22.80, "SGD", "Grab SG", "Transport", datetime(2026, 8, 13, 21, 15)),
        (120.00, "SGD", "Uniqlo Orchard", "Shopping", datetime(2026, 8, 12, 16, 0)),
        (5.80, "SGD", "Yakun Kaya Toast", "Dining", datetime(2026, 8, 12, 8, 30)),
        (65.00, "SGD", "Singtel Utilities", "Bills", datetime(2026, 8, 10, 10, 0)),
        (18.50, "SGD", "Cold Storage", "Groceries", datetime(2026, 8, 9, 19, 20)),
        (32.00, "SGD", "Cedele Cafe", "Dining", datetime(2026, 8, 8, 13, 0)),
    ]
    for amount, currency, merchant, category, dt in sample_data:
        session.add(
            ExpenseTransaction(
                user_id=user_id,
                amount=amount,
                currency=currency,
                merchant=merchant,
                category=category,
                date=dt,
                is_verified=True,
            )
        )
    await session.commit()


# ---------------------------------------------------------------------------
# 2. Reminders & Scheduled Jobs Endpoints
# ---------------------------------------------------------------------------

@router.get("/jobs")
async def list_jobs(user_id: Optional[int] = Query(default=None)) -> Dict[str, Any]:
    """List active scheduled jobs and reminders."""
    async with async_session_factory() as session:
        effective_user_id = user_id if (user_id is not None and user_id != 0) else await get_primary_user_id(session)
    jobs = await list_active_jobs(user_id=effective_user_id)
    return {"status": "ok", "jobs": jobs}


@router.post("/jobs/run/{job_id}")
async def trigger_job_run(job_id: int) -> Dict[str, Any]:
    """Instantly trigger a scheduled reminder job."""
    success = await run_now(job_id)
    return {"status": "ok", "triggered": success, "job_id": job_id}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: int, user_id: Optional[int] = Query(default=None)) -> Dict[str, Any]:
    """Delete a scheduled reminder."""
    async with async_session_factory() as session:
        effective_user_id = user_id if (user_id is not None and user_id != 0) else await get_primary_user_id(session)
    deleted = await delete_scheduled_job(job_id=job_id, user_id=effective_user_id)
    return {"status": "ok", "deleted": deleted, "job_id": job_id}


# ---------------------------------------------------------------------------
# 4. Tasks & Reminders To-Do Endpoints
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

def _parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        clean = dt_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _format_iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


@router.get("/tasks")
async def list_tasks(
    status: Optional[str] = Query(default="all"),
    priority: Optional[str] = Query(default=None),
    has_reminder: Optional[bool] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """List tasks with status, priority, and reminder filters."""
    async with async_session_factory() as session:
        effective_user_id = user_id if (user_id is not None and user_id != 0) else await get_primary_user_id(session)

        query = select(TaskItem).where(TaskItem.user_id == effective_user_id)
        if status and status.lower() != "all":
            query = query.where(TaskItem.status == status.lower())
        if priority:
            query = query.where(TaskItem.priority == priority.lower())
        if has_reminder is True:
            query = query.where(TaskItem.reminder_type != "none", TaskItem.is_reminder_active == True)
        elif has_reminder is False:
            query = query.where(TaskItem.reminder_type == "none")

        query = query.order_by(TaskItem.status, desc(TaskItem.created_at))
        result = await session.execute(query)
        tasks = result.scalars().all()

        return {
            "status": "ok",
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status,
                    "priority": t.priority,
                    "due_at": _format_iso(t.due_at),
                    "reminder_type": t.reminder_type,
                    "reminder_time": _format_iso(t.reminder_time),
                    "cron_expression": t.cron_expression,
                    "timezone": t.timezone,
                    "is_reminder_active": t.is_reminder_active,
                    "linked_expense_id": t.linked_expense_id,
                    "iou_friend": t.iou_friend,
                    "iou_amount": t.iou_amount,
                    "created_at": _format_iso(t.created_at),
                    "completed_at": _format_iso(t.completed_at),
                }
                for t in tasks
            ],
            "stats": {
                "total": len(tasks),
                "todo_count": sum(1 for t in tasks if t.status == "todo"),
                "done_count": sum(1 for t in tasks if t.status == "done"),
                "reminders_count": sum(1 for t in tasks if t.reminder_type != "none" and t.is_reminder_active),
            },
        }


@router.post("/tasks")
async def create_task(req: TaskCreateRequest) -> Dict[str, Any]:
    """Create a new task with optional reminder schedule."""
    async with async_session_factory() as session:
        effective_user_id = (
            req.user_id
            if (req.user_id is not None and req.user_id != 999999 and req.user_id != 0)
            else await get_primary_user_id(session)
        )

        task = TaskItem(
            user_id=effective_user_id,
            title=req.title.strip(),
            description=req.description.strip() if req.description else None,
            priority=req.priority.lower() if req.priority in ("low", "medium", "high") else "medium",
            due_at=_parse_iso_datetime(req.due_at),
            reminder_type=req.reminder_type if req.reminder_type in ("none", "once", "recurring") else "none",
            reminder_time=_parse_iso_datetime(req.reminder_time),
            cron_expression=req.cron_expression.strip() if req.cron_expression else None,
            timezone=req.timezone or "Asia/Singapore",
            is_reminder_active=req.reminder_type != "none",
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        if task.reminder_type != "none":
            _add_task_to_scheduler(task)

        return {
            "status": "ok",
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "due_at": _format_iso(task.due_at),
                "reminder_type": task.reminder_type,
                "reminder_time": _format_iso(task.reminder_time),
                "cron_expression": task.cron_expression,
                "timezone": task.timezone,
                "is_reminder_active": task.is_reminder_active,
                "linked_expense_id": task.linked_expense_id,
                "iou_friend": task.iou_friend,
                "iou_amount": task.iou_amount,
                "created_at": _format_iso(task.created_at),
                "completed_at": _format_iso(task.completed_at),
            },
        }


@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, req: TaskUpdateRequest) -> Dict[str, Any]:
    """Update a task's details, status, or reminder."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if req.title is not None:
            task.title = req.title.strip()
        if req.description is not None:
            task.description = req.description.strip() if req.description else None
        if req.priority is not None and req.priority.lower() in ("low", "medium", "high"):
            task.priority = req.priority.lower()
        if req.due_at is not None:
            task.due_at = _parse_iso_datetime(req.due_at)
        if req.status is not None:
            old_status = task.status
            task.status = req.status.lower()
            if task.status == "done" and old_status != "done":
                task.completed_at = datetime.now(timezone.utc)
                task.is_reminder_active = False
                remove_task_reminder(task.id)
            elif task.status == "todo" and old_status == "done":
                task.completed_at = None
                if task.reminder_type != "none":
                    task.is_reminder_active = True

        if req.reminder_type is not None:
            task.reminder_type = req.reminder_type
        if req.reminder_time is not None:
            task.reminder_time = _parse_iso_datetime(req.reminder_time)
        if req.cron_expression is not None:
            task.cron_expression = req.cron_expression.strip() if req.cron_expression else None
        if req.timezone is not None:
            task.timezone = req.timezone
        if req.is_reminder_active is not None:
            task.is_reminder_active = req.is_reminder_active

        session.add(task)
        await session.commit()
        await session.refresh(task)

        # Update scheduler
        if task.status == "done" or not task.is_reminder_active or task.reminder_type == "none":
            remove_task_reminder(task.id)
        else:
            _add_task_to_scheduler(task)

        return {
            "status": "ok",
            "task": {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "due_at": _format_iso(task.due_at),
                "reminder_type": task.reminder_type,
                "reminder_time": _format_iso(task.reminder_time),
                "cron_expression": task.cron_expression,
                "timezone": task.timezone,
                "is_reminder_active": task.is_reminder_active,
                "linked_expense_id": task.linked_expense_id,
                "iou_friend": task.iou_friend,
                "iou_amount": task.iou_amount,
                "created_at": _format_iso(task.created_at),
                "completed_at": _format_iso(task.completed_at),
            },
        }


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: int) -> Dict[str, Any]:
    """Delete a task and remove its scheduled reminder."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        remove_task_reminder(task.id)
        await session.execute(delete(TaskItem).where(TaskItem.id == task_id))
        await session.commit()
        return {"status": "ok", "deleted_id": task_id}


@router.post("/tasks/{task_id}/test_alert")
async def test_task_alert(task_id: int) -> Dict[str, Any]:
    """Instantly trigger a Telegram reminder alert for this task to test delivery."""
    async with async_session_factory() as session:
        task = (
            await session.execute(
                select(TaskItem).where(TaskItem.id == task_id)
            )
        ).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        user_id = task.user_id

    success = await trigger_task_alert_now(task_id=task_id, user_id=user_id)
    return {"status": "ok", "alert_triggered": success, "task_id": task_id}


@router.post("/tasks/{task_id}/snooze")
async def snooze_task(task_id: int, minutes: int = Query(default=60)) -> Dict[str, Any]:
    """Snooze a task reminder by N minutes."""
    async with async_session_factory() as session:
        task = (
            await session.execute(
                select(TaskItem).where(TaskItem.id == task_id)
            )
        ).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        user_id = task.user_id

    success = await snooze_task_reminder(task_id=task_id, user_id=user_id, minutes=minutes)
    return {"status": "ok", "snoozed": success, "task_id": task_id, "minutes": minutes}



