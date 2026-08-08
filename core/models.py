from datetime import datetime
from typing import List, Optional
from sqlmodel import SQLModel, Field, Column, JSON

class UserProfile(SQLModel, table=True):
    user_id: int = Field(primary_key=True)  # Telegram User ID
    telegram_chat_id: int = Field(index=True, unique=True)
    current_timezone: str = Field(default="UTC")
    home_currency: str = Field(default="SGD")
    tracked_banks: List[str] = Field(default=[], sa_column=Column(JSON))
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
    is_verified: bool = Field(default=True)

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
    intent_type: str = Field(index=True)  # "unsupported_transaction" or "informational_fallback"
    missing_capability_tags: str = Field(index=True)  # Comma-separated tags e.g. "calendar,smart_home"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationAuditLog(SQLModel, table=True):
    """Periodic LLM-as-a-Judge review of whole conversations (default every 5 messages)."""

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
