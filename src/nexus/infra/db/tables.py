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
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
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
    ForeignKeyConstraint(["user_id"], ["users.id"]),
    ForeignKeyConstraint(["category_id", "user_id"], ["categories.id", "categories.user_id"]),
    UniqueConstraint("id", "user_id"),
    CheckConstraint("direction IN ('in', 'out')", name="direction"),
    CheckConstraint("amount > 0", name="amount_positive"),
    CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
    CheckConstraint("status IN ('confirmed', 'pending')", name="status"),
    CheckConstraint("source IN ('text', 'photo', 'email', 'import', 'manual')", name="source"),
    Index("ix_transactions_user_id_occurred_at", "user_id", "occurred_at"),
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
