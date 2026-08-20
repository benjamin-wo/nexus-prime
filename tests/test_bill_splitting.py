import pytest
from datetime import datetime, timezone
from sqlmodel import select
from capabilities.expenses.tools import split_bill_expense, save_expense_transaction
from capabilities.expenses.schemas import ExtractedExpense
from core.models import TaskItem, ExpenseTransaction
from core.db import async_session_factory


@pytest.mark.asyncio
async def test_split_bill_equal_shares_and_task_creation():
    user_id = 998811
    
    # 1. First save a parent expense
    exp = ExtractedExpense(
        amount=160.0,
        currency="SGD",
        merchant="Haidilao Hotpot",
        category="Dining",
        date=datetime.now(timezone.utc).replace(tzinfo=None),
        confidence=0.95,
        needs_clarification=False,
    )
    tx = await save_expense_transaction(user_id=user_id, expense=exp)
    assert tx.id is not None
    assert tx.amount == 160.0

    # 2. Split with 3 friends (Alex, Chloe, Ben) + user = 4 people total ($40 each)
    res = await split_bill_expense.ainvoke({
        "user_id": user_id,
        "total_amount": 160.0,
        "merchant": "Haidilao Hotpot",
        "people": ["Alex", "Chloe", "Ben"],
        "transaction_id": tx.id,
    })

    assert res["status"] == "ok"
    assert res["per_person"] == 40.0
    assert res["my_share"] == 40.0
    assert len(res["friends"]) == 3
    assert len(res["tasks"]) == 3
    assert "Alex: **$40.00**" in res["reply_text"]
    assert "PayNow" in res["reply_text"]

    # 3. Verify user's parent expense is adjusted to net share ($40.00) in database
    async with async_session_factory() as session:
        updated_tx = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == tx.id)
        )).scalar_one()
        assert updated_tx.amount == 40.0

        # Verify 3 IOU tasks are created
        tasks = (await session.execute(
            select(TaskItem).where(TaskItem.user_id == user_id, TaskItem.status == "todo")
        )).scalars().all()
        assert len(tasks) == 3
        task_titles = [t.title for t in tasks]
        assert any("Alex" in t and "$40.00" in t for t in task_titles)
        assert any("Chloe" in t and "$40.00" in t for t in task_titles)
        assert any("Ben" in t and "$40.00" in t for t in task_titles)
