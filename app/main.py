from contextlib import asynccontextmanager
from fastapi import FastAPI
from core.db import init_db
from core.scheduler import start_scheduler, shutdown_scheduler
from app.webhook import router as webhook_router
from app.auth import router as auth_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Uvicorn lifespan manager for Railway deployment:
    - Initialize database tables
    - Start APScheduler engine & watchdog
    - Gracefully shutdown scheduler on exit
    """
    await init_db()
    await start_scheduler()
    yield
    await shutdown_scheduler()

app = FastAPI(
    title="Telegram Personal Assistant Bot",
    description="High-performance Telegram bot with 3-Layer Plugin Architecture and LangGraph Multi-Agent Orchestration",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router, prefix="/api", tags=["Webhook"])
app.include_router(auth_router)

@app.get("/")
@app.get("/health")
async def health_check():
    """Health check endpoint for Railway deployment monitoring."""
    return {"status": "ok", "service": "Telegram Personal Assistant Bot"}
