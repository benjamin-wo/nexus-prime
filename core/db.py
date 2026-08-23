import core.models  # noqa: F401 - ensure all SQLModel tables are registered with metadata
import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlmodel import SQLModel
from core.config import settings

logger = logging.getLogger(__name__)

def _is_duplicate_column_error(exc: Exception) -> bool:
    """Return True only for 'column already exists' style errors so we don't
    silently swallow real migration failures (connection errors, missing tables...)."""
    message = str(exc).lower()
    markers = ("duplicate column", "already exists", "duplicate column name", "column already exists")
    return any(m in message for m in markers)

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
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for whiteboard_seeded skipped: %s", exc)

        # Idempotent migration: add cover_ready column if it doesn't exist yet
        # (needed for existing SQLite and PostgreSQL instances that pre-date this field)
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE whiteboardproject ADD COLUMN cover_ready BOOLEAN NOT NULL DEFAULT 0")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE whiteboardproject ADD COLUMN IF NOT EXISTS cover_ready BOOLEAN NOT NULL DEFAULT FALSE")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for cover_ready skipped: %s", exc)

        # Idempotent migration: add section_order column if it doesn't exist yet
        # (explicit whiteboard section ordering; may include empty sections)
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE whiteboardproject ADD COLUMN section_order JSON DEFAULT '[]'")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE whiteboardproject ADD COLUMN IF NOT EXISTS section_order JSON DEFAULT '[]'::json")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for section_order skipped: %s", exc)

        # Idempotent migration: durable pointer to the user's most recent board
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE userprofile ADD COLUMN last_whiteboard_id INTEGER")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE userprofile ADD COLUMN IF NOT EXISTS last_whiteboard_id INTEGER")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for last_whiteboard_id skipped: %s", exc)

        # Idempotent migration: last daily email-expense digest marker
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE userprofile ADD COLUMN last_email_digest_at TIMESTAMP")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE userprofile ADD COLUMN IF NOT EXISTS last_email_digest_at TIMESTAMP")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for last_email_digest_at skipped: %s", exc)

        # Idempotent migration: add receipt_items and split_data columns to expensetransaction
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN receipt_items JSON DEFAULT '[]'")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN IF NOT EXISTS receipt_items JSON DEFAULT '[]'::json")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for receipt_items skipped: %s", exc)

        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN split_data JSON DEFAULT '{}'")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN IF NOT EXISTS split_data JSON DEFAULT '{}'::json")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for split_data skipped: %s", exc)

        # Idempotent migration: source sender domain for receipt-vs-bank-alert dedup
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN source_sender_domain VARCHAR")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN IF NOT EXISTS source_sender_domain VARCHAR")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for source_sender_domain skipped: %s", exc)

        # Idempotent migration: UTC ingestion time used by the daily email digest
        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN logged_at TIMESTAMP")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN IF NOT EXISTS logged_at TIMESTAMP")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for logged_at skipped: %s", exc)

        try:
            db_url = settings.resolved_database_url
            if db_url.startswith("sqlite"):
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN notes VARCHAR")
                )
            else:
                await conn.execute(
                    text("ALTER TABLE expensetransaction ADD COLUMN IF NOT EXISTS notes VARCHAR")
                )
        except (OperationalError, ProgrammingError) as exc:
            if not _is_duplicate_column_error(exc):
                logger.warning("Migration for expense notes skipped: %s", exc)

        # Idempotent linkage fields keep repayments and IOU tasks synchronized
        # with the parent expense while preserving existing records.
        db_url = settings.resolved_database_url
        for table_name, column_name, index_name in (
            ("incometransaction", "linked_expense_id", "ix_incometransaction_linked_expense_id"),
            ("taskitem", "linked_expense_id", "ix_taskitem_linked_expense_id"),
            ("taskitem", "iou_friend", "ix_taskitem_iou_friend"),
            ("taskitem", "iou_amount", "ix_taskitem_iou_amount"),
        ):
            column_type = (
                "FLOAT"
                if column_name == "iou_amount"
                else "INTEGER"
                if column_name == "linked_expense_id"
                else "VARCHAR"
            )
            try:
                column_sql = (
                    f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
                    if not db_url.startswith("sqlite")
                    else f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )
                await conn.execute(
                    text(column_sql)
                )
            except (OperationalError, ProgrammingError) as exc:
                if not _is_duplicate_column_error(exc):
                    logger.warning(
                        "Migration for %s.%s skipped: %s",
                        table_name,
                        column_name,
                        exc,
                    )
            try:
                await conn.execute(
                    text(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON {table_name} ({column_name})"
                    )
                )
            except (OperationalError, ProgrammingError) as exc:
                if not _is_duplicate_column_error(exc):
                    logger.warning(
                        "Index migration for %s.%s skipped: %s",
                        table_name,
                        column_name,
                        exc,
                    )

        # Idempotent migration: richer capability-gap telemetry columns
        for col, default in (
            ("expectation", "NULL"),
            ("block_reason", "NULL"),
            ("agent_reply", "NULL"),
            ("channel", "NULL"),
        ):
            try:
                db_url = settings.resolved_database_url
                if db_url.startswith("sqlite"):
                    await conn.execute(
                        text(f"ALTER TABLE capabilityrequestlog ADD COLUMN {col} TEXT DEFAULT {default}")
                    )
                else:
                    await conn.execute(
                        text(f"ALTER TABLE capabilityrequestlog ADD COLUMN IF NOT EXISTS {col} TEXT DEFAULT {default}")
                    )
            except (OperationalError, ProgrammingError) as exc:
                if not _is_duplicate_column_error(exc):
                    logger.warning("Migration for capabilityrequestlog.%s skipped: %s", col, exc)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
