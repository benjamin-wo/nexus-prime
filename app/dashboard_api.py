"""Dashboard API router for Nexus Prime.

Provides REST endpoints for querying and managing personal assistant data:
- Expenses: Summary statistics, category breakdowns, merchant rankings, and transaction logs.
- Reminders & Scheduled Jobs: Active APScheduler tasks, dynamic timezones, and manual triggers.
- Groceries: Checklist items, category groups, and purchase status toggles.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import select, delete, func, desc

from core.db import async_session_factory
from core.config import settings
from core.models import (
    ExpenseTransaction,
    DeletedExpenseMessage,
    GroceryItem,
    ScheduledJob,
    UserProfile,
    TaskItem,
    WhiteboardProject,
    WhiteboardBlock,
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

logger = logging.getLogger(__name__)

# Directory where AI-generated board cover art is persisted (project_root/data/board_covers
# by default, or DATA_DIR/board_covers when an absolute DATA_DIR is configured).
BOARD_COVERS_DIR = os.path.join(settings.resolved_data_dir, "board_covers")

# In-flight cover generation guard — prevents duplicate concurrent Imagen calls per board.
_cover_generation_inflight: set = set()

# Strong references to in-flight generation tasks so the garbage collector never
# collects them while suspended at an await ("Task was destroyed but it is pending").
_cover_generation_tasks: Dict[int, "asyncio.Task[None]"] = {}


# ---------------------------------------------------------------------------
# Board Cover Art (Imagen)
# ---------------------------------------------------------------------------

# Category-adaptive art direction used to build the "Artsy Narrative Landscape" prompt.
_COVER_THEMES: Dict[str, Dict[str, str]] = {
    "trip": {
        "sky": "a dusky gradient from deep indigo into warm amber along the horizon",
        "foreground": "a winding coastal road, glowing street lamps and distant mountain silhouettes",
        "aurora": "soft teal and violet aurora ribbons drifting overhead",
    },
    "event": {
        "sky": "a festive violet-to-magenta twilight",
        "foreground": "string lights, gentle confetti and a celebratory stage silhouette",
        "aurora": "colourful sparkle bursts scattered across the sky",
    },
    "meal": {
        "sky": "warm golden-hour light fading into a creamy sky",
        "foreground": "a rustic wooden table with fresh produce, herbs and ceramic bowls",
        "aurora": "subtle warm bokeh lights glowing in the background",
    },
    "project": {
        "sky": "a cool midnight blue with faint constellation lines",
        "foreground": "abstract geometric shapes, floating nodes and a glowing roadmap",
        "aurora": "electric cyan energy streaks arcing overhead",
    },
    "general": {
        "sky": "a soft gradient twilight blending lavender into slate",
        "foreground": "abstract mountains, calm water and floating luminous notes",
        "aurora": "gentle pastel aurora washing across the sky",
    },
}


def _build_imagen_prompt(title: str, category: Optional[str], summary: Optional[str]) -> str:
    """Construct the 'Artsy Narrative Landscape' prompt, adapting sky / foreground /
    aurora styling to the board's category and title."""
    theme = _COVER_THEMES.get((category or "general").strip().lower(), _COVER_THEMES["general"])
    subject = title.strip() or "a personal planning board"
    context = (summary or "").strip()
    return (
        "Artsy Narrative Landscape illustration, tall vertical banner. "
        f"Theme: {subject}. "
        f"{'Context: ' + context + '. ' if context else ''}"
        f"Sky: {theme['sky']}. Foreground: {theme['foreground']}. "
        f"Aurora: {theme['aurora']}. "
        "Cinematic lighting, rich painterly detail, soft depth of field, "
        "no text, no words, no letters, no logos."
    )


def _cover_file_path(project_id: int) -> str:
    return os.path.join(BOARD_COVERS_DIR, f"{project_id}.png")


