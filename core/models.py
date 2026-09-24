from datetime import datetime, timezone as dt_timezone
from typing import List, Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint


def _utcnow() -> datetime:
    return datetime.now(dt_timezone.utc)

class UserProfile(SQLModel, table=True):
    user_id: int = Field(primary_key=True)  # Telegram User ID
    telegram_chat_id: int = Field(index=True, unique=True)
    current_timezone: str = Field(default="UTC")
    home_currency: str = Field(default="SGD")
    tracked_banks: List[str] = Field(default=[], sa_column=Column(JSON))
    email_exclude_domains: List[str] = Field(default=[], sa_column=Column(JSON))
    email_content_type_presets: List[str] = Field(default=[], sa_column=Column(JSON))
    whiteboard_seeded: bool = Field(default=False)  # True after first-time board seeding — prevents re-seed on empty state
    last_whiteboard_id: Optional[int] = Field(default=None)  # Durable pointer to the most recently touched board
    last_email_digest_at: Optional[datetime] = Field(default=None)  # Last daily email-expense digest sent
    created_at: datetime = Field(default_factory=_utcnow)

class UserCredential(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    provider: str = Field(index=True)  # e.g., "gmail"
    encrypted_token_payload: str       # Ciphertext encrypted via Fernet
    updated_at: datetime = Field(default_factory=_utcnow)

class ExpenseTransaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    amount: float
    currency: str
    merchant: str
    category: str
    date: datetime
    source_message_id: Optional[str] = Field(default=None, unique=True, index=True)
    source_sender_domain: Optional[str] = Field(default=None, index=True)  # e.g. "starbucks.com" — enables receipt-vs-bank-alert dedup
    logged_at: Optional[datetime] = Field(default=None, index=True)  # UTC ingestion time for daily digest selection
    is_verified: bool = Field(default=True)
    notes: Optional[str] = Field(default=None)
    receipt_items: List[Dict[str, Any]] = Field(default=[], sa_column=Column(JSON))
    split_data: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))


class IncomeTransaction(SQLModel, table=True):
    """Money received by the user, kept separate from spending transactions."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    amount: float
    currency: str = Field(default="SGD")
    source: str = Field(index=True)  # employer | friend | insurer | other
    category: str = Field(default="Other", index=True)  # salary | repayment | reimbursement | claim | other
    date: datetime
    notes: Optional[str] = Field(default=None)
    source_message_id: Optional[str] = Field(default=None, unique=True, index=True)
    linked_expense_id: Optional[int] = Field(default=None, foreign_key="expensetransaction.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class DeletedExpenseMessage(SQLModel, table=True):
    """Tombstone table for deleted email/source transactions to prevent poller re-ingestion."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    source_message_id: str = Field(index=True, unique=True)
    deleted_at: datetime = Field(default_factory=_utcnow)


class ExpenseUndoEntry(SQLModel, table=True):
    """Undo snapshot for expense writes (create/edit/delete).

    Every mutating expense tool records a snapshot here BEFORE applying its
    change, so undo_last_write / restore_expense can revert it. kind:
    "delete" (snapshot = the row before deletion), "edit" (snapshot = the row
    before the edit), "create" (snapshot = None, undo deletes the row).
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    expense_id: int = Field(index=True)
    kind: str = Field(index=True)
    snapshot: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)

class ScheduledJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    job_name: str
    cron_expression: str
    instruction_prompt: str
    timezone: str = Field(default="UTC")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=_utcnow)

class TaskItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    title: str
    description: Optional[str] = Field(default=None)
    status: str = Field(default="todo", index=True)  # "todo" | "done"
    priority: str = Field(default="medium", index=True)  # "low" | "medium" | "high"
    due_at: Optional[datetime] = Field(default=None)
    reminder_type: str = Field(default="none")  # "none" | "once" | "recurring"
    reminder_time: Optional[datetime] = Field(default=None)
    cron_expression: Optional[str] = Field(default=None)
    timezone: str = Field(default="Asia/Singapore")
    is_reminder_active: bool = Field(default=True)
    linked_expense_id: Optional[int] = Field(default=None, foreign_key="expensetransaction.id", index=True)
    iou_friend: Optional[str] = Field(default=None, index=True)
    iou_amount: Optional[float] = Field(default=None)
    created_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = Field(default=None)

class CapabilityRequestLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    requested_task: str
    intent_type: str = Field(index=True)  # "unsupported_transaction" | "insufficient_capability" | ...
    missing_capability_tags: str = Field(index=True)  # Comma-separated tags e.g. "calendar,smart_home"
    expectation: Optional[str] = Field(default=None)  # What the user wanted to accomplish
    block_reason: Optional[str] = Field(default=None)  # Why the request could not be fulfilled
    agent_reply: Optional[str] = Field(default=None)  # What the assistant told the user
    channel: Optional[str] = Field(default=None)  # "telegram" | "web" | "api" | "unknown"
    created_at: datetime = Field(default_factory=_utcnow)
