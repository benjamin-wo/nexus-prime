"""Read the pre-rebuild database without writing to it.

The old schema drifted from its models over time, so columns are discovered
from the live database: required ones must exist, optional ones default.
Everything is read inside one READ ONLY transaction.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg

# table -> (required columns, optional columns)
_TABLES: dict[str, tuple[set[str], set[str]]] = {
    "userprofile": (
        {"user_id"},
        {"telegram_chat_id", "current_timezone", "home_currency"},
    ),
    "expensetransaction": (
        {"id", "user_id", "amount", "currency", "date"},
        {"merchant", "category", "notes", "is_verified", "source_message_id", "split_data"},
    ),
    "incometransaction": (
        {"id", "user_id", "amount", "date"},
        {"currency", "source", "category", "notes", "source_message_id", "linked_expense_id"},
    ),
    "deletedexpensemessage": ({"user_id", "source_message_id"}, set()),
    "taskitem": (
        {"id", "user_id"},
        {"status", "linked_expense_id", "iou_friend", "iou_amount"},
    ),
}


class LegacySchemaError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LegacyUser:
    telegram_user_id: int
    telegram_chat_id: int | None
    timezone: str | None
    home_currency: str | None


@dataclass(frozen=True, slots=True)
class LegacyExpense:
    id: int
    user_id: int
    amount: float
    currency: str
    occurred_at: datetime
    merchant: str | None
    category: str | None
    notes: str | None
    verified: bool
    source_message_id: str | None
    split_data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LegacyIncome:
    id: int
    user_id: int
    amount: float
    currency: str | None
    occurred_at: datetime
    source: str | None
    category: str | None
    notes: str | None
    source_message_id: str | None
    linked_expense_id: int | None


@dataclass(frozen=True, slots=True)
class LegacyIouTask:
    id: int
    user_id: int
    expense_id: int
    friend: str
    amount: float | None
    done: bool


@dataclass
class LegacySnapshot:
    users: list[LegacyUser] = field(default_factory=list)
    expenses: list[LegacyExpense] = field(default_factory=list)
    incomes: list[LegacyIncome] = field(default_factory=list)
    tombstones: list[tuple[int, str]] = field(default_factory=list)  # (user_id, message id)
    iou_tasks: list[LegacyIouTask] = field(default_factory=list)


def _json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else {}
    return value if isinstance(value, dict) else {}


async def _columns(conn: asyncpg.Connection, table: str) -> set[str]:
    rows = await conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = $1",
        table,
    )
    return {r["column_name"] for r in rows}


async def _select(conn: asyncpg.Connection, table: str) -> list[dict[str, Any]]:
    required, optional = _TABLES[table]
    present = await _columns(conn, table)
    if not present and table in {"deletedexpensemessage", "taskitem", "incometransaction"}:
        return []  # a table the old deployment never created
    missing = required - present
    if missing:
        raise LegacySchemaError(f"{table} is missing columns {sorted(missing)}")
    wanted = sorted(required | (optional & present))
    cols = ", ".join(f'"{c}"' for c in wanted)
    rows = await conn.fetch(f'SELECT {cols} FROM "{table}"')  # noqa: S608 - names from _TABLES
    return [{c: r.get(c) for c in required | optional} for r in rows]


async def read_legacy(conn: asyncpg.Connection) -> LegacySnapshot:
    snapshot = LegacySnapshot()
    async with conn.transaction(readonly=True):
        for r in await _select(conn, "userprofile"):
            snapshot.users.append(
                LegacyUser(
                    telegram_user_id=int(r["user_id"]),
                    telegram_chat_id=r["telegram_chat_id"],
                    timezone=r["current_timezone"],
                    home_currency=r["home_currency"],
                )
            )
        for r in await _select(conn, "expensetransaction"):
            snapshot.expenses.append(
                LegacyExpense(
                    id=int(r["id"]),
                    user_id=int(r["user_id"]),
                    amount=float(r["amount"]),
                    currency=str(r["currency"] or ""),
                    occurred_at=r["date"],
                    merchant=r["merchant"],
                    category=r["category"],
                    notes=r["notes"],
                    verified=r["is_verified"] is not False,
                    source_message_id=r["source_message_id"],
                    split_data=_json(r["split_data"]),
                )
            )
        for r in await _select(conn, "incometransaction"):
            snapshot.incomes.append(
                LegacyIncome(
                    id=int(r["id"]),
                    user_id=int(r["user_id"]),
                    amount=float(r["amount"]),
                    currency=r["currency"],
                    occurred_at=r["date"],
                    source=r["source"],
                    category=r["category"],
                    notes=r["notes"],
                    source_message_id=r["source_message_id"],
                    linked_expense_id=r["linked_expense_id"],
                )
            )
        for r in await _select(conn, "deletedexpensemessage"):
            snapshot.tombstones.append((int(r["user_id"]), str(r["source_message_id"])))
        for r in await _select(conn, "taskitem"):
            if r["iou_friend"] and r["linked_expense_id"] is not None:
                snapshot.iou_tasks.append(
                    LegacyIouTask(
                        id=int(r["id"]),
                        user_id=int(r["user_id"]),
                        expense_id=int(r["linked_expense_id"]),
                        friend=str(r["iou_friend"]),
                        amount=None if r["iou_amount"] is None else float(r["iou_amount"]),
                        done=r["status"] == "done",
                    )
                )
    return snapshot