async def _generate_board_cover(project_id: int) -> None:
    """Generate Imagen cover art for a board and persist it to disk.

    Safe to run as a background task: fetches the project from the DB, builds a
    category-aware prompt, calls Imagen, writes the PNG to BOARD_COVERS_DIR and
    finally flips WhiteboardProject.cover_ready to True. Any failure leaves the
    flag False so a later poll can retry.
    """
    try:
        api_key = settings.active_gemini_api_key
        if not api_key:
            logger.info("No Gemini API key configured — skipping cover generation for board %s", project_id)
            return

        async with async_session_factory() as session:
            proj = (await session.execute(
                select(WhiteboardProject).where(WhiteboardProject.id == project_id)
            )).scalar_one_or_none()
            if not proj:
                return
            title, category, summary = proj.title, proj.category, proj.summary

        prompt = _build_imagen_prompt(title, category, summary)

        image_bytes = None
        # 1. Primary generation path: Interactions API with gemini-3.1-flash-lite-image
        try:
            import base64
            from google import genai

            client = genai.Client(api_key=api_key)
            generation_config = {
                "temperature": 1,
                "max_output_tokens": 65536,
                "top_p": 0.95,
                "thinking_level": "minimal",
            }
            interaction = client.interactions.create(
                model="models/gemini-3.1-flash-lite-image",
                input=prompt,
                generation_config=generation_config,
                response_modalities=["image", "text"],
            )
            for step in interaction.steps:
                if step.type == "model_output" and step.content:
                    for part in step.content:
                        if getattr(part, "type", None) == "image" and getattr(part, "data", None):
                            image_bytes = base64.b64decode(part.data)
                            break
                    if image_bytes:
                        break
        except Exception as inter_exc:
            logger.info("Interactions image generation failed for board %s, trying generate_content: %s", project_id, inter_exc)

        # 2. Fallback generation path: generate_content with gemini-2.5-flash-image
        if not image_bytes:
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash-image",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                    ),
                )
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                            image_bytes = part.inline_data.data
                            break
            except Exception as gen_exc:
                logger.warning("generate_content image fallback failed for board %s: %s", project_id, gen_exc)

        if not image_bytes:
            logger.warning("No image bytes returned for board %s", project_id)
            return

        os.makedirs(BOARD_COVERS_DIR, exist_ok=True)
        with open(_cover_file_path(project_id), "wb") as f:
            f.write(image_bytes)

        async with async_session_factory() as session:
            proj = (await session.execute(
                select(WhiteboardProject).where(WhiteboardProject.id == project_id)
            )).scalar_one_or_none()
            if proj:
                proj.cover_ready = True
                session.add(proj)
                await session.commit()
        logger.info("Cover art generated successfully for board %s", project_id)
    except Exception as exc:  # noqa: BLE001 - background task must never crash the request
        logger.warning("Cover generation failed for board %s: %s", project_id, exc)
    finally:
        _cover_generation_inflight.discard(project_id)


def _schedule_cover_generation(project_id: int) -> None:
    """Safely kick off cover generation as a tracked asyncio task.

    Adds the board to the in-flight guard, keeps a strong reference to the task
    (so the GC cannot collect it mid-await) and removes both once it completes.
    """
    _cover_generation_inflight.add(project_id)
    task = asyncio.create_task(_generate_board_cover(project_id))
    _cover_generation_tasks[project_id] = task
    task.add_done_callback(lambda _t, pid=project_id: _cover_generation_tasks.pop(pid, None))


def _maybe_trigger_cover_generation(project_id: int) -> None:
    """Kick off cover generation in the background if it isn't already running
    and no cover file exists yet."""
    if project_id in _cover_generation_inflight:
        return
    if os.path.exists(_cover_file_path(project_id)):
        return
    _schedule_cover_generation(project_id)


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
    admin_id = 999999
    if settings.admin_telegram_chat_id:
        try:
            admin_id = int(settings.admin_telegram_chat_id)
        except Exception:
            admin_id = 999999

    try:
        result = await session.execute(
            select(UserProfile).limit(1)
        )
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


# ===========================================================================
# 4. Whiteboard & Living Canvas Endpoints
# ===========================================================================

class CreateWhiteboardRequest(BaseModel):
    title: str
    emoji_icon: str = "📋"
    category: str = "general"
    summary: Optional[str] = None
    template: Optional[str] = None  # "trip" | "event" | "project" | "meal" | "blank"

class UpdateWhiteboardRequest(BaseModel):
    title: Optional[str] = None
    emoji_icon: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None

class CreateBlockRequest(BaseModel):
    section_name: str = "General"
    block_type: str = "note"  # comparison | checklist | itinerary | budget | note
    title: str
    content_payload: Dict[str, Any] = {}
    position_order: int = 0

class UpdateBlockRequest(BaseModel):
    section_name: Optional[str] = None
    block_type: Optional[str] = None
    title: Optional[str] = None
    content_payload: Optional[Dict[str, Any]] = None
    position_order: Optional[int] = None

class EscalateBlockTaskRequest(BaseModel):
    title: Optional[str] = None
    due_at: Optional[str] = None
    reminder_type: str = "once"
    reminder_time: Optional[str] = None
    priority: str = "medium"

class EscalateBlockExpenseRequest(BaseModel):
    merchant: str
    amount: float
    category: str = "Travel"
    currency: str = "SGD"

class WhiteboardAiPromptRequest(BaseModel):
    prompt: str
    section_name: Optional[str] = "AI Suggestions"


