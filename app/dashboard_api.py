"""Dashboard API router for Nexus Prime.

Provides REST endpoints for querying and managing personal assistant data:
- Expenses: Summary statistics, category breakdowns, merchant rankings, and transaction logs.
- Reminders & Scheduled Jobs: Active APScheduler tasks, dynamic timezones, and manual triggers.
- Groceries: Checklist items, category groups, and purchase status toggles.
"""

from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query
from sqlmodel import select, delete, func, desc

from core.db import async_session_factory
from core.models import (
    ExpenseTransaction,
    DeletedExpenseMessage,
    GroceryItem,
    ScheduledJob,
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

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ExpenseCreateRequest(BaseModel):
    amount: float = Field(..., gt=0, description="Expense amount")
    currency: str = Field(default="SGD", description="3-letter currency code")
    merchant: str = Field(..., description="Store or merchant name")
    category: str = Field(default="General", description="Expense category")
    date: Optional[str] = Field(default=None, description="ISO timestamp or date string")
    user_id: Optional[int] = Field(default=999999, description="Target user ID")


class ExpenseUpdateRequest(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0, description="Expense amount")
    currency: Optional[str] = Field(default=None, description="3-letter currency code")
    merchant: Optional[str] = Field(default=None, description="Store or merchant name")
    category: Optional[str] = Field(default=None, description="Expense category")
    date: Optional[str] = Field(default=None, description="ISO timestamp or date string")



class GroceryCreateRequest(BaseModel):
    name: str = Field(..., description="Item name")
    quantity: str = Field(default="1", description="Quantity or count")
    category: str = Field(default="General", description="Item category")
    user_id: Optional[int] = Field(default=999999, description="Target user ID")


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
    """Resolve the active primary user ID (Telegram user or default)."""
    result = await session.execute(
        select(UserProfile).order_by(desc(UserProfile.created_at)).limit(1)
    )
    profile = result.scalar_one_or_none()
    if profile is not None:
        return profile.user_id

    # Create default user profile to ensure foreign key constraints pass
    admin_id = 999999
    if settings.admin_telegram_chat_id:
        try:
            admin_id = int(settings.admin_telegram_chat_id)
        except Exception:
            admin_id = 999999

    default_user = UserProfile(
        user_id=admin_id,
        telegram_chat_id=admin_id,
        current_timezone="Asia/Singapore",
        home_currency="SGD",
    )
    session.add(default_user)
    await session.commit()
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

        now = datetime.now(dt_timezone.utc)
        current_year_month = now.strftime("%Y-%m")

        total_spent_all = sum(e.amount for e in expenses)
        month_expenses = [e for e in expenses if e.date and e.date.strftime("%Y-%m") == current_year_month]
        total_spent_month = sum(e.amount for e in month_expenses) if month_expenses else total_spent_all

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

        # Grocery items count
        g_query = select(func.count(GroceryItem.id)).where(GroceryItem.is_purchased == False)
        if user_id is not None and user_id != 0:
            g_query = g_query.where(GroceryItem.user_id == user_id)
        
        g_res = await session.execute(g_query)
        groceries_pending = g_res.scalar_one() or 0

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
            "total_transactions_count": len(expenses),
            "month_transactions_count": len(target_set),
            "categories": categories_list,
            "top_merchants": merchants_list,
            "active_jobs_count": len(active_jobs),
            "pending_groceries_count": groceries_pending,
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
                "date": r.date.isoformat() if r.date else "",
                "is_verified": r.is_verified,
                "source": "gmail" if r.source_message_id and "gmail" in r.source_message_id.lower() else ("telegram" if r.source_message_id else "manual"),
            }
            for r in rows
        ]

        return {"status": "ok", "expenses": items, "count": len(items)}


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
        )
        session.add(tx)
        await session.commit()
        await session.refresh(tx)

        return {
            "status": "ok",
            "message": f"Logged {tx.currency} {tx.amount:.2f} at {tx.merchant}",
            "transaction_id": tx.id,
        }


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
                "date": tx.date.isoformat() if tx.date else "",
            },
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
# 3. Groceries & Pantry Endpoints
# ---------------------------------------------------------------------------

@router.get("/groceries")
async def list_groceries(user_id: Optional[int] = Query(default=None)) -> Dict[str, Any]:
    """List grocery checklist items from live database."""
    async with async_session_factory() as session:
        query = select(GroceryItem)
        if user_id is not None and user_id != 0:
            query = query.where(GroceryItem.user_id == user_id)
        
        query = query.order_by(GroceryItem.is_purchased, desc(GroceryItem.added_at))
        result = await session.execute(query)
        items = result.scalars().all()

        if not items:
            # Only seed default groceries if entire table is empty
            total_g_res = await session.execute(select(func.count(GroceryItem.id)))
            if (total_g_res.scalar_one() or 0) == 0:
                demo_uid = await get_primary_user_id(session)
                seed_groceries = [
                    ("Oat Milk", "2 cartons", "Dairy/Alternative"),
                    ("Chicken Breast", "500g", "Meat & Seafood"),
                    ("Japanese Cucumbers", "1 pack", "Produce"),
                    ("Eggs", "1 tray (10 pcs)", "Dairy & Eggs"),
                    ("Avocados", "3 pcs", "Produce"),
                ]
                for name, qty, cat in seed_groceries:
                    session.add(GroceryItem(user_id=demo_uid, name=name, quantity=qty, category=cat))
                await session.commit()

                result = await session.execute(query)
                items = result.scalars().all()

        return {
            "status": "ok",
            "groceries": [
                {
                    "id": item.id,
                    "name": item.name,
                    "quantity": item.quantity,
                    "category": item.category,
                    "is_purchased": item.is_purchased,
                }
                for item in items
            ],
        }


@router.post("/groceries")
async def add_grocery(req: GroceryCreateRequest) -> Dict[str, Any]:
    """Add a new item to the grocery shopping list."""
    async with async_session_factory() as session:
        target_uid = req.user_id if (req.user_id and req.user_id != 999999) else await get_primary_user_id(session)
        item = GroceryItem(
            user_id=target_uid,
            name=req.name,
            quantity=req.quantity or "1",
            category=req.category or "General",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return {"status": "ok", "item_id": item.id, "name": item.name}


@router.patch("/groceries/{item_id}/toggle")
async def toggle_grocery(item_id: int) -> Dict[str, Any]:
    """Toggle purchased status of a grocery item."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(GroceryItem).where(GroceryItem.id == item_id)
        )
        item = result.scalar_one_or_none()
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        item.is_purchased = not item.is_purchased
        session.add(item)
        await session.commit()
        return {"status": "ok", "item_id": item.id, "is_purchased": item.is_purchased}


@router.delete("/groceries/{item_id}")
async def delete_grocery(item_id: int) -> Dict[str, Any]:
    """Delete an item from the grocery list."""
    async with async_session_factory() as session:
        await session.execute(delete(GroceryItem).where(GroceryItem.id == item_id))
        await session.commit()
        return {"status": "ok", "deleted_id": item_id}


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
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
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
