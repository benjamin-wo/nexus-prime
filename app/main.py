import os
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from core.db import init_db
from core.scheduler import start_scheduler, shutdown_scheduler
from orchestrator.checkpointer import setup_checkpointer, close_checkpointer
from app.webhook import router as webhook_router
from app.auth import router as auth_router
from app.chat_api import router as chat_router
from app.dashboard_api import router as dashboard_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Uvicorn lifespan manager for Railway deployment:
    - Initialize database tables
    - Start APScheduler engine & watchdog
    - Register Telegram bot commands and menu button
    - Gracefully shutdown scheduler on exit
    """
    await setup_checkpointer()
    await init_db()
    try:
        from core.db import async_session_factory
        from core.models import ExpenseTransaction
        from sqlmodel import or_, select
        async with async_session_factory() as session:
            bogus_res = await session.execute(
                select(ExpenseTransaction).where(
                    or_(
                        ExpenseTransaction.amount >= 100000.0,
                        (ExpenseTransaction.amount.in_([2024.0, 2025.0, 2026.0, 2027.0]) & ExpenseTransaction.merchant.in_(["Apple", "PayLah! Alerts", "Email Receipt", "Unknown"])),
                        (ExpenseTransaction.merchant == "PayLah! Alerts") & (ExpenseTransaction.amount == 21.0),
                    )
                )
            )
            for bad_tx in bogus_res.scalars().all():
                await session.delete(bad_tx)
            await session.commit()
    except Exception as clean_err:
        print(f"[STARTUP] legacy cleanup error: {clean_err}")
    await start_scheduler()
    try:
        from app.ingress import setup_telegram_bot_commands
        await setup_telegram_bot_commands()
    except Exception as exc:
        print(f"[TELEGRAM] Failed to setup bot commands on startup: {exc}")
    yield
    await shutdown_scheduler()
    await close_checkpointer()

app = FastAPI(
    title="Telegram Personal Assistant Bot",
    description="High-performance Telegram bot with 3-Layer Plugin Architecture and LangGraph Multi-Agent Orchestration",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router, prefix="/api", tags=["Webhook"])
app.include_router(chat_router, prefix="/api", tags=["Web Chat"])
app.include_router(dashboard_router, prefix="/api", tags=["Dashboard"])
app.include_router(auth_router)

@app.get("/health")
async def health_check():
    """Health check endpoint for Railway deployment monitoring."""
    return {"status": "ok", "service": "Telegram Personal Assistant Bot"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Capture unhandled route errors into the production-bug pipeline (DB + GitHub Issues).

    Keeps a 500 to the caller while recording a service-side issue for agent review.
    Re-raised HTTPExceptions keep their original status/detail intact.
    """
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    try:
        from core.audit import record_operation_event

        await record_operation_event(
            subsystem=(request.url.path or "ingress").strip("/").split("/")[0] or "ingress",
            error_context=f"Unhandled {type(exc).__name__} on {request.method} {request.url.path}",
            error_traceback="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )[:3000],
            detection_source="runtime_exception",
        )
    except Exception as audit_err:  # noqa: BLE001 - the audit funnel must never hide the original fault
        print(f"[OPS AUDIT] failed to record unhandled exception: {audit_err}")
    return JSONResponse(
        status_code=500,
        content={"detail": "internal_error"},
    )

# Mount showcase web application
showcase_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "showcase")
if os.path.exists(showcase_dir):
    app.mount("/showcase", StaticFiles(directory=showcase_dir, html=True), name="showcase")
    app.mount("/", StaticFiles(directory=showcase_dir, html=True), name="static_root")


