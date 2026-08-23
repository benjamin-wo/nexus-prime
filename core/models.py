from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column, JSON

class UserProfile(SQLModel, table=True):
    user_id: int = Field(primary_key=True)  # Telegram User ID
    telegram_chat_id: int = Field(index=True, unique=True)
    current_timezone: str = Field(default="UTC")
    home_currency: str = Field(default="SGD")
    tracked_banks: List[str] = Field(default=[], sa_column=Column(JSON))
    whiteboard_seeded: bool = Field(default=False)  # True after first-time board seeding — prevents re-seed on empty state
    last_whiteboard_id: Optional[int] = Field(default=None)  # Durable pointer to the most recently touched board
    last_email_digest_at: Optional[datetime] = Field(default=None)  # Last daily email-expense digest sent
    created_at: datetime = Field(default_factory=datetime.utcnow)

class UserCredential(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    provider: str = Field(index=True)  # e.g., "gmail"
    encrypted_token_payload: str       # Ciphertext encrypted via Fernet
    updated_at: datetime = Field(default_factory=datetime.utcnow)

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
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DeletedExpenseMessage(SQLModel, table=True):
    """Tombstone table for deleted email/source transactions to prevent poller re-ingestion."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True)
    source_message_id: str = Field(index=True, unique=True)
    deleted_at: datetime = Field(default_factory=datetime.utcnow)

class GroceryItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    name: str
    quantity: str = Field(default="1")
    category: str = Field(default="General")
    is_purchased: bool = Field(default=False)
    added_at: datetime = Field(default_factory=datetime.utcnow)

class ScheduledJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    job_name: str
    cron_expression: str
    instruction_prompt: str
    timezone: str = Field(default="UTC")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = Field(default=None)


class WhiteboardProject(SQLModel, table=True):
    """Living canvas / whiteboard project (trips, events, projects, meal plans, etc.)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    title: str
    emoji_icon: str = Field(default="📋")
    category: str = Field(default="general", index=True)  # trip | event | project | meal | general
    summary: Optional[str] = Field(default=None)
    cover_ready: bool = Field(default=False)  # True once the AI-generated cover art is saved to disk
    section_order: List[str] = Field(default=[], sa_column=Column(JSON))  # explicit section ordering (may include empty sections)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WhiteboardBlock(SQLModel, table=True):
    """Polymorphic interactive card / block inside a whiteboard project."""
    id: Optional[int] = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="whiteboardproject.id", index=True)
    section_name: str = Field(default="General", index=True)  # e.g. "Accommodations", "Itinerary", "Checklist"
    block_type: str = Field(default="note", index=True)  # comparison | checklist | itinerary | budget | note
    title: str
    content_payload: Dict[str, Any] = Field(default={}, sa_column=Column(JSON))
    position_order: int = Field(default=0)
    linked_task_id: Optional[int] = Field(default=None, foreign_key="taskitem.id")
    linked_expense_id: Optional[int] = Field(default=None, foreign_key="expensetransaction.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BusStop(SQLModel, table=True):
    """Cached LTA bus-stop catalog for offline/robust stop-name resolution."""

    code: str = Field(primary_key=True)
    description: str = Field(index=True)
    road_name: str = Field(index=True)
    lat: Optional[float] = None
    lng: Optional[float] = None

class QualityAuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="userprofile.user_id", index=True)
    thread_id: str = Field(index=True)
    faithfulness_score: int = Field(ge=1, le=5)
    routing_efficiency_score: int = Field(ge=1, le=5)
    hallucination_detected: bool = Field(default=False, index=True)
    unnecessary_friction_flag: bool = Field(default=False)
    evidence_explanation: str
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)

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
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationAuditLog(SQLModel, table=True):
    """Periodic LLM-as-a-Judge review of whole conversations (default every 10 messages)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    thread_id: str = Field(index=True)
    user_id: int = Field(index=True)
    message_count: int
    faithfulness_score: int = Field(ge=1, le=5)
    routing_score: int = Field(ge=1, le=5)
    tool_correctness_score: int = Field(ge=1, le=5)
    helpfulness_score: int = Field(ge=1, le=5)
    verdict: str = Field(index=True)  # pass | review | critical
    evidence: str
    judge_model: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ProductionBugLog(SQLModel, table=True):
    """Production bug and audit failure telemetry tracked via Gemini 3.1 Pro and synced to GitHub Issues."""

    id: Optional[int] = Field(default=None, primary_key=True)
    fingerprint: str = Field(index=True)
    title: str = Field(index=True)
    severity: str = Field(default="P2", index=True)  # P0, P1, P2, P3
    subsystem: str = Field(default="general", index=True)
    detection_source: str = Field(default="conversation_audit", index=True)  # conversation_audit | runtime_exception | quality_audit
    user_id: Optional[int] = Field(default=None, index=True)
    thread_id: Optional[str] = Field(default=None, index=True)
    root_cause: Optional[str] = Field(default=None)
    reproduction_context: Optional[str] = Field(default=None)
    suggested_fix: Optional[str] = Field(default=None)
    error_traceback: Optional[str] = Field(default=None)
    github_issue_url: Optional[str] = Field(default=None)
    github_issue_number: Optional[int] = Field(default=None)
    occurrence_count: int = Field(default=1)
    status: str = Field(default="open", index=True)  # open | resolved
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
