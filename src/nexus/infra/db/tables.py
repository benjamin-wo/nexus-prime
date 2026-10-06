"""Schema, as SQLAlchemy Core tables. Alembic migrations must match this.

Child tables carry ``user_id`` and reference their parent by
``(id, user_id)``, so the database itself refuses cross-tenant links.
"""

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Table,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

MONEY = Numeric(19, 4, asdecimal=True)
CURRENCY = String(3)
TZ = DateTime(timezone=True)


def _uuid_pk() -> Column[uuid.UUID]:
    return Column("id", UUID(as_uuid=True), primary_key=True)


def _user_fk() -> Column[uuid.UUID]:
    return Column("user_id", UUID(as_uuid=True), nullable=False)


users = Table(
    "users",
    metadata,
    _uuid_pk(),
    Column("telegram_user_id", BigInteger, nullable=False, unique=True),
    Column("telegram_chat_id", BigInteger),
    Column("timezone", Text, nullable=False),
    Column("home_currency", CURRENCY, nullable=False),
    Column("role", Text, nullable=False),
    Column("created_at", TZ, nullable=False, server_default=func.now()),
    # Set when a member redeems an invite; owners always have web access.
    Column("web_access_granted_at", TZ),
    CheckConstraint("role IN ('owner', 'member')", name="role"),
    CheckConstraint("home_currency ~ '^[A-Z]{3}$'", name="home_currency"),
)

categories = Table(
    "categories",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("name", Text, nullable=False),
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", TZ, nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("id", "user_id"),
    Index("uq_categories_user_id_lower_name", "user_id", func.lower(text("name")), unique=True),
)

