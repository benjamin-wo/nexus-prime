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
import re
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Literal, Optional, assert_never
from urllib.parse import urlparse
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import select, delete, func, desc
from sqlalchemy import or_, update

from core.db import async_session_factory
from core.config import settings
from capabilities.whiteboard.tools import DEFAULT_SECTION_TEMPLATES
from core.models import (
    ExpenseTransaction,
    IncomeTransaction,
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
from capabilities.expenses.settlement import IouSettlementCommand, settle_iou

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
        "Artsy Narrative Landscape illustration for a compact web card. "
        "Wide landscape composition, 16:9 aspect ratio, 1K web-thumbnail detail, "
        "subject centered with generous safe margins so it crops cleanly inside a "
        "260x150px card. Do not create a portrait poster or tall vertical banner. "
        f"Theme: {subject}. "
        f"{'Context: ' + context + '. ' if context else ''}"
        f"Sky: {theme['sky']}. Foreground: {theme['foreground']}. "
        f"Aurora: {theme['aurora']}. "
        "Cinematic lighting, rich painterly detail, soft depth of field, "
        "no text, no words, no letters, no logos."
    )


def _cover_file_path(project_id: int) -> str:
    return os.path.join(BOARD_COVERS_DIR, f"{project_id}.png")


def _cover_cache_version(project_id: int) -> Optional[str]:
    """Return a stable browser-cache version for the persisted cover file."""
    try:
        return str(os.stat(_cover_file_path(project_id)).st_mtime_ns)
    except OSError:
        return None


def _cover_cache_headers(project_id: int) -> Dict[str, str]:
    """Cache cover bytes aggressively while allowing a new file to invalidate them."""
    version = _cover_cache_version(project_id) or "pending"
    return {
        "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
        "ETag": f'W/"board-cover-{project_id}-{version}"',
    }


async def _generate_board_cover(project_id: int) -> None:
    """Generate Imagen cover art for a board and persist it to disk.

    Safe to run as a background task: fetches the project from the DB, builds a
    category-aware prompt, calls Imagen, writes the PNG to BOARD_COVERS_DIR and
    finally flips WhiteboardProject.cover_ready to True. Any failure leaves the
    flag False so a later poll can retry.
    """
    try:
        # The durable file is the source of truth. A restart, repeated GET, or
        # a second worker must reuse it without spending another image token.
        if os.path.isfile(_cover_file_path(project_id)):
            async with async_session_factory() as session:
                proj = (await session.execute(
                    select(WhiteboardProject).where(WhiteboardProject.id == project_id)
                )).scalar_one_or_none()
                if proj and not proj.cover_ready:
                    proj.cover_ready = True
                    session.add(proj)
                    await session.commit()
            logger.info("Reusing cached cover art for board %s", project_id)
            return

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
                "max_output_tokens": 1024,
                "top_p": 0.95,
                "thinking_level": "minimal",
                "image_config": {
                    "aspect_ratio": "16:9",
                    "image_size": "1K",
                },
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
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash-image",
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE"],
                            max_output_tokens=1024,
                            image_config=types.ImageConfig(
                                aspect_ratio="16:9",
                                image_size="1K",
                            ),
                        ),
                    )
                except Exception as config_exc:
                    # Older image model revisions may reject image_size while
                    # still accepting the prompt/aspect ratio path.
                    logger.info("Image config rejected for board %s, retrying minimal config: %s", project_id, config_exc)
                    response = client.models.generate_content(
                        model="gemini-2.5-flash-image",
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE"],
                            max_output_tokens=1024,
                            image_config=types.ImageConfig(aspect_ratio="16:9"),
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
            "pending_groceries_count": groceries_pending,
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


def _expense_to_transaction(item: ExpenseTransaction) -> Dict[str, Any]:
    """Serialize an expense using the unified transaction contract."""
    split_data = item.split_data or {}
    split_status, pending_count, pending_amount = _split_payment_summary(split_data)
    return {
        "id": f"outgoing:{item.id}",
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
        "id": f"incoming:{item.id}",
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
            f"outgoing:{item.linked_expense_id}"
            if item.linked_expense_id
            else None
        ),
        "pending_iou_count": 0,
        "pending_iou_amount": 0.0,
        "split_data": {},
    }