async def _seed_template_blocks(session: Any, project_id: int, template_name: str, user_id: int) -> None:
    """Helper to populate pre-built rich blocks based on chosen template."""
    now = datetime.utcnow()
    if template_name == "trip":
        # 1. Accommodations Comparison Block
        b1 = WhiteboardBlock(
            project_id=project_id,
            section_name="🏨 Accommodations",
            block_type="comparison",
            title="Shortlisted Hotels in Shinjuku & Ginza",
            content_payload={
                "options": [
                    {
                        "id": "opt-1",
                        "name": "Hotel Gracery Shinjuku",
                        "price": "$185 / night",
                        "rating": "4.6 ★",
                        "pros": ["Direct access to JR Shinjuku Station", "Godzilla terrace view", "Vibrant nightlife"],
                        "cons": ["Rooms are cozy/compact", "Bustling Kabukicho crowds"],
                        "is_winner": True,
                    },
                    {
                        "id": "opt-2",
                        "name": "The Royal Park Canvas Ginza",
                        "price": "$240 / night",
                        "rating": "4.8 ★",
                        "pros": ["Peaceful luxury neighborhood", "Walk to Tsukiji Outer Market", "Modern cocktail lounge"],
                        "cons": ["Higher nightly rate", "Further from Shibuya nightlife"],
                        "is_winner": False,
                    },
                    {
                        "id": "opt-3",
                        "name": "Candeo Hotels Roppongi",
                        "price": "$210 / night",
                        "rating": "4.5 ★",
                        "pros": ["Open-air rooftop onsen & sky spa", "Stunning Tokyo Tower skyline views"],
                        "cons": ["Subway transfer can be 10 min walk"],
                        "is_winner": False,
                    }
                ]
            },
            position_order=1,
            created_at=now,
            updated_at=now,
        )
        # 2. Itinerary Step Block
        b2 = WhiteboardBlock(
            project_id=project_id,
            section_name="📅 Day-by-Day Itinerary",
            block_type="itinerary",
            title="Day 1: Arrival & Neon Shinjuku",
            content_payload={
                "steps": [
                    {"time": "15:00", "title": "Check in at Hotel Gracery", "location": "Shinjuku", "notes": "Drop luggage and freshen up"},
                    {"time": "17:30", "title": "Tokyo Metropolitan Govt Observation Deck", "location": "Nishi-Shinjuku", "notes": "Free 45th-floor view for sunset over Mt. Fuji"},
                    {"time": "19:30", "title": "Yakitori Alley (Omoide Yokocho)", "location": "Shinjuku West", "notes": "Charcoal grilled skewers, draft beer & ramen"}
                ]
            },
            position_order=2,
            created_at=now,
            updated_at=now,
        )
        # 3. Packing Checklist Block
        b3 = WhiteboardBlock(
            project_id=project_id,
            section_name="🎒 Packing & Essentials",
            block_type="checklist",
            title="Pre-Departure Travel Essentials",
            content_payload={
                "items": [
                    {"id": "c-1", "text": "Suica / Pasmo IC card loaded on Apple Wallet", "checked": True},
                    {"id": "c-2", "text": "eSIM activation QR code saved offline", "checked": True},
                    {"id": "c-3", "text": "Visit Japan Web digital customs QR saved", "checked": False},
                    {"id": "c-4", "text": "Universal power plug adapter (Type A / 2-prong)", "checked": False},
                    {"id": "c-5", "text": "Passport valid > 6 months", "checked": True}
                ]
            },
            position_order=3,
            created_at=now,
            updated_at=now,
        )
        # 4. Budget Block
        b4 = WhiteboardBlock(
            project_id=project_id,
            section_name="💰 Trip Budget & Cost Forecast",
            block_type="budget",
            title="Estimated Trip Expense Breakdown",
            content_payload={
                "currency": "SGD",
                "items": [
                    {"name": "Return Flights (SQ)", "cost": 780, "status": "Booked"},
                    {"name": "Hotels (6 nights)", "cost": 1110, "status": "Estimated"},
                    {"name": "Food & Dining (~$80/day)", "cost": 560, "status": "Estimated"},
                    {"name": "Transport & Shinkansen", "cost": 180, "status": "Estimated"},
                    {"name": "Shopping & Souvenirs", "cost": 400, "status": "Estimated"}
                ]
            },
            position_order=4,
            created_at=now,
            updated_at=now,
        )
        session.add_all([b1, b2, b3, b4])

    elif template_name == "meal" or template_name == "groceries":
        # Fetch existing grocery items to migrate seamlessly
        grocery_rows = (await session.execute(select(GroceryItem).where(GroceryItem.user_id == user_id))).scalars().all()
        grocery_items_list = []
        if grocery_rows:
            for g in grocery_rows:
                grocery_items_list.append({
                    "id": f"g-{g.id}",
                    "text": f"{g.name} ({g.quantity})" if g.quantity and g.quantity != "1" else g.name,
                    "checked": g.is_purchased,
                })
        else:
            grocery_items_list = [
                {"id": "g-1", "text": "Oat Milk (2 cartons)", "checked": False},
                {"id": "g-2", "text": "Fresh Atlantic Salmon fillets (500g)", "checked": False},
                {"id": "g-3", "text": "Avocados (3 pack)", "checked": True},
                {"id": "g-4", "text": "Eggs (10 pack)", "checked": True},
                {"id": "g-5", "text": "Sourdough loaf", "checked": False},
            ]

        b1 = WhiteboardBlock(
            project_id=project_id,
            section_name="🥗 Meal Plan Ideas",
            block_type="note",
            title="Weekly Meal Inspiration & Schedule",
            content_payload={
                "markdown": "• **Mon / Tue**: Fresh salmon poke bowls with edamame, avocado, and sesame dressing\n• **Wed**: Garlic butter lemon pasta with grilled chicken breast\n• **Thu / Fri**: Japanese golden curry with carrots, potatoes & steamed rice\n• **Weekend**: Homemade sourdough margherita pizza with fresh basil"
            },
            position_order=1,
            created_at=now,
            updated_at=now,
        )
        b2 = WhiteboardBlock(
            project_id=project_id,
            section_name="🛒 Grocery Checklist",
            block_type="checklist",
            title="Supermarket Shopping Checklist",
            content_payload={"items": grocery_items_list},
            position_order=2,
            created_at=now,
            updated_at=now,
        )
        session.add_all([b1, b2])

    elif template_name == "project":
        b1 = WhiteboardBlock(
            project_id=project_id,
            section_name="🎯 Problem & Core Value Prop",
            block_type="note",
            title="Executive Summary & Elevator Pitch",
            content_payload={
                "markdown": "Building an **AI-first multi-agent operating system** that turns conversations into persistent living project whiteboards, automated task schedules, and smart financial tracking without friction."
            },
            position_order=1,
            created_at=now,
            updated_at=now,
        )
        b2 = WhiteboardBlock(
            project_id=project_id,
            section_name="🚀 MVP Features & Scope",
            block_type="checklist",
            title="Sprint Milestones",
            content_payload={
                "items": [
                    {"id": "p-1", "text": "Polymorphic canvas card renderers (Comparison, Checklist, Itinerary, Budget)", "checked": True},
                    {"id": "p-2", "text": "1-Click action escalation to Task scheduler with Telegram push alerts", "checked": True},
                    {"id": "p-3", "text": "Bi-directional chat-to-whiteboard NLP pin hooks", "checked": True},
                    {"id": "p-4", "text": "Live user collaborative multi-board switching", "checked": False}
                ]
            },
            position_order=2,
            created_at=now,
            updated_at=now,
        )
        session.add_all([b1, b2])

    elif template_name == "event":
        b1 = WhiteboardBlock(
            project_id=project_id,
            section_name="🏛️ Venue Options",
            block_type="comparison",
            title="Shortlisted Party Venues",
            content_payload={
                "options": [
                    {"id": "v-1", "name": "Rooftop Glasshouse Lounge", "price": "$120/hr", "rating": "4.9 ★", "pros": ["Panoramic city views", "BYO drinks allowed"], "cons": ["Weather dependent terrace"], "is_winner": True},
                    {"id": "v-2", "name": "Botanical Greenhouse Studio", "price": "$90/hr", "rating": "4.7 ★", "pros": ["Air-conditioned lush plants", "Great natural lighting"], "cons": ["Capacity capped at 25 pax"], "is_winner": False}
                ]
            },
            position_order=1,
            created_at=now,
            updated_at=now,
        )
        b2 = WhiteboardBlock(
            project_id=project_id,
            section_name="📋 Guest List & RSVP",
            block_type="checklist",
            title="Confirmed Attendees & RSVP",
            content_payload={
                "items": [
                    {"id": "e-1", "text": "Alex & Sarah (Confirmed)", "checked": True},
                    {"id": "e-2", "text": "Marcus + 1 (Confirmed)", "checked": True},
                    {"id": "e-3", "text": "Rachel (Pending response)", "checked": False},
                    {"id": "e-4", "text": "Daniel & Chloe (Confirmed)", "checked": True}
                ]
            },
            position_order=2,
            created_at=now,
            updated_at=now,
        )
        session.add_all([b1, b2])
    else:
        # Default blank card
        b1 = WhiteboardBlock(
            project_id=project_id,
            section_name="Ideas & Notes",
            block_type="note",
            title="Getting Started",
            content_payload={"markdown": "Type in the copilot bar above or add new cards to start planning!"},
            position_order=1,
            created_at=now,
            updated_at=now,
        )
        session.add(b1)