# A word or phrase that files new expenses under a category. Archived, never
# deleted, so transactions it filed can still explain themselves.
category_rules = Table(
    "category_rules",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("pattern", Text, nullable=False),
    Column("category_id", UUID(as_uuid=True), nullable=False),
    Column("explanation", Text, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    Column("archived_at", TZ),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(["category_id", "user_id"], ["categories.id", "categories.user_id"]),
    UniqueConstraint("id", "user_id"),
    CheckConstraint("char_length(pattern) BETWEEN 2 AND 60", name="pattern_length"),
    Index(
        "uq_category_rules_user_id_pattern",
        "user_id",
        "pattern",
        unique=True,
        postgresql_where=text("archived_at IS NULL"),
    ),
)

transactions = Table(
    "transactions",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("direction", Text, nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("currency", CURRENCY, nullable=False),
    Column("occurred_at", TZ, nullable=False),
    Column("counterparty", Text),
    Column("category_id", UUID(as_uuid=True)),
    Column("notes", Text),
    Column("status", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    Column("deleted_at", TZ),
    Column("category_rule_id", UUID(as_uuid=True)),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(["category_id", "user_id"], ["categories.id", "categories.user_id"]),
    ForeignKeyConstraint(
        ["category_rule_id", "user_id"], ["category_rules.id", "category_rules.user_id"]
    ),
    UniqueConstraint("id", "user_id"),
    CheckConstraint(
        "category_rule_id IS NULL OR category_id IS NOT NULL", name="rule_needs_category"
    ),
    CheckConstraint("direction IN ('in', 'out')", name="direction"),
    CheckConstraint("amount > 0", name="amount_positive"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    CheckConstraint("status IN ('confirmed', 'pending')", name="status"),
    CheckConstraint("source IN ('text', 'photo', 'email', 'import', 'manual')", name="source"),
    Index("ix_transactions_user_id_occurred_at", "user_id", "occurred_at"),
)

# A receipt file in the private bucket. Its visibility and purge follow its
# transaction (see nexus.domain.receipts); an unclaimed one is a declined photo.
receipts = Table(
    "receipts",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("transaction_id", UUID(as_uuid=True)),
    Column("object_key", Text, nullable=False),
    Column("content_type", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(
        ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    UniqueConstraint("object_key"),
    CheckConstraint("size_bytes > 0", name="size_positive"),
    CheckConstraint("object_key LIKE 'receipts/' || user_id || '/%'", name="key_owner"),
    Index(
        "uq_receipts_transaction_id",
        "transaction_id",
        unique=True,
        postgresql_where=text("transaction_id IS NOT NULL"),
    ),
    Index("ix_receipts_created_at", "created_at"),
)

transaction_sources = Table(
    "transaction_sources",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _user_fk(),
    Column("source", Text, nullable=False),
    Column("external_id", Text, nullable=False),
    Column("transaction_id", UUID(as_uuid=True)),
    Column("created_at", TZ, nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(
        ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    UniqueConstraint("user_id", "source", "external_id"),
)

transaction_revisions = Table(
    "transaction_revisions",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _user_fk(),
    Column("transaction_id", UUID(as_uuid=True), nullable=False),
    Column("kind", Text, nullable=False),
    Column("before", JSONB),
    Column("created_at", TZ, nullable=False),
    Column("undone_at", TZ),
    ForeignKeyConstraint(
        ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    CheckConstraint("kind IN ('create', 'edit', 'delete', 'restore', 'split')", name="kind"),
    Index("ix_transaction_revisions_user_id_id", "user_id", "id"),
)

splits = Table(
    "splits",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("transaction_id", UUID(as_uuid=True), nullable=False),
    Column("participant_name", Text, nullable=False),
    Column("share_amount", MONEY, nullable=False),
    Column("created_at", TZ, nullable=False, server_default=func.now()),
    ForeignKeyConstraint(
        ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    UniqueConstraint("id", "user_id"),
    CheckConstraint("share_amount > 0", name="share_positive"),
    Index("ix_splits_user_id_transaction_id", "user_id", "transaction_id"),
)

settlements = Table(
    "settlements",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("split_id", UUID(as_uuid=True), nullable=False),
    Column("income_transaction_id", UUID(as_uuid=True), nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("created_at", TZ, nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["split_id", "user_id"], ["splits.id", "splits.user_id"]),
    ForeignKeyConstraint(
        ["income_transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    CheckConstraint("amount > 0", name="amount_positive"),
    Index("ix_settlements_split_id", "split_id"),
)

capability_gaps = Table(
    "capability_gaps",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    _user_fk(),
    Column("request", Text, nullable=False),
    Column("intent", Text, nullable=False),
    Column("channel", Text, nullable=False),
    Column("created_at", TZ, nullable=False, server_default=func.now()),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
)

# Inbound events already accepted, so a redelivered one is ignored.
inbound_events = Table(
    "inbound_events",
    metadata,
    Column("channel", Text, primary_key=True),
    Column("event_id", Text, primary_key=True),
    Column("received_at", TZ, nullable=False, server_default=func.now()),
)

invites = Table(
    "invites",
    metadata,
    _uuid_pk(),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("created_by", UUID(as_uuid=True), nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("expires_at", TZ, nullable=False),
    Column("redeemed_at", TZ),
    Column("redeemed_by", UUID(as_uuid=True)),
    ForeignKeyConstraint(["created_by"], ["users.id"]),
    ForeignKeyConstraint(["redeemed_by"], ["users.id"]),
)

web_sessions = Table(
    "web_sessions",
    metadata,
    Column("token_hash", Text, primary_key=True),
    _user_fk(),
    Column("csrf_token", Text, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("expires_at", TZ, nullable=False),
    Column("revoked_at", TZ),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    Index("ix_web_sessions_user_id", "user_id"),
)

# Monthly spending limits in the user's home currency: at most one overall
# budget and one per category.
budgets = Table(
    "budgets",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("category_id", UUID(as_uuid=True)),
    Column("amount", MONEY, nullable=False),
    Column("currency", CURRENCY, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(["category_id", "user_id"], ["categories.id", "categories.user_id"]),
    UniqueConstraint("id", "user_id"),
    CheckConstraint("amount > 0", name="amount_positive"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    Index(
        "uq_budgets_user_id_overall",
        "user_id",
        unique=True,
        postgresql_where=text("category_id IS NULL"),
    ),
    Index(
        "uq_budgets_user_id_category_id",
        "user_id",
        "category_id",
        unique=True,
        postgresql_where=text("category_id IS NOT NULL"),
    ),
)

# One row per (budget, month, threshold) reached: the row is the alert's
# idempotency key, so an alert is sent at most once.
budget_alerts = Table(
    "budget_alerts",
    metadata,
    Column("budget_id", UUID(as_uuid=True), primary_key=True),
    Column("period", Date, primary_key=True),
    Column("threshold", SmallInteger, primary_key=True),
    _user_fk(),
    Column("reached_at", TZ, nullable=False),
    ForeignKeyConstraint(
        ["budget_id", "user_id"], ["budgets.id", "budgets.user_id"], ondelete="CASCADE"
    ),
    CheckConstraint("threshold IN (50, 80, 100)", name="threshold"),
)

# Bills to remember (never paid by the app). Amount and currency are both set or
# both empty.
bills = Table(
    "bills",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("name", Text, nullable=False),
    Column("amount", MONEY),
    Column("currency", CURRENCY),
    Column("cadence", Text, nullable=False),
    Column("anchor", Date, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("archived_at", TZ),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("id", "user_id"),
    CheckConstraint("cadence IN ('once', 'weekly', 'monthly', 'yearly')", name="cadence"),
    CheckConstraint("(amount IS NULL) = (currency IS NULL)", name="amount_with_currency"),
    CheckConstraint("amount IS NULL OR amount > 0", name="amount_positive"),
    Index("ix_bills_user_id", "user_id"),
)

# A due date of a bill, stored once it's reminded, snoozed or paid.
bill_occurrences = Table(
    "bill_occurrences",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("bill_id", UUID(as_uuid=True), nullable=False),
    Column("due", Date, nullable=False),
    Column("paid_at", TZ),
    Column("snoozed_until", TZ),
    Column("reminded_offset", SmallInteger),
    ForeignKeyConstraint(["bill_id", "user_id"], ["bills.id", "bills.user_id"], ondelete="CASCADE"),
    UniqueConstraint("bill_id", "due"),
    CheckConstraint("reminded_offset IN (7, 3, 1)", name="reminded_offset"),
)

# When the user is paid, and their usual (confirmed) salary. One per user.
salary_schedules = Table(
    "salary_schedules",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("rule", Text, nullable=False),
    Column("day", SmallInteger),
    Column("anchor", Date),
    Column("amount", MONEY),
    Column("currency", CURRENCY),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    CheckConstraint("rule IN ('monthly_day', 'last_weekday', 'biweekly')", name="rule"),
    CheckConstraint("(rule = 'monthly_day') = (day IS NOT NULL)", name="day_for_monthly"),
    CheckConstraint("day IS NULL OR day BETWEEN 1 AND 31", name="day_range"),
    CheckConstraint("(rule = 'biweekly') = (anchor IS NOT NULL)", name="anchor_for_biweekly"),
    CheckConstraint("(amount IS NULL) = (currency IS NULL)", name="amount_with_currency"),
    CheckConstraint("amount IS NULL OR amount > 0", name="amount_positive"),
)

# Recurring payments: proposed from the ledger, tracked once the user agrees.
# One row per merchant and currency, whatever its status, so a proposal the user
# turned down isn't made again.
subscriptions = Table(
    "subscriptions",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("key", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("cadence", Text, nullable=False),
    Column("amount", MONEY, nullable=False),
    Column("currency", CURRENCY, nullable=False),
    Column("last_charged_on", Date, nullable=False),
    Column("status", Text, nullable=False),
    Column("previous_amount", MONEY),
    Column("price_changed_on", Date),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("user_id", "key", "currency"),
    CheckConstraint("cadence IN ('weekly', 'monthly', 'yearly')", name="cadence"),
    CheckConstraint("status IN ('proposed', 'active', 'dismissed')", name="status"),
    CheckConstraint("amount > 0", name="amount_positive"),
)

# How often each user hears about their transactions. No row means the default
# (an end-of-day summary), not yet started.
notification_settings = Table(
    "notification_settings",
    metadata,
    Column("user_id", UUID(as_uuid=True), primary_key=True),
    Column("frequency", Text, nullable=False),
    Column("notified_until", TZ),
    Column("daily_at", Time),  # when the daily summary goes, local time; NULL is 21:00
    Column("updated_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    CheckConstraint(
        "frequency IN ('instant', 'hourly', 'thrice_daily', 'daily', 'off')", name="frequency"
    ),
)

# What Nexus remembers about a user, from their own words (see nexus.domain.memory).
memories = Table(
    "memories",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("kind", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("happened_on", Date),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    CheckConstraint("kind IN ('fact', 'preference', 'episode')", name="kind"),
    CheckConstraint("length(text) BETWEEN 1 AND 300", name="text_length"),
    Index("ix_memories_user_id_updated_at", "user_id", "updated_at"),
)

# The chat as the user saw it, on the web or Telegram: their messages and Nexus's
# replies, so the web chat can show the conversation again. Notifications aren't
# kept here. The newest CHAT_KEEP per user are kept.
chat_log = Table(
    "chat_log",
    metadata,
    # In the order said: two lines can share a timestamp.
    Column("id", BigInteger, Identity(always=True), primary_key=True),
    _user_fk(),
    Column("role", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("channel", Text),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    CheckConstraint("role IN ('user', 'nexus')", name="role"),
    CheckConstraint("length(text) BETWEEN 1 AND 4000", name="text_length"),
    Index("ix_chat_log_user_id_id", "user_id", "id"),
)

# What a user holds: one row per stock, with the quantity and average cost per share.
holdings = Table(
    "holdings",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("symbol", Text, nullable=False),
    Column("quantity", Numeric(24, 8), nullable=False),
    Column("average_cost", MONEY, nullable=False),
    Column("currency", CURRENCY, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("user_id", "symbol"),
    CheckConstraint("quantity > 0", name="quantity_positive"),
    CheckConstraint("average_cost >= 0", name="cost_not_negative"),
)

# Positions read from a broker screenshot, waiting for the user to save or drop them.
holding_drafts = Table(
    "holding_drafts",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("positions", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    CheckConstraint("status IN ('waiting', 'saved', 'discarded')", name="status"),
    Index("ix_holding_drafts_user_id_created_at", "user_id", "created_at"),
)

# Daily prices, shared by every user: market data, not anyone's own. A stock is
# fetched while someone holds it.
market_bars = Table(
    "market_bars",
    metadata,
    Column("symbol", Text, nullable=False),
    Column("day", Date, nullable=False),
    Column("open", Numeric(19, 6), nullable=False),
    Column("high", Numeric(19, 6), nullable=False),
    Column("low", Numeric(19, 6), nullable=False),
    Column("close", Numeric(19, 6), nullable=False),
    Column("adj_close", Numeric(19, 6), nullable=False),
    Column("volume", BigInteger, nullable=False),
    # The dividend per share going ex that day (migration 0031).
    Column("div_cash", Numeric(19, 6), nullable=False, server_default=text("0")),
    PrimaryKeyConstraint("symbol", "day"),
)

# Trades the user told Nexus about, buy or sell (migration 0031).
trades = Table(
    "trades",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("symbol", Text, nullable=False),
    Column("side", Text, nullable=False),
    Column("quantity", Numeric(24, 8), nullable=False),
    Column("price", MONEY),
    Column("currency", CURRENCY, nullable=False),
    Column("traded_on", Date, nullable=False),
    Column("realised", Numeric(19, 4)),  # a sale's gain or loss, in ``currency``
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    CheckConstraint("side IN ('buy', 'sell')", name="side"),
    CheckConstraint("quantity > 0", name="quantity_positive"),
    Index("ix_trades_user_id_traded_on", "user_id", "traded_on"),
)

# Dividends on shares the user held when they went ex (0031).
dividends = Table(
    "dividends",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("symbol", Text, nullable=False),
    Column("ex_date", Date, nullable=False),
    Column("per_share", Numeric(19, 6), nullable=False),
    Column("currency", CURRENCY, nullable=False),
    Column("shares", Numeric(24, 8), nullable=False),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("user_id", "symbol", "ex_date"),
    CheckConstraint("per_share > 0", name="per_share_positive"),
    CheckConstraint("shares > 0", name="shares_positive"),
)

# When each stock's prices were last fetched, and whether the provider knows it.
market_symbols = Table(
    "market_symbols",
    metadata,
    Column("symbol", Text, primary_key=True),
    Column("fetched_at", TZ, nullable=False),
    Column("known", Boolean, nullable=False),
    # Its full history was fetched with dividends (0031); until then the next
    # refresh fetches all of it again, once.
    Column("dividends", Boolean, nullable=False, server_default=text("false")),
)

# Stocks a user follows without holding them.
watchlist = Table(
    "watchlist",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("symbol", Text, nullable=False),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("user_id", "symbol"),
)

# News per stock, shared by every user, kept for a month. Someone else's text.
market_news = Table(
    "market_news",
    metadata,
    Column("symbol", Text, nullable=False),
    Column("external_id", Text, nullable=False),
    Column("headline", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("url", Text, nullable=False),
    Column("summary", Text, nullable=False),
    Column("published_at", TZ, nullable=False),
    PrimaryKeyConstraint("symbol", "external_id"),
    Index("ix_market_news_symbol_published_at", "symbol", "published_at"),
)

# Upcoming earnings dates per stock, shared by every user.
market_earnings = Table(
    "market_earnings",
    metadata,
    Column("symbol", Text, nullable=False),
    Column("day", Date, nullable=False),
    Column("timing", Text),
    PrimaryKeyConstraint("symbol", "day"),
)

# When each stock's news and earnings dates were last fetched.
news_fetches = Table(
    "news_fetches",
    metadata,
    Column("symbol", Text, primary_key=True),
    Column("fetched_at", TZ, nullable=False),
)

# A research plan for one stock: its numbers (worked out in code) and the
# analysts' write-up, kept so it can be scored when it ends (M13d).
plans = Table(
    "plans",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("run_id", UUID(as_uuid=True)),
    Column("symbol", Text, nullable=False),
    Column("verdict", Text, nullable=False),
    Column("as_of", Date, nullable=False),
    Column("valid_until", Date, nullable=False),
    Column("close", Numeric(19, 4), nullable=False),
    Column("entry_low", Numeric(19, 4)),
    Column("entry_high", Numeric(19, 4)),
    Column("stop", Numeric(19, 4)),
    Column("body", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("closed_at", TZ),
    # Following it after each close (M13d).
    Column("entered_on", Date),
    Column("checked_through", Date),
    Column("outcome_price", Numeric(19, 4)),
    Column("outcome_day", Date),
    Column("result_percent", Numeric(9, 1)),
    Column("alerts", Boolean, nullable=False, server_default=text("true")),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    CheckConstraint("status IN ('open', 'target', 'stopped', 'expired')", name="status"),
    Index("ix_plans_user_id_created_at", "user_id", "created_at"),
    Index("ix_plans_status", "status"),
)

# A department's long piece of work (a research plan, a trip), saved step by step.
department_runs = Table(
    "department_runs",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("department", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("task", JSONB, nullable=False),
    Column("outputs", JSONB, nullable=False),
    Column("steps_done", Integer, nullable=False),
    Column("steps_total", Integer, nullable=False),
    Column("progress", Text, nullable=False),
    Column("spent", MONEY, nullable=False),
    Column("result", JSONB),
    Column("error", Text),
    Column("chat_id", BigInteger),
    Column("message_id", BigInteger),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    Column("finished_at", TZ),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    CheckConstraint(
        "status IN ('queued', 'running', 'done', 'failed', 'cancelled')", name="status"
    ),
    Index("ix_department_runs_user_id_created_at", "user_id", "created_at"),
)

# Two transactions the user said aren't the same payment, so they're never flagged
# as a possible duplicate again. The pair is stored in a fixed order.
duplicate_dismissals = Table(
    "duplicate_dismissals",
    metadata,
    _user_fk(),
    Column("first_id", UUID(as_uuid=True), nullable=False),
    Column("second_id", UUID(as_uuid=True), nullable=False),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    PrimaryKeyConstraint("user_id", "first_id", "second_id"),
    CheckConstraint("first_id < second_id", name="ordered"),
)

# A bank's CSV layout the user saved, found again by its header row.
statement_mappings = Table(
    "statement_mappings",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("name", Text, nullable=False),
    Column("header_key", Text, nullable=False),
    Column("mapping", JSONB, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("user_id", "header_key"),
    CheckConstraint("length(name) BETWEEN 1 AND 60", name="name_length"),
)

# One confirmed statement import, so it can be listed and undone as a whole.
statement_imports = Table(
    "statement_imports",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("file_name", Text, nullable=False),
    Column("transaction_ids", JSONB, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("undone_at", TZ),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    Index("ix_statement_imports_user_id_created_at", "user_id", "created_at"),
)

# Background work. A job is claimed atomically (FOR UPDATE SKIP LOCKED) and
# every job has a unique dedupe key, so none runs twice.
jobs = Table(
    "jobs",
    metadata,
    Column("id", BigInteger, Identity(), primary_key=True),
    Column("kind", Text, nullable=False),
    Column("dedupe_key", Text, nullable=False, unique=True),
    Column("payload", JSONB, nullable=False),
    Column("run_at", TZ, nullable=False),
    Column("status", Text, nullable=False),
    Column("attempts", Integer, nullable=False, server_default=text("0")),
    Column("locked_until", TZ),
    Column("last_error", Text),
    Column("created_at", TZ, nullable=False, server_default=func.now()),
    Column("finished_at", TZ),
    CheckConstraint("status IN ('pending', 'running', 'done', 'failed')", name="status"),
    Index("ix_jobs_status_run_at", "status", "run_at"),
)

# A mailbox the user connected. The refresh token is stored encrypted only.
email_connections = Table(
    "email_connections",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("provider", Text, nullable=False),
    Column("address", Text, nullable=False),
    Column("token", LargeBinary, nullable=False),
    Column("status", Text, nullable=False),
    Column("synced_until", TZ),
    Column("last_error", Text),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    # Forwarding addresses only: when mail last arrived, and when we last said
    # it had gone quiet.
    Column("last_received_at", TZ),
    Column("nudged_at", TZ),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    UniqueConstraint("id", "user_id"),
    UniqueConstraint("user_id", "provider", "address"),
    CheckConstraint("provider IN ('gmail', 'forward')", name="provider"),
    CheckConstraint("status IN ('active', 'broken')", name="status"),
)

# Every email a sweep looked at and what became of it: sender, subject and
# outcome, never the body. Unique per mailbox message, so none is read twice.
inbound_emails = Table(
    "inbound_emails",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("connection_id", UUID(as_uuid=True), nullable=False),
    Column("provider_message_id", Text, nullable=False),
    Column("received_at", TZ, nullable=False),
    Column("sender", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("reason", Text),
    Column("draft", JSONB),
    Column("transaction_id", UUID(as_uuid=True)),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(
        ["connection_id", "user_id"],
        ["email_connections.id", "email_connections.user_id"],
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    UniqueConstraint("connection_id", "provider_message_id"),
    CheckConstraint(
        "status IN ('pending', 'logged', 'skipped', 'not_receipt', 'no_amount', "
        "'duplicate', 'failed')",
        name="status",
    ),
    Index("ix_inbound_emails_user_id_received_at", "user_id", "received_at"),
)

# One-time links that start connecting a mailbox, outside the web session (a
# Telegram button opens the system browser). Stored only as a hash.
email_links = Table(
    "email_links",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("expires_at", TZ, nullable=False),
    Column("used_at", TZ),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
)

# A trip (M11a): dates, a budget and set-aside in the home currency, and who's going.
# A famous view of a place in a season, from Wikimedia Commons, shared by every trip
# there; or the note that none was found ("none"), so it isn't looked for again soon.
destination_photos = Table(
    "destination_photos",
    metadata,
    _uuid_pk(),
    Column("place_key", Text, nullable=False),
    Column("season", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("latitude", Numeric(8, 5)),
    Column("spot", Text),
    Column("author", Text),
    Column("licence", Text),
    Column("licence_url", Text),
    Column("page", Text),
    Column("mime", Text),
    Column("data", LargeBinary),
    Column("created_at", TZ, nullable=False),
    UniqueConstraint("place_key", "season"),
    CheckConstraint("season IN ('spring', 'summer', 'autumn', 'winter', 'any')", name="season"),
    CheckConstraint("status IN ('ready', 'none')", name="status"),
    CheckConstraint(
        "status = 'none' OR (data IS NOT NULL AND mime IS NOT NULL AND author IS NOT NULL "
        "AND licence IS NOT NULL)",
        name="ready_has_photo",
    ),
)

trips = Table(
    "trips",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("destination", Text, nullable=False),
    Column("start_on", Date, nullable=False),
    Column("end_on", Date, nullable=False),
    Column("currency", CURRENCY, nullable=False),
    Column("home_currency", CURRENCY, nullable=False),
    Column("budget", MONEY),
    Column("set_aside", MONEY),
    Column("companions", JSONB, nullable=False),
    Column("planned", JSONB, nullable=False),
    Column("created_at", TZ, nullable=False),
    Column("updated_at", TZ, nullable=False),
    Column("notes", Text),  # the user's own: what to pack, who to meet (M11 follow-up)
    # A label per day, {"2026-12-12": "Busan"} (migration 0030).
    Column("day_labels", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    # Its header photo, and when one was last looked for (migration 0033).
    Column("photo_id", UUID(as_uuid=True)),
    Column("photo_tried_at", TZ),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(["photo_id"], ["destination_photos.id"], ondelete="SET NULL"),
    UniqueConstraint("id", "user_id"),
    CheckConstraint("end_on >= start_on", name="dates"),
    CheckConstraint("budget IS NULL OR budget > 0", name="budget_positive"),
    CheckConstraint("set_aside IS NULL OR set_aside > 0", name="set_aside_positive"),
    Index("ix_trips_user_id_start_on", "user_id", "start_on"),
)

# An expense added to a trip by hand (included), or taken off one its dates and
# currency would have put it on (excluded).
trip_links = Table(
    "trip_links",
    metadata,
    _user_fk(),
    Column("trip_id", UUID(as_uuid=True), nullable=False),
    Column("transaction_id", UUID(as_uuid=True), nullable=False),
    Column("included", Boolean, nullable=False),
    Column("created_at", TZ, nullable=False),
    PrimaryKeyConstraint("trip_id", "transaction_id"),
    ForeignKeyConstraint(["trip_id", "user_id"], ["trips.id", "trips.user_id"], ondelete="CASCADE"),
    ForeignKeyConstraint(
        ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    Index("ix_trip_links_user_id_transaction_id", "user_id", "transaction_id"),
)


# A flight, hotel or train booking read from email (M11b), or an itinerary entry the
# user added by hand (no email_id), including plans. Only what's needed to travel;
# references and personal numbers are never stored.
trip_bookings = Table(
    "trip_bookings",
    metadata,
    _uuid_pk(),
    _user_fk(),
    Column("trip_id", UUID(as_uuid=True)),
    Column("email_id", UUID(as_uuid=True)),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("start_on", Date),  # None: a place to visit without a day yet (0030)
    Column("end_on", Date),
    Column("details", JSONB, nullable=False),
    Column("amount", MONEY),
    Column("currency", CURRENCY),
    Column("transaction_id", UUID(as_uuid=True)),
    Column("created_at", TZ, nullable=False),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(["trip_id", "user_id"], ["trips.id", "trips.user_id"]),
    ForeignKeyConstraint(
        ["transaction_id", "user_id"], ["transactions.id", "transactions.user_id"]
    ),
    UniqueConstraint("user_id", "email_id"),
    CheckConstraint("kind IN ('flight', 'hotel', 'rail', 'activity')", name="kind"),
    CheckConstraint("(amount IS NULL) = (currency IS NULL)", name="cost"),
    Index("ix_trip_bookings_user_id_start_on", "user_id", "start_on"),
)

# Travel reminders already sent (passport, check-in, hotel address), once each.
trip_reminders = Table(
    "trip_reminders",
    metadata,
    _user_fk(),
    Column("key", Text, nullable=False),
    Column("sent_at", TZ, nullable=False),
    PrimaryKeyConstraint("user_id", "key"),
    ForeignKeyConstraint(["user_id"], ["users.id"]),
)


# Tables LangGraph's Postgres checkpointer creates for itself (migration 0003).
CHECKPOINT_TABLES = frozenset(
    {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "checkpoint_migrations"}
)
