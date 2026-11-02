"""Everything tied to one user, in one place: read for "Export all my data" and removed by
"Delete my data".

``TIES`` says how each user-owned table points at its user, and is used for both, so what is
exported is exactly what is deleted. ``ERASE_ORDER`` is the order the rows go in, children
before the rows they reference, the users row last. ``tests/unit/test_user_data_coverage.py``
reads the schema and fails if a table is in neither ``application.user_data`` (owned) nor its
``SHARED`` list, or if a user-pointing column is missing from ``TIES``, so a new table can't be
silently missed.
"""

import re
from typing import Any

from sqlalchemy import Column, LargeBinary, String, Table, cast, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import ColumnElement

from nexus.domain.ledger import UserId
from nexus.infra.db.tables import demo_costs, jobs, metadata, model_costs, users

# Columns that are tied to the user by something other than ``user_id``. Every other owned
# table is tied by ``user_id``. A table's columns are OR-ed: a membership belongs both to the
# trip's owner and to the member.
_OTHER_TIES: dict[str, tuple[str, ...]] = {
    "users": ("id",),
    "invites": ("created_by", "redeemed_by"),
    "trip_members": ("owner_id", "member_id"),
    "trip_invites": ("owner_id", "redeemed_by"),
    "trip_activity": ("owner_id", "actor_id"),
    # Queued work names its user in the payload (and Telegram's button-expiry jobs the chat).
    "jobs": ("payload->user_id",),
}

# Children before the rows they reference; the users row is last. Each statement is plain
# DELETE ... WHERE <tie>, so nothing here relies on a foreign key cascading.
ERASE_ORDER: tuple[str, ...] = (
    "jobs",
    # The trips: everything under them (other people's memberships, invites and activity
    # included), then the trips; then the user's own memberships on other people's trips,
    # which the same three statements remove.
    "trip_activity",
    "trip_members",
    "trip_invites",
    "trip_changes",
    "trip_links",
    "trip_covers",
    "trip_paid_by_others",
    "trip_shares",
    "trip_bookings",
    "trips",
    # Mail, then the ledger from the leaves in.
    "inbound_emails",
    "email_links",
    "email_connections",
    "settlements",
    "splits",
    "receipts",
    "transaction_sources",
    "transaction_revisions",
    "duplicate_dismissals",
    "transactions",
    "category_rules",
    "split_habits",
    "budget_alerts",
    "budgets",
    "bill_occurrences",
    "bills",
    "categories",
    "wallets",
    # Planning, investment, memory and notifications.
    "salary_schedules",
    "subscriptions",
    "statement_mappings",
    "statement_imports",
    "notifications",
    "notification_settings",
    "voice_settings",
    "memories",
    "chat_log",
    "capability_gaps",
    "model_costs",
    "holding_drafts",
    "market_alerts",
    "trades",
    "dividends",
    "holdings",
    "watchlist",
    "plans",
    "department_runs",
    "trip_reminders",
    # Sign-in state, then the invites the user made or used, then the user.
    "web_sessions",
    "login_links",
    "invites",
    "users",
)

# The LangGraph checkpointer's tables (migration 0003) keyed by chat thread. Not in the
# metadata, so they are named here; ``checkpoint_migrations`` is the library's own version
# table and holds nothing of anyone's.
CHECKPOINT_THREAD_TABLES: tuple[str, ...] = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")

# "tokens" is a count of words a model read or wrote, not a secret; "token" and "token_hash" are.
_SECRET_NAME = re.compile(r"token(?!s)|secret|password|passwd|csrf|hash", re.IGNORECASE)
_ORDER_BY = ("created_at", "occurred_at", "added_at", "at", "traded_on", "day")


def tie_columns(table: str) -> tuple[str, ...]:
    """The columns that tie a row of an owned ``table`` to a user."""
    return _OTHER_TIES.get(table, ("user_id",))


