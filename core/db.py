import core.models  # noqa: F401 - ensure all SQLModel tables are registered with metadata
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from sqlmodel import SQLModel
from core.config import settings

def get_engine():
    db_url = settings.resolved_database_url
    if db_url.startswith("sqlite"):
        return create_async_engine(
            db_url,
            echo=False,
        )
    else:
        return create_async_engine(
            db_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )

engine = get_engine()
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # Idempotent migration: add whiteboard_seeded column if it doesn't exist yet
        # (needed for existing SQLite and PostgreSQL instances that pre-date this field)
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE userprofile ADD COLUMN whiteboard_seeded BOOLEAN NOT NULL DEFAULT 0")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE userprofile ADD COLUMN IF NOT EXISTS whiteboard_seeded BOOLEAN NOT NULL DEFAULT FALSE")
                )
        except Exception:
            pass  # Column already exists — safe to ignore

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