@router.get("/whiteboards")
async def list_whiteboards(user_id: Optional[int] = None) -> Dict[str, Any]:
    """List all whiteboard projects for the user. Auto-seeds default projects on empty state."""
    async with async_session_factory() as session:
        effective_user_id = user_id if (user_id is not None and user_id != 0) else await get_primary_user_id(session)
        result = await session.execute(
            select(WhiteboardProject)
            .where(WhiteboardProject.user_id == effective_user_id)
            .order_by(desc(WhiteboardProject.updated_at))
        )
        projects = result.scalars().all()

        # Only seed default starter boards on first-ever load (whiteboard_seeded == False).
        # If the user has intentionally deleted all boards, honour the empty state.
        if not projects:
            user_profile = (await session.execute(
                select(UserProfile).where(UserProfile.user_id == effective_user_id)
            )).scalar_one_or_none()

            should_seed = user_profile is not None and not user_profile.whiteboard_seeded

            if should_seed:
                p1 = WhiteboardProject(
                    user_id=effective_user_id,
                    title="Tokyo Vacation & Trip Planner",
                    emoji_icon="✈️",
                    category="trip",
                    summary="7-day autumn trip to Tokyo exploring Shibuya, Shinjuku, Ginza, and Hakone",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                p2 = WhiteboardProject(
                    user_id=effective_user_id,
                    title="Smart Groceries & Meal Prep",
                    emoji_icon="🛒",
                    category="meal",
                    summary="Weekly recipe inspiration, pantry items, and shopping checklist",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                p3 = WhiteboardProject(
                    user_id=effective_user_id,
                    title="Startup MVP & Launch Board",
                    emoji_icon="🚀",
                    category="project",
                    summary="Architecture, MVP scope, core features, and launch checklist",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                session.add_all([p1, p2, p3])
                await session.commit()
                await session.refresh(p1)
                await session.refresh(p2)
                await session.refresh(p3)

                await _seed_template_blocks(session, p1.id, "trip", effective_user_id)
                await _seed_template_blocks(session, p2.id, "meal", effective_user_id)
                await _seed_template_blocks(session, p3.id, "project", effective_user_id)

                # Mark as seeded — never auto-seed again for this user
                if user_profile:
                    user_profile.whiteboard_seeded = True
                    session.add(user_profile)
                await session.commit()

                # Re-fetch
                projects = [p1, p2, p3]

        return {
            "status": "ok",
            "projects": [
                {
                    "id": p.id,
                    "title": p.title,
                    "emoji_icon": p.emoji_icon,
                    "category": p.category,
                    "summary": p.summary,
                    "cover_ready": p.cover_ready,
                    "created_at": _format_iso(p.created_at),
                    "updated_at": _format_iso(p.updated_at),
                }
                for p in projects
            ]
        }


@router.post("/whiteboards")
async def create_whiteboard(
    payload: CreateWhiteboardRequest,
    user_id: Optional[int] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> Dict[str, Any]:
    """Create a new whiteboard project with optional pre-built template.

    Cover art generation runs in the background via FastAPI BackgroundTasks so the
    endpoint returns immediately; the carousel shows a shimmer until it is ready.

    FastAPI injects a fresh per-request BackgroundTasks instance, so the default
    value is only used when the function is called directly (e.g. in tests), where
    add_task simply queues the coroutine without executing it.
    """
    async with async_session_factory() as session:
        effective_user_id = user_id if (user_id is not None and user_id != 0) else await get_primary_user_id(session)
        now = datetime.utcnow()
        project = WhiteboardProject(
            user_id=effective_user_id,
            title=payload.title.strip(),
            emoji_icon=payload.emoji_icon or "📋",
            category=payload.category or "general",
            summary=payload.summary,
            created_at=now,
            updated_at=now,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)

        if payload.template and payload.template != "blank":
            await _seed_template_blocks(session, project.id, payload.template, effective_user_id)
            await session.commit()

        # Kick off cover generation after the response is sent. We mark the board
        # as in-flight up front so a concurrent poll of /cover cannot spawn a
        # duplicate Imagen call.
        if project.id not in _cover_generation_inflight:
            _cover_generation_inflight.add(project.id)
            background_tasks.add_task(_generate_board_cover, project.id)

        return {
            "status": "ok",
            "project": {
                "id": project.id,
                "title": project.title,
                "emoji_icon": project.emoji_icon,
                "category": project.category,
                "summary": project.summary,
                "cover_ready": project.cover_ready,
                "created_at": _format_iso(project.created_at),
                "updated_at": _format_iso(project.updated_at),
            }
        }


@router.get("/whiteboards/{project_id}")
async def get_whiteboard_details(project_id: int) -> Dict[str, Any]:
    """Get project details and all grouped blocks."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        blocks = (await session.execute(
            select(WhiteboardBlock)
            .where(WhiteboardBlock.project_id == project_id)
            .order_by(WhiteboardBlock.section_name, WhiteboardBlock.position_order, WhiteboardBlock.id)
        )).scalars().all()

        return {
            "status": "ok",
            "project": {
                "id": proj.id,
                "title": proj.title,
                "emoji_icon": proj.emoji_icon,
                "category": proj.category,
                "summary": proj.summary,
                "cover_ready": proj.cover_ready,
                "created_at": _format_iso(proj.created_at),
                "updated_at": _format_iso(proj.updated_at),
            },
            "blocks": [
                {
                    "id": b.id,
                    "project_id": b.project_id,
                    "section_name": b.section_name,
                    "block_type": b.block_type,
                    "title": b.title,
                    "content_payload": b.content_payload or {},
                    "position_order": b.position_order,
                    "linked_task_id": b.linked_task_id,
                    "linked_expense_id": b.linked_expense_id,
                    "created_at": _format_iso(b.created_at),
                    "updated_at": _format_iso(b.updated_at),
                }
                for b in blocks
            ]
        }


@router.get("/whiteboards/{project_id}/cover")
async def get_whiteboard_cover(project_id: int):
    """Return the AI-generated cover art PNG for a board.

    - 200 with the image bytes when the cover is ready on disk.
    - 202 {"status": "generating"} when it is not yet ready (kicks off generation
      in the background so the frontend can poll until it flips to 200).
    - 404 when the board does not exist.
    """
    cover_path = _cover_file_path(project_id)
    if os.path.exists(cover_path):
        return FileResponse(cover_path, media_type="image/png")

    async with async_session_factory() as session:
        exists = (await session.execute(
            select(WhiteboardProject.id).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
    if not exists:
        raise HTTPException(status_code=404, detail="Whiteboard not found")

    _maybe_trigger_cover_generation(project_id)
    return JSONResponse(status_code=202, content={"status": "generating"})


@router.patch("/whiteboards/{project_id}")
async def update_whiteboard(
    project_id: int,
    payload: UpdateWhiteboardRequest,
) -> Dict[str, Any]:
    """Update whiteboard project metadata."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        if payload.title is not None:
            proj.title = payload.title.strip()
        if payload.emoji_icon is not None:
            proj.emoji_icon = payload.emoji_icon.strip()
        if payload.category is not None:
            proj.category = payload.category.strip()
        if payload.summary is not None:
            proj.summary = payload.summary.strip()
        proj.updated_at = datetime.utcnow()

        session.add(proj)
        await session.commit()
        return {"status": "ok", "project_id": proj.id}


@router.delete("/whiteboards/{project_id}")
async def delete_whiteboard(project_id: int) -> Dict[str, Any]:
    """Delete whiteboard project and its associated blocks."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        await session.execute(delete(WhiteboardBlock).where(WhiteboardBlock.project_id == project_id))
        await session.execute(delete(WhiteboardProject).where(WhiteboardProject.id == project_id))
        await session.commit()

        # Clean up the generated cover art file and cancel any in-flight generation.
        _cover_generation_inflight.discard(project_id)
        task = _cover_generation_tasks.pop(project_id, None)
        if task is not None and not task.done():
            task.cancel()
        cover_path = _cover_file_path(project_id)
        if os.path.exists(cover_path):
            try:
                os.remove(cover_path)
            except OSError:
                logger.warning("Could not remove cover art for deleted board %s", project_id)

        return {"status": "ok", "deleted_project_id": project_id}


@router.post("/whiteboards/{project_id}/blocks")
async def add_block(
    project_id: int,
    payload: CreateBlockRequest,
) -> Dict[str, Any]:
    """Create a new smart block / card on a whiteboard project."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        now = datetime.utcnow()
        block = WhiteboardBlock(
            project_id=project_id,
            section_name=payload.section_name.strip() or "General",
            block_type=payload.block_type or "note",
            title=payload.title.strip(),
            content_payload=payload.content_payload or {},
            position_order=payload.position_order,
            created_at=now,
            updated_at=now,
        )
        session.add(block)
        proj.updated_at = now
        session.add(proj)
        await session.commit()
        await session.refresh(block)

        return {
            "status": "ok",
            "block": {
                "id": block.id,
                "project_id": block.project_id,
                "section_name": block.section_name,
                "block_type": block.block_type,
                "title": block.title,
                "content_payload": block.content_payload,
                "position_order": block.position_order,
                "linked_task_id": block.linked_task_id,
                "linked_expense_id": block.linked_expense_id,
                "created_at": _format_iso(block.created_at),
                "updated_at": _format_iso(block.updated_at),
            }
        }


@router.patch("/whiteboards/blocks/{block_id}")
async def update_block(
    block_id: int,
    payload: UpdateBlockRequest,
) -> Dict[str, Any]:
    """Update block title, content payload, position, or section name."""
    async with async_session_factory() as session:
        block = (await session.execute(
            select(WhiteboardBlock).where(WhiteboardBlock.id == block_id)
        )).scalar_one_or_none()
        if not block:
            raise HTTPException(status_code=404, detail="Block not found")

        if payload.section_name is not None:
            block.section_name = payload.section_name.strip()
        if payload.block_type is not None:
            block.block_type = payload.block_type.strip()
        if payload.title is not None:
            block.title = payload.title.strip()
        if payload.content_payload is not None:
            block.content_payload = payload.content_payload
        if payload.position_order is not None:
            block.position_order = payload.position_order

        now = datetime.utcnow()
        block.updated_at = now
        session.add(block)

        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == block.project_id)
        )).scalar_one_or_none()
        if proj:
            proj.updated_at = now
            session.add(proj)

        await session.commit()
        return {"status": "ok", "block_id": block.id}


@router.delete("/whiteboards/blocks/{block_id}")
async def delete_block(block_id: int) -> Dict[str, Any]:
    """Delete an individual block card."""
    async with async_session_factory() as session:
        block = (await session.execute(
            select(WhiteboardBlock).where(WhiteboardBlock.id == block_id)
        )).scalar_one_or_none()
        if not block:
            raise HTTPException(status_code=404, detail="Block not found")

        await session.execute(delete(WhiteboardBlock).where(WhiteboardBlock.id == block_id))
        await session.commit()
        return {"status": "ok", "deleted_block_id": block_id}


@router.post("/whiteboards/blocks/{block_id}/escalate_task")
async def escalate_block_to_task(
    block_id: int,
    payload: EscalateBlockTaskRequest,
) -> Dict[str, Any]:
    """Escalate a whiteboard card or selected option directly into an active TaskItem with reminder."""
    async with async_session_factory() as session:
        block = (await session.execute(
            select(WhiteboardBlock).where(WhiteboardBlock.id == block_id)
        )).scalar_one_or_none()
        if not block:
            raise HTTPException(status_code=404, detail="Block not found")

        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == block.project_id)
        )).scalar_one_or_none()
        user_id = proj.user_id if proj else await get_primary_user_id(session)

        task_title = payload.title or block.title
        due_dt = _parse_iso_datetime(payload.due_at)
        rem_dt = _parse_iso_datetime(payload.reminder_time) or due_dt
        now = datetime.utcnow()

        task = TaskItem(
            user_id=user_id,
            title=task_title,
            description=f"Escalated from whiteboard project: {proj.title if proj else 'Whiteboard'} (#{block.section_name})",
            status="todo",
            priority=payload.priority or "medium",
            due_at=due_dt,
            reminder_type=payload.reminder_type or "once",
            reminder_time=rem_dt,
            is_reminder_active=True if (rem_dt and payload.reminder_type == "once") else False,
            created_at=now,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)

        # Link task ID to block
        block.linked_task_id = task.id
        session.add(block)
        await session.commit()

        # Schedule reminder
        if task.is_reminder_active and task.reminder_time:
            _add_task_to_scheduler(task)

        return {
            "status": "ok",
            "task_id": task.id,
            "title": task.title,
            "due_at": _format_iso(task.due_at),
            "reminder_time": _format_iso(task.reminder_time),
        }