def is_secret(column: Column[Any]) -> bool:
    """A token, hash, password-like value or encrypted blob: never exported."""
    return bool(_SECRET_NAME.search(column.name)) or isinstance(column.type, LargeBinary)


def exported_columns(table: Table) -> list[Column[Any]]:
    return [c for c in table.c if not is_secret(c)]


def _where(name: str, user_id: UserId) -> ColumnElement[bool]:
    """The rows of ``name`` that belong to ``user_id``. The only place a row is matched to a
    user, for reading and deleting alike."""
    table = metadata.tables[name]
    clauses: list[ColumnElement[bool]] = []
    for column in tie_columns(name):
        if column == "payload->user_id":
            clauses.append(jobs.c.payload["user_id"].astext == str(user_id))
            chat = select(cast(users.c.telegram_chat_id, String)).where(users.c.id == user_id)
            clauses.append(jobs.c.payload["chat_id"].astext == chat.scalar_subquery())
        else:
            clauses.append(table.c[column] == user_id)
    return or_(*clauses)


class SqlUserData:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def rows(self, user_id: UserId, table: str) -> list[dict[str, Any]]:
        if table not in ERASE_ORDER:
            raise ValueError(f"{table} is not a user-owned table")
        t = metadata.tables[table]
        order = [t.c[name] for name in _ORDER_BY if name in t.c] + list(t.primary_key.columns)
        stmt = select(*exported_columns(t)).where(_where(table, user_id)).order_by(*order)
        return [dict(row) for row in (await self._c.execute(stmt)).mappings()]

    async def erase(self, user_id: UserId, *, chat_thread: str) -> None:
        # Wait for anything in flight that is adding a row for this user (such a row would
        # block deleting them); once we hold the row, nothing new can be added.
        locked = await self._c.execute(
            select(users.c.id).where(users.c.id == user_id).with_for_update()
        )
        if locked.first() is None:
            return
        await self._keep_demo_costs(user_id)
        for name in ERASE_ORDER:
            await self._c.execute(delete(metadata.tables[name]).where(_where(name, user_id)))
        for name in CHECKPOINT_THREAD_TABLES:
            # The names are the constants above, never input.
            await self._c.execute(
                text(f"DELETE FROM {name} WHERE thread_id = :thread"),  # noqa: S608
                {"thread": chat_thread},
            )

    async def _keep_demo_costs(self, user_id: UserId) -> None:
        """A demo account's model costs go with it; first add them to the demo totals, which
        hold no user, so the day's demo spend (a daily cap reads it) and the owner's cost page
        keep them. Nothing for a real user."""
        m = model_costs.c
        spent = (
            select(
                m.day, m.feature, m.model,
                func.sum(m.calls), func.sum(m.input_tokens), func.sum(m.output_tokens),
                func.sum(m.cached_tokens), func.sum(m.cost_usd),
            )
            .where(m.user_id == user_id)
            .where(
                select(users.c.id)
                .where(users.c.id == user_id, users.c.demo_expires_at.is_not(None))
                .exists()
            )
            .group_by(m.day, m.feature, m.model)
        )  # fmt: skip
        d = demo_costs.c
        insert_costs = pg_insert(demo_costs).from_select(
            [d.day, d.feature, d.model, d.calls, d.input_tokens, d.output_tokens,
             d.cached_tokens, d.cost_usd],
            spent,
        )  # fmt: skip
        await self._c.execute(
            insert_costs.on_conflict_do_update(
                index_elements=[d.day, d.feature, d.model],
                set_={
                    "calls": d.calls + insert_costs.excluded.calls,
                    "input_tokens": d.input_tokens + insert_costs.excluded.input_tokens,
                    "output_tokens": d.output_tokens + insert_costs.excluded.output_tokens,
                    "cached_tokens": d.cached_tokens + insert_costs.excluded.cached_tokens,
                    "cost_usd": d.cost_usd + insert_costs.excluded.cost_usd,
                },
            )
        )
