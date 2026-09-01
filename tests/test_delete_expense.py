import pytest
from datetime import datetime, timezone as dt_timezone
from sqlmodel import select

from core.db import async_session_factory
from core.models import DeletedExpenseMessage, ExpenseTransaction
from capabilities.expenses.schemas import ExtractedExpense
from capabilities.expenses.tools import delete_expense, save_expense_transaction


async def _seed_expense(
    user_id: int,
    merchant: str,
    source_message_id: str | None = None,
) -> int:
    item = await save_expense_transaction(
        user_id=user_id,
        expense=ExtractedExpense(
            amount=10.0,
            currency="SGD",
            merchant=merchant,
            category="Dining",
            date=datetime.now(dt_timezone.utc).replace(tzinfo=None),
            confidence=0.95,
        ),
        source_message_id=source_message_id,
    )
    return item.id


@pytest.mark.asyncio
async def test_delete_expense_removes_row_and_tombstones_source():
    expense_id = await _seed_expense(3002, "Coinhako", source_message_id="msg_coinhako_1")
    reply = await delete_expense.ainvoke({"expense_id": expense_id, "user_id": 3002})
    assert "Coinhako" in reply
    async with async_session_factory() as session:
        row = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        )).scalar_one_or_none()
        assert row is None
        tomb = (await session.execute(
            select(DeletedExpenseMessage).where(
                DeletedExpenseMessage.source_message_id == "msg_coinhako_1"
            )
        )).scalar_one_or_none()
        assert tomb is not None


@pytest.mark.asyncio
async def test_delete_expense_not_found_returns_message():
    reply = await delete_expense.ainvoke({"expense_id": 999999, "user_id": 3002})
    assert "No expense" in reply


@pytest.mark.asyncio
async def test_delete_expense_is_scoped_to_owner():
    expense_id = await _seed_expense(3003, "Owned by 3003")
    reply = await delete_expense.ainvoke({"expense_id": expense_id, "user_id": 3004})
    assert "No expense" in reply
    async with async_session_factory() as session:
        row = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        )).scalar_one_or_none()
        assert row is not None


@pytest.mark.asyncio
async def test_delete_expense_without_source_message_id():
    expense_id = await _seed_expense(3005, "Manual Entry")
    reply = await delete_expense.ainvoke({"expense_id": expense_id, "user_id": 3005})
    assert "Manual Entry" in reply
    async with async_session_factory() as session:
        row = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        )).scalar_one_or_none()
        assert row is None