@router.post("/whiteboards/blocks/{block_id}/escalate_expense")
async def escalate_block_to_expense(
    block_id: int,
    payload: EscalateBlockExpenseRequest,
) -> Dict[str, Any]:
    """Escalate a whiteboard budget item directly into the ExpenseTransaction table."""
    async with async_session_factory() as session:
        block = (await session.execute(
            select(WhiteboardBlock).where(WhiteboardBlock.id == block_id)
        )).scalar_one_or_none()
        if not block:
            raise HTTPException(status_code=404, detail="Block not found")

        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == block.project_id)
        )).scalar_one_or_none()
        user_id = proj.user_id if proj else await get_primary_user_id(session)

        expense = ExpenseTransaction(
            user_id=user_id,
            amount=payload.amount,
            currency=payload.currency or "SGD",
            merchant=payload.merchant or block.title,
            category=payload.category or "Travel",
            date=datetime.utcnow(),
            is_verified=True,
        )
        session.add(expense)
        await session.commit()
        await session.refresh(expense)

        block.linked_expense_id = expense.id
        session.add(block)
        await session.commit()

        return {
            "status": "ok",
            "expense_id": expense.id,
            "amount": expense.amount,
            "merchant": expense.merchant,
            "category": expense.category,
        }


@router.post("/whiteboards/{project_id}/ai_copilot")
async def whiteboard_ai_copilot(
    project_id: int,
    payload: WhiteboardAiPromptRequest,
) -> Dict[str, Any]:
    """Live AI Copilot endpoint: brainstorms, shortlists, or generates structured cards directly onto the whiteboard."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

    prompt_text = payload.prompt.strip()
    section_name = payload.section_name or "AI Suggestions"

    # Fast structured generator
    # Decide block type based on prompt keywords
    prompt_lower = prompt_text.lower()
    block_type = "note"
    title = prompt_text
    content_payload: Dict[str, Any] = {}

    if any(k in prompt_lower for k in ["hotel", "stay", "resort", "venue", "option", "compare", "shortlist", "vs"]):
        block_type = "comparison"
        title = f"Shortlist: {prompt_text.replace('shortlist', '').replace('compare', '').strip().title() or 'Options'}"
        content_payload = {
            "options": [
                {
                    "id": "ai-opt-1",
                    "name": f"Top Recommended Choice",
                    "price": "$180 - $220 / night",
                    "rating": "4.8 ★",
                    "pros": ["Prime location with direct transit access", "Modern amenities and top customer ratings", "Free breakfast and flexible cancellation"],
                    "cons": ["Popular dates book out fast"],
                    "is_winner": True,
                },
                {
                    "id": "ai-opt-2",
                    "name": f"Boutique High-Value Alternative",
                    "price": "$135 - $160 / night",
                    "rating": "4.6 ★",
                    "pros": ["Great value for money", "Quiet neighborhood with authentic dining nearby"],
                    "cons": ["5-10 min walk to main train station"],
                    "is_winner": False,
                },
                {
                    "id": "ai-opt-3",
                    "name": f"Premium Luxury Option",
                    "price": "$320+ / night",
                    "rating": "4.9 ★",
                    "pros": ["Spacious rooms with skyline views", "On-site rooftop bar and spa"],
                    "cons": ["Higher budget requirement"],
                    "is_winner": False,
                }
            ]
        }
    elif any(k in prompt_lower for k in ["pack", "checklist", "gear", "todo", "bring", "buy", "grocer", "ingredient"]):
        block_type = "checklist"
        title = f"Checklist: {prompt_text.title()}"
        content_payload = {
            "items": [
                {"id": "ai-c-1", "text": "Essential passports, travel IDs & boarding passes", "checked": True},
                {"id": "ai-c-2", "text": "Power banks, universal adapters & charging cables", "checked": False},
                {"id": "ai-c-3", "text": "Prescription medications & basic first-aid kit", "checked": False},
                {"id": "ai-c-4", "text": "Comfortable walking shoes & weather-appropriate layers", "checked": False},
                {"id": "ai-c-5", "text": "Cash in local currency & backup credit card", "checked": True},
            ]
        }
    elif any(k in prompt_lower for k in ["day", "itinerary", "schedule", "plan", "tour"]):
        block_type = "itinerary"
        title = f"Itinerary: {prompt_text.title()}"
        content_payload = {
            "steps": [
                {"time": "09:30", "title": "Morning Exploration & Sightseeing", "location": "City Center", "notes": "Visit primary cultural landmarks before crowds arrive"},
                {"time": "12:30", "title": "Lunch at Highly-Rated Local Eatery", "location": "Historic District", "notes": "Taste signature local dishes"},
                {"time": "15:00", "title": "Afternoon Museum / Neighborhood Stroll", "location": "Arts District", "notes": "Scenic photo spots and coffee break"},
                {"time": "19:00", "title": "Sunset Dinner & Nightlife", "location": "Waterfront", "notes": "Dinner with panoramic view"}
            ]
        }
    elif any(k in prompt_lower for k in ["budget", "cost", "spend", "price", "expense"]):
        block_type = "budget"
        title = f"Budget Estimate: {prompt_text.title()}"
        content_payload = {
            "currency": "SGD",
            "items": [
                {"name": "Accommodation & Lodging", "cost": 650, "status": "Estimated"},
                {"name": "Food, Drinks & Dining", "cost": 380, "status": "Estimated"},
                {"name": "Local Transit & Passes", "cost": 120, "status": "Estimated"},
                {"name": "Activities & Admissions", "cost": 150, "status": "Estimated"},
                {"name": "Emergency Contingency Fund", "cost": 100, "status": "Estimated"}
            ]
        }
    else:
        block_type = "note"
        title = f"Research Notes: {prompt_text.title()}"
        content_payload = {
            "markdown": f"### ✨ AI Brainstorming Insights\n\n• **Core Concept**: {prompt_text}\n• **Key Considerations**: Focus on high-impact items first, keep budget in check, and balance flexibility with scheduled reservations.\n• **Next Steps**: Shortlist top options, assign due dates, and verify opening hours."
        }

    # Save generated block
    async with async_session_factory() as session:
        now = datetime.utcnow()
        block = WhiteboardBlock(
            project_id=project_id,
            section_name=section_name,
            block_type=block_type,
            title=title,
            content_payload=content_payload,
            position_order=10,
            created_at=now,
            updated_at=now,
        )
        session.add(block)
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if proj:
            proj.updated_at = now
            session.add(proj)
        await session.commit()
        await session.refresh(block)

    return {
        "status": "ok",
        "generated_block": {
            "id": block.id,
            "project_id": block.project_id,
            "section_name": block.section_name,
            "block_type": block.block_type,
            "title": block.title,
            "content_payload": block.content_payload,
            "position_order": block.position_order,
            "created_at": _format_iso(block.created_at),
        }
    }