def _parse_transaction_key(value: str) -> tuple[str, int] | None:
    """Parse a stable unified transaction key such as ``incoming:14``."""
    direction, separator, raw_id = value.partition(":")
    if not separator or direction not in {"outgoing", "incoming"} or not raw_id.isdigit():
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


class SyncGroceriesRequest(BaseModel):
    items: List[str] = Field(default=[], description="List of item names to check off")


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


@router.post("/expenses/{expense_id}/sync-groceries")
async def sync_expense_groceries(
    expense_id: int,
    req: SyncGroceriesRequest,
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Match receipt grocery items against pending GroceryItem checklist and check them off."""
    from core.models import GroceryItem
    async with async_session_factory() as session:
        query = select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        if user_id is not None and user_id != 0:
            query = query.where(ExpenseTransaction.user_id == user_id)
        result = await session.execute(query)
        tx = result.scalar_one_or_none()
        if not tx:
            raise HTTPException(status_code=404, detail="Expense not found")
        
        user_id = tx.user_id
        checked_off = []
        items_to_sync = req.items
        if not items_to_sync and tx.receipt_items:
            items_to_sync = [it.get("name") for it in tx.receipt_items if it.get("name")]

        grocery_res = await session.execute(
            select(GroceryItem).where(GroceryItem.user_id == user_id, GroceryItem.is_purchased == False)
        )
        unpurchased = grocery_res.scalars().all()

        for g_item in unpurchased:
            for name in items_to_sync:
                if name and (name.lower() in g_item.name.lower() or g_item.name.lower() in name.lower()):
                    g_item.is_purchased = True
                    session.add(g_item)
                    checked_off.append(g_item.name)
                    break
        
        await session.commit()
        return {
            "status": "ok",
            "checked_off_count": len(checked_off),
            "checked_off_items": checked_off,
            "message": f"Checked off {len(checked_off)} matching items from grocery list.",
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
        # Whiteboard cards retain their content after escalation, so detach
        # their optional task link before removing the referenced task.
        await session.execute(
            update(WhiteboardBlock)
            .where(WhiteboardBlock.linked_task_id == task_id)
            .values(linked_task_id=None)
        )
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

class SectionReorderEntry(BaseModel):
    name: str
    block_ids: List[int] = []

class ReorderWhiteboardRequest(BaseModel):
    """Full-canvas ordering: section order + per-section block order."""
    section_order: Optional[List[str]] = None
    sections: Optional[List[SectionReorderEntry]] = None

class SectionOpRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)

class SectionRenameRequest(BaseModel):
    old_name: str = Field(min_length=1, max_length=80)
    new_name: str = Field(min_length=1, max_length=80)


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
                    "cover_ready": bool(_cover_cache_version(p.id)),
                    "cover_version": _cover_cache_version(p.id),
                    "section_order": p.section_order or [],
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
        category = payload.category or "general"
        project = WhiteboardProject(
            user_id=effective_user_id,
            title=payload.title.strip(),
            emoji_icon=payload.emoji_icon or "📋",
            category=category,
            summary=payload.summary,
            section_order=DEFAULT_SECTION_TEMPLATES.get(category, DEFAULT_SECTION_TEMPLATES["general"]),
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
                "cover_ready": bool(_cover_cache_version(project.id)),
                "cover_version": _cover_cache_version(project.id),
                "section_order": project.section_order or [],
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
                "cover_ready": bool(_cover_cache_version(proj.id)),
                "cover_version": _cover_cache_version(proj.id),
                "section_order": proj.section_order or [],
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
        return FileResponse(
            cover_path,
            media_type="image/png",
            headers=_cover_cache_headers(project_id),
        )

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
        section = payload.section_name.strip() or "General"
        block = WhiteboardBlock(
            project_id=project_id,
            section_name=section,
            block_type=payload.block_type or "note",
            title=payload.title.strip(),
            content_payload=payload.content_payload or {},
            position_order=payload.position_order,
            created_at=now,
            updated_at=now,
        )
        session.add(block)
        proj.updated_at = now
        order = list(proj.section_order or [])
        if section not in order:
            order.append(section)
            proj.section_order = order
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


@router.post("/whiteboards/{project_id}/reorder")
async def reorder_whiteboard(project_id: int, payload: ReorderWhiteboardRequest) -> Dict[str, Any]:
    """Persist canvas ordering: section order and per-section card order."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        if payload.section_order is not None:
            proj.section_order = [s.strip() for s in payload.section_order if s.strip()]

        if payload.sections:
            blocks = (await session.execute(
                select(WhiteboardBlock).where(WhiteboardBlock.project_id == project_id)
            )).scalars().all()
            by_id = {b.id: b for b in blocks}
            for sec in payload.sections:
                for idx, block_id in enumerate(sec.block_ids):
                    block = by_id.get(block_id)
                    if block is None:
                        continue
                    block.position_order = idx
                    block.section_name = sec.name.strip() or block.section_name
                    block.updated_at = datetime.utcnow()
                    session.add(block)

        proj.updated_at = datetime.utcnow()
        session.add(proj)
        await session.commit()
        return {"status": "ok", "section_order": proj.section_order or []}


@router.post("/whiteboards/{project_id}/sections")
async def add_section(project_id: int, payload: SectionOpRequest) -> Dict[str, Any]:
    """Register a new (initially empty) section on the board."""
    name = payload.name.strip()
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        order = list(proj.section_order or [])
        if name in order:
            raise HTTPException(status_code=409, detail=f"Section '{name}' already exists")
        order.append(name)
        proj.section_order = order
        proj.updated_at = datetime.utcnow()
        session.add(proj)
        await session.commit()
        return {"status": "ok", "section_order": order}


@router.patch("/whiteboards/{project_id}/sections")
async def rename_section(project_id: int, payload: SectionRenameRequest) -> Dict[str, Any]:
    """Rename a section across every block and the board's section order."""
    old_name = payload.old_name.strip()
    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="New section name cannot be empty")

    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        blocks = (await session.execute(
            select(WhiteboardBlock).where(
                WhiteboardBlock.project_id == project_id,
                WhiteboardBlock.section_name == old_name,
            )
        )).scalars().all()

        order = list(proj.section_order or [])
        if old_name not in order and not blocks:
            raise HTTPException(status_code=404, detail=f"Section '{old_name}' not found")

        for b in blocks:
            b.section_name = new_name
            b.updated_at = datetime.utcnow()
            session.add(b)

        # Merge gracefully if target section already exists
        if new_name in order:
            proj.section_order = [s for s in order if s != old_name]
        else:
            proj.section_order = [new_name if s == old_name else s for s in order]

        proj.updated_at = datetime.utcnow()
        session.add(proj)
        await session.commit()
        return {"status": "ok", "renamed_blocks": len(blocks), "section_order": proj.section_order}


