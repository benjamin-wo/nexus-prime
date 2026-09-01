import pytest
from datetime import datetime, timezone as dt_timezone
from sqlmodel import select

from core.db import async_session_factory
from core.models import DeletedExpenseMessage, ExpenseTransaction, ExpenseUndoEntry
from capabilities.expenses.schemas import ExtractedExpense
from capabilities.expenses.tools import (
    delete_expense,
    edit_expense,
    process_extracted_expense,
    restore_expense,
    save_expense_transaction,
    undo_last_write,
)


async def _seed_expense(
    user_id: int,
    merchant: str,
    amount: float = 10.0,
    source_message_id: str | None = None,
) -> int:
    item = await save_expense_transaction(
        user_id=user_id,
        expense=ExtractedExpense(
            amount=amount,
            currency="SGD",
            merchant=merchant,
            category="Dining",
            date=datetime.now(dt_timezone.utc).replace(tzinfo=None),
            confidence=0.95,
        ),
        source_message_id=source_message_id,
    )
    return item.id


async def _row(expense_id: int):
    async with async_session_factory() as session:
        return (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == expense_id)
        )).scalar_one_or_none()


@pytest.mark.asyncio
async def test_edit_expense_updates_fields_and_records_undo():
    expense_id = await _seed_expense(3101, "Coinhako", amount=20.0)
    reply = await edit_expense.ainvoke({
        "expense_id": expense_id,
        "user_id": 3101,
        "amount": 12.5,
        "merchant": "CoinHako Trading",
    })
    assert "amount" in reply and "merchant" in reply
    row = await _row(expense_id)
    assert row is not None
    assert row.amount == 12.5
    assert row.merchant == "CoinHako Trading"
    async with async_session_factory() as session:
        entry = (await session.execute(
            select(ExpenseUndoEntry).where(
                ExpenseUndoEntry.user_id == 3101,
                ExpenseUndoEntry.expense_id == expense_id,
            )
        )).scalars().first()
        assert entry is not None
        assert entry.kind == "edit"
        assert entry.snapshot["amount"] == 20.0


@pytest.mark.asyncio
async def test_edit_expense_not_found():
    reply = await edit_expense.ainvoke({"expense_id": 999999, "user_id": 3101, "amount": 5.0})
    assert "No expense" in reply


@pytest.mark.asyncio
async def test_edit_expense_owner_scoped():
    expense_id = await _seed_expense(3102, "Owner")
    reply = await edit_expense.ainvoke({"expense_id": expense_id, "user_id": 3199, "amount": 5.0})
    assert "No expense" in reply
    row = await _row(expense_id)
    assert row.amount == 10.0


@pytest.mark.asyncio
async def test_delete_then_restore_round_trip():
    expense_id = await _seed_expense(3103, "Coinhako", source_message_id="msg_coinhako_rt")
    await delete_expense.ainvoke({"expense_id": expense_id, "user_id": 3103})
    assert await _row(expense_id) is None
    reply = await restore_expense.ainvoke({"expense_id": expense_id, "user_id": 3103})
    assert "Restored" in reply
    # tombstone cleared so the poller can re-log if it arrives again
    async with async_session_factory() as session:
        tomb = (await session.execute(
            select(DeletedExpenseMessage).where(
                DeletedExpenseMessage.source_message_id == "msg_coinhako_rt"
            )
        )).scalar_one_or_none()
        assert tomb is None
    restored = (await _row(expense_id)) or await _row(expense_id)
    assert restored is not None


@pytest.mark.asyncio
async def test_undo_last_write_reverts_delete():
    expense_id = await _seed_expense(3104, "Grab", source_message_id="msg_grab_undo")
    await delete_expense.ainvoke({"expense_id": expense_id, "user_id": 3104})
    reply = await undo_last_write.ainvoke({"user_id": 3104})
    assert "Undone" in reply
    assert await _row(expense_id) is not None


@pytest.mark.asyncio
async def test_undo_last_write_reverts_edit():
    expense_id = await _seed_expense(3105, "Bus")
    await edit_expense.ainvoke({"expense_id": expense_id, "user_id": 3105, "amount": 99.0})
    reply = await undo_last_write.ainvoke({"user_id": 3105})
    assert "Undone" in reply
    row = await _row(expense_id)
    assert row.amount == 10.0


@pytest.mark.asyncio
async def test_undo_last_write_reverts_create():
    res = await process_extracted_expense.ainvoke({
        "user_id": 3106,
        "amount": 42.0,
        "currency": "SGD",
        "merchant": "FairPrice",
        "category": "Groceries",
        "date_iso": "2026-09-01T12:00:00Z",
        "confidence": 0.95,
        "needs_clarification": False,
    })
    assert res["status"] == "saved_silently"
    tx_id = res["transaction_id"]
    assert await _row(tx_id) is not None
    reply = await undo_last_write.ainvoke({"user_id": 3106})
    assert "Removed" in reply
    assert await _row(tx_id) is None


@pytest.mark.asyncio
async def test_undo_last_write_nothing_to_undo():
    reply = await undo_last_write.ainvoke({"user_id": 3107})
    assert "Nothing to undo" in reply