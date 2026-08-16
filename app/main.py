import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
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
    - Gracefully shutdown scheduler on exit
    """
    await setup_checkpointer()
    await init_db()
    await start_scheduler()
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

# Mount showcase web application
showcase_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "showcase")
if os.path.exists(showcase_dir):
    app.mount("/showcase", StaticFiles(directory=showcase_dir, html=True), name="showcase")
    app.mount("/", StaticFiles(directory=showcase_dir, html=True), name="static_root")