@router.delete("/whiteboards/{project_id}/sections")
async def delete_section(project_id: int, name: str) -> Dict[str, Any]:
    """Delete a section, its cards, and its entry in the section order."""
    async with async_session_factory() as session:
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if not proj:
            raise HTTPException(status_code=404, detail="Whiteboard project not found")

        result = await session.execute(
            delete(WhiteboardBlock).where(
                WhiteboardBlock.project_id == project_id,
                WhiteboardBlock.section_name == name.strip(),
            )
        )
        removed_cards = result.rowcount or 0

        order = list(proj.section_order or [])
        proj.section_order = [s for s in order if s != name.strip()]
        proj.updated_at = datetime.utcnow()
        session.add(proj)
        await session.commit()
        return {"status": "ok", "deleted_cards": removed_cards, "section_order": proj.section_order}


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


def _validate_generated_block(raw: Any) -> Optional[Dict[str, Any]]:
    """Validate an LLM-generated block dict; returns normalized block fields or None."""
    if not isinstance(raw, dict):
        return None
    block_type = raw.get("block_type")
    title = str(raw.get("title") or "").strip()
    payload = raw.get("content_payload")
    if block_type not in ("comparison", "checklist", "itinerary", "budget", "note"):
        return None
    if not title:
        return None
    if not isinstance(payload, dict):
        return None

    section_name = str(raw.get("section_name") or "").strip()[:60]
    result = {"section_name": section_name}

    if block_type == "comparison":
        options = payload.get("options")
        if not isinstance(options, list) or len(options) < 2:
            return None
        clean_options = []
        for idx, opt in enumerate(options[:6]):
            if not isinstance(opt, dict) or not str(opt.get("name") or "").strip():
                continue
            clean_options.append({
                "id": f"ai-opt-{idx + 1}",
                "name": str(opt.get("name")).strip()[:80],
                "price": str(opt.get("price") or "").strip()[:40],
                "rating": str(opt.get("rating") or "").strip()[:12],
                "pros": [str(p).strip()[:120] for p in (opt.get("pros") or []) if str(p).strip()][:4],
                "cons": [str(c).strip()[:120] for c in (opt.get("cons") or []) if str(c).strip()][:4],
                "is_winner": bool(opt.get("is_winner")) and len(clean_options) == 0,
            })
        if len(clean_options) < 2:
            return None
        # Guarantee exactly one winner
        if not any(o["is_winner"] for o in clean_options):
            clean_options[0]["is_winner"] = True
        else:
            seen_winner = False
            for o in clean_options:
                if o["is_winner"]:
                    if seen_winner:
                        o["is_winner"] = False
                    seen_winner = True
        return {**result, "block_type": block_type, "title": title[:120], "content_payload": {"options": clean_options}}

    if block_type == "checklist":
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return None
        clean_items = []
        for idx, item in enumerate(items[:20]):
            text = str(item.get("text") if isinstance(item, dict) else item or "").strip()
            if not text:
                continue
            clean_items.append({"id": f"ai-c-{idx + 1}", "text": text[:140], "checked": False})
        if not clean_items:
            return None
        return {**result, "block_type": block_type, "title": title[:120], "content_payload": {"items": clean_items}}

    if block_type == "itinerary":
        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps:
            return None
        clean_steps = []
        for s in steps[:12]:
            if not isinstance(s, dict) or not str(s.get("title") or "").strip():
                continue
            clean_steps.append({
                "time": str(s.get("time") or "").strip()[:10],
                "title": str(s.get("title")).strip()[:100],
                "location": str(s.get("location") or "").strip()[:80],
                "notes": str(s.get("notes") or "").strip()[:200],
            })
        if not clean_steps:
            return None
        return {**result, "block_type": block_type, "title": title[:120], "content_payload": {"steps": clean_steps}}

    if block_type == "budget":
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            return None
        clean_items = []
        for item in items[:15]:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            try:
                cost = round(float(item.get("cost")), 2)
            except (TypeError, ValueError):
                continue
            clean_items.append({
                "name": str(item.get("name")).strip()[:80],
                "cost": cost,
                "status": str(item.get("status") or "Estimated").strip()[:20],
            })
        if not clean_items:
            return None
        currency = str(payload.get("currency") or "SGD").strip().upper()[:5]
        return {**result, "block_type": block_type, "title": title[:120], "content_payload": {"currency": currency, "items": clean_items}}

    # note
    markdown = str(payload.get("markdown") or "").strip()
    if not markdown:
        return None
    return {**result, "block_type": "note", "title": title[:120], "content_payload": {"markdown": markdown[:2000]}}


async def _llm_generate_block_json(prompt: str, board_context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ask the LLM to generate one structured whiteboard card. Returns validated fields or None."""
    from core.llm import ThinkingLevel, get_agent_llm
    import json as _json
    import re as _re

    if not settings.has_llm_key:
        return None

    existing = board_context.get("existing_sections") or []
    system_prompt = (
        "You are the AI copilot of a visual planning whiteboard. Generate exactly ONE card "
        "for the user's request. Reply with ONLY a JSON object:\n"
        '{"block_type": "comparison"|"checklist"|"itinerary"|"budget"|"note", '
        '"section_name": string, "title": string, "content_payload": object}\n\n'
        "Payload shapes:\n"
        '- comparison: {"options": [{"name","price","rating","pros":[..],"cons":[..],"is_winner":bool}]} '
        "(2-4 options, exactly one is_winner)\n"
        "- checklist: {\"items\": [{\"text\": string}]} (5-12 concrete actionable items)\n"
        "- itinerary: {\"steps\": [{\"time\":\"09:30\",\"title\",\"location\",\"notes\"}]}\n"
        "- budget: {\"currency\": \"SGD\", \"items\": [{\"name\",\"cost\":number,\"status\":\"Estimated\"}]}\n"
        "- note: {\"markdown\": string} (concise markdown bullets)\n\n"
        f"Board context — title: {board_context.get('title')!r}, category: {board_context.get('category')!r}, "
        f"summary: {board_context.get('summary')!r}, existing sections: {existing}.\n"
        "Rules:\n"
        "1. Content must be specific to the request and board topic — never generic placeholder text.\n"
        "2. Pick section_name that fits the board's existing sections when sensible.\n"
        "3. Prices/costs must be plausible for the locale implied by the board."
    )

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.4)
        from langchain_core.messages import HumanMessage, SystemMessage

        ai_message = await llm.ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=prompt[:1500])]
        )
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = _re.sub(r"^```(?:json)?|```$", "", raw, flags=_re.MULTILINE).strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return None
        parsed = _json.loads(raw[start:end + 1])
        return _validate_generated_block(parsed)
    except Exception as exc:  # noqa: BLE001 - copilot must degrade gracefully
        logger.info("LLM copilot generation failed, using template fallback: %s", exc)
        return None


def _template_block_for_prompt(prompt_text: str) -> Dict[str, Any]:
    """Deterministic offline fallback generator used when the LLM path is unavailable."""
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
                {"id": "ai-c-1", "text": "Essential passports, travel IDs & boarding passes", "checked": False},
                {"id": "ai-c-2", "text": "Power banks, universal adapters & charging cables", "checked": False},
                {"id": "ai-c-3", "text": "Prescription medications & basic first-aid kit", "checked": False},
                {"id": "ai-c-4", "text": "Comfortable walking shoes & weather-appropriate layers", "checked": False},
                {"id": "ai-c-5", "text": "Cash in local currency & backup credit card", "checked": False},
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
            "markdown": f"### ✨ Brainstorming Insights\n\n• **Core Concept**: {prompt_text}\n• **Key Considerations**: Focus on high-impact items first, keep budget in check, and balance flexibility with scheduled reservations.\n• **Next Steps**: Shortlist top options, assign due dates, and verify opening hours."
        }

    return {"block_type": block_type, "title": title, "content_payload": content_payload}


def _is_explicit_research_prompt(prompt: str) -> bool:
    """Detect prompts that should fetch evidence rather than invent a card."""
    lowered = (prompt or "").lower()
    return any(
        phrase in lowered
        for phrase in (
            "research", "look up", "look into", "search for", "find out",
            "check the latest", "what are the best", "where should we",
        )
    )


async def _research_whiteboard_prompt(
    prompt: str,
    board_context: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Run one bounded web search and normalize it into a compact research card."""
    if not settings.tavily_api_key or settings.tavily_api_key.startswith("your_"):
        return None

    from capabilities.general.tools import search_web

    sections = board_context.get("existing_sections") or []
    context = " ".join(
        str(value).strip()
        for value in (
            board_context.get("title"),
            board_context.get("category"),
            board_context.get("summary"),
            ", ".join(str(section) for section in sections[:10]),
        )
        if value
    )
    specific_request = not re.fullmatch(
        r"(?:can you|could you|please)?\s*(?:do|help me with|help me to)?\s*"
        r"(?:some )?research(?: for me| on this| about it)?[?.!]*",
        prompt.strip(),
        flags=re.IGNORECASE,
    )
    if specific_request:
        query = f"{prompt.strip()} {context} current practical recommendations official sites reputable guides"
        topic_title = prompt.strip()[:160]
    else:
        query = (
            f"Current practical recommendations for the planning board '{board_context.get('title')}'. "
            f"Find useful options for its open sections ({', '.join(str(section) for section in sections[:8])}), "
            f"with context {board_context.get('summary') or board_context.get('category')}. "
            "Use current reputable guides and official websites; avoid social-media posts."
        )
        topic_title = f"Ideas for {board_context.get('title') or 'this board'}"
    query = query.strip()[:1200]
    try:
        raw_result = await asyncio.wait_for(
            search_web.ainvoke({"query": query, "include_images": True}),
            timeout=25,
        )
    except Exception as exc:  # noqa: BLE001 - copilot can fall back gracefully
        logger.info("Whiteboard research search failed: %s", exc)
        return None

    raw_text = str(raw_result or "").strip()
    if not raw_text or raw_text.startswith("[search]"):
        return None

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    summary = ""
    sources = []
    images = []
    for line in lines:
        summary_match = re.match(r"^Summary:\s*(.+)$", line, re.IGNORECASE)
        if summary_match:
            summary = summary_match.group(1).strip()[:320]
            continue
        image_match = re.match(r"^Image:\s*(https?://\S+)", line, re.IGNORECASE)
        if image_match:
            images.append(image_match.group(1).rstrip(".,"))
            continue
        source_match = re.match(
            r"^[-*•]\s+(.+?)\s+\((https?://[^)]+)\)\s*:?(.*)$",
            line,
        )
        if source_match:
            url = source_match.group(2).strip()
            try:
                hostname = urlparse(url).hostname or ""
            except ValueError:
                hostname = ""
            sources.append({
                "title": source_match.group(1).strip()[:120],
                "url": url[:400],
                "snippet": source_match.group(3).strip()[:260],
                "hostname": hostname.lower(),
            })

    # Social feeds are often low-context or unstable. Prefer editorial and
    # official sources when Tavily gives us alternatives.
    preferred_sources = [
        source for source in sources
        if not any(host in source["hostname"] for host in ("instagram.com", "facebook.com", "tiktok.com"))
    ]
    if preferred_sources:
        sources = preferred_sources
    for index, source in enumerate(sources):
        if index < len(images):
            source["image_url"] = images[index]
        source.pop("hostname", None)

    if not summary:
        summary = next((line for line in lines if not line.startswith(("-", "*", "•", "Image:"))), "")[:320]
    if not summary and not sources:
        return None

    return {
        "section_name": "🔍 Research",
        "block_type": "note",
        "title": f"Research: {topic_title}".rstrip(" ."),
        "content_payload": {
            "topics": [{
                "query": topic_title,
                "summary": summary,
                "sources": sources[:5],
                "images": images[:5],
            }],
            "markdown": "\n".join([
                f"**{prompt.strip()[:160]}**",
                f"Summary: {summary}" if summary else "",
                *[
                    f"- {source['title']} ({source['url']})"
                    for source in sources[:5]
                ],
            ]),
        },
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

        existing_sections = list(proj.section_order or [])
        if not existing_sections:
            sec_rows = await session.execute(
                select(WhiteboardBlock.section_name)
                .where(WhiteboardBlock.project_id == project_id)
                .distinct()
            )
            existing_sections = [row[0] for row in sec_rows.all()]
        board_context = {
            "title": proj.title,
            "category": proj.category,
            "summary": proj.summary,
            "existing_sections": existing_sections[:15],
        }

    prompt_text = payload.prompt.strip()

    generated = None
    engine = "llm"
    if _is_explicit_research_prompt(prompt_text):
        generated = await _research_whiteboard_prompt(prompt_text, board_context)
        if generated is not None:
            engine = "research"
    if generated is None:
        generated = await _llm_generate_block_json(prompt_text, board_context)
    if generated is None:
        generated = _template_block_for_prompt(prompt_text)
        engine = "template"

    block_type = generated["block_type"]
    title = generated["title"]
    content_payload = generated["content_payload"]
    # Prefer the copilot's own section choice when it picked one
    section_name = (
        (generated.get("section_name") or "").strip()
        or ("🔍 Research" if engine == "research" else "")
        or (payload.section_name or "").strip()
        or "AI Suggestions"
    )

    # Save generated block
    async with async_session_factory() as session:
        now = datetime.utcnow()
        max_pos = (await session.execute(
            select(WhiteboardBlock.position_order)
            .where(WhiteboardBlock.project_id == project_id)
            .order_by(desc(WhiteboardBlock.position_order))
            .limit(1)
        )).scalar()
        block = WhiteboardBlock(
            project_id=project_id,
            section_name=section_name,
            block_type=block_type,
            title=title,
            content_payload=content_payload,
            position_order=(max_pos or 0) + 1,
            created_at=now,
            updated_at=now,
        )
        session.add(block)
        proj = (await session.execute(
            select(WhiteboardProject).where(WhiteboardProject.id == project_id)
        )).scalar_one_or_none()
        if proj:
            order = list(proj.section_order or [])
            if section_name not in order:
                order.append(section_name)
                proj.section_order = order
            proj.updated_at = now
            session.add(proj)
        await session.commit()
        await session.refresh(block)

    return {
        "status": "ok",
        "engine": engine,
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
