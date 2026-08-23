import pytest
from datetime import datetime, timedelta, timezone
from httpx import ASGITransport, AsyncClient
from sqlmodel import select
from capabilities.expenses.tools import split_bill_expense, save_expense_transaction
from capabilities.expenses.schemas import ExtractedExpense
from core.models import IncomeTransaction, TaskItem, ExpenseTransaction
from core.db import async_session_factory
from app.main import app


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

    # 3. Verify the parent expense remains the gross bill total in the ledger.
    async with async_session_factory() as session:
        updated_tx = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == tx.id)
        )).scalar_one()
        assert updated_tx.amount == 160.0
        assert updated_tx.split_data["gross_total"] == 160.0
        assert updated_tx.split_data["my_share"] == 40.0
        assert updated_tx.split_data["share_amounts"]["Alex"] == 40.0

        # Verify 3 IOU tasks are created
        tasks = (await session.execute(
            select(TaskItem).where(TaskItem.user_id == user_id, TaskItem.status == "todo")
        )).scalars().all()
        assert len(tasks) == 3
        task_titles = [t.title for t in tasks]
        assert any("Alex" in t and "$40.00" in t for t in task_titles)
        assert any("Chloe" in t and "$40.00" in t for t in task_titles)
        assert any("Ben" in t and "$40.00" in t for t in task_titles)


@pytest.mark.asyncio
async def test_split_bill_custom_shares_and_validation():
    """Custom final amounts support uneven shares and reject non-reconciling totals."""
    user_id = 998812
    exp = ExtractedExpense(
        amount=30.0,
        currency="SGD",
        merchant="PLQ",
        category="Shopping",
        date=datetime.now(timezone.utc).replace(tzinfo=None),
        confidence=0.95,
        needs_clarification=False,
    )
    tx = await save_expense_transaction(user_id=user_id, expense=exp)

    result = await split_bill_expense.ainvoke({
        "user_id": user_id,
        "total_amount": 30.0,
        "merchant": "PLQ",
        "people": ["Alex"],
        "custom_amounts": {"Me": 20.0, "Alex": 10.0},
        "transaction_id": tx.id,
    })
    assert result["status"] == "ok"
    assert result["my_share"] == 20.0
    assert result["per_person"] is None
    assert result["custom_amounts"] == {"Me": 20.0, "Alex": 10.0}
    assert result["tasks"][0]["amount"] == 10.0
    assert "Alex: $10.00" in result["reply_text"]
    assert "Me: $20.00" in result["reply_text"]

    async with async_session_factory() as session:
        updated = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == tx.id)
        )).scalar_one()
        assert updated.amount == 30.0
        assert updated.split_data["gross_total"] == 30.0
        assert updated.split_data["my_share"] == 20.0
        assert updated.split_data["share_amounts"] == {"Me": 20.0, "Alex": 10.0}

    invalid = await split_bill_expense.ainvoke({
        "user_id": user_id,
        "total_amount": 30.0,
        "merchant": "PLQ",
        "people": ["Alex"],
        "custom_amounts": {"Me": 20.0, "Alex": 9.0},
        "transaction_id": tx.id,
    })
    assert invalid["status"] == "needs_adjustment"
    assert "30.00" in invalid["message"]


@pytest.mark.asyncio
async def test_iou_settlement_updates_split_task_and_income_once():
    user_id = 998813
    exp = ExtractedExpense(
        amount=30.0,
        currency="SGD",
        merchant="PLQ",
        category="Dining",
        date=datetime.now(timezone.utc).replace(tzinfo=None),
        confidence=0.95,
        needs_clarification=False,
    )
    tx = await save_expense_transaction(user_id=user_id, expense=exp)
    split = await split_bill_expense.ainvoke({
        "user_id": user_id,
        "total_amount": 30.0,
        "merchant": "PLQ",
        "people": ["Alex"],
        "custom_amounts": {"Me": 20.0, "Alex": 10.0},
        "transaction_id": tx.id,
    })
    task_id = split["tasks"][0]["task_id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        before = await client.get(
            f"/api/dashboard/transactions?user_id={user_id}&direction=outgoing"
        )
        assert before.status_code == 200
        assert before.json()["transactions"][0]["status"] == "pending"

        settled = await client.post(
            f"/api/dashboard/transactions/out-{tx.id:06d}/settle?user_id={user_id}",
            json={"participant": "Alex"},
        )
        assert settled.status_code == 200
        assert settled.json()["settlement"]["status"] == "settled"
        assert settled.json()["settlement"]["amount_received"] == 10.0

        repeated = await client.post(
            f"/api/dashboard/transactions/out-{tx.id:06d}/settle?user_id={user_id}",
            json={"participant": "Alex"},
        )
        assert repeated.status_code == 200
        assert repeated.json()["settlement"]["status"] == "already_settled"

        after = await client.get(
            f"/api/dashboard/transactions?user_id={user_id}&direction=outgoing"
        )
        assert after.status_code == 200
        assert after.json()["transactions"][0]["status"] == "paid"

    async with async_session_factory() as session:
        updated_tx = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == tx.id)
        )).scalar_one()
        task = (await session.execute(
            select(TaskItem).where(TaskItem.id == task_id)
        )).scalar_one()
        repayments = (await session.execute(
            select(IncomeTransaction).where(
                IncomeTransaction.user_id == user_id,
                IncomeTransaction.linked_expense_id == tx.id,
            )
        )).scalars().all()

        assert updated_tx.split_data["paid_status"]["Alex"] is True
        assert task.status == "done"
        assert len(repayments) == 1
        assert repayments[0].amount == 10.0


@pytest.mark.asyncio
async def test_telegram_iou_button_settles_linked_repayment():
    from app.ingress import TelegramIngress

    user_id = 998814
    exp = ExtractedExpense(
        amount=20.0,
        currency="SGD",
        merchant="Cafe",
        category="Dining",
        date=datetime.now(timezone.utc).replace(tzinfo=None),
        confidence=0.95,
        needs_clarification=False,
    )
    tx = await save_expense_transaction(user_id=user_id, expense=exp)
    split = await split_bill_expense.ainvoke({
        "user_id": user_id,
        "total_amount": 20.0,
        "merchant": "Cafe",
        "people": ["Mina"],
        "transaction_id": tx.id,
    })
    task_id = split["tasks"][0]["task_id"]

    result = await TelegramIngress().handle_callback_query({
        "id": "iou-callback-1",
        "from": {"id": user_id},
        "message": {"chat": {"id": user_id}, "message_id": 1},
        "data": f"td:{task_id}",
    })

    assert result["status"] == "ok"
    assert result["action"] == "iou_settled"
    async with async_session_factory() as session:
        task = (await session.execute(select(TaskItem).where(TaskItem.id == task_id))).scalar_one()
        repayment = (await session.execute(
            select(IncomeTransaction).where(IncomeTransaction.linked_expense_id == tx.id)
        )).scalars().first()
    assert task.status == "done"
    assert repayment is not None


@pytest.mark.asyncio
async def test_assistant_repayment_settles_matching_iou():
    from langchain_core.messages import HumanMessage
    from orchestrator.router import ExpensePlugin

    user_id = 998815
    exp = ExtractedExpense(
        amount=37.05,
        currency="SGD",
        merchant="Dinner",
        category="Dining",
        date=datetime.now(timezone.utc).replace(tzinfo=None),
        confidence=0.95,
        needs_clarification=False,
    )
    tx = await save_expense_transaction(user_id=user_id, expense=exp)
    await split_bill_expense.ainvoke({
        "user_id": user_id,
        "total_amount": 37.05,
        "merchant": "Dinner",
        "people": ["Loren"],
        "custom_amounts": {"Me": 24.05, "Loren": 13.00},
        "transaction_id": tx.id,
    })

    result = await ExpensePlugin().execute({
        "messages": [HumanMessage(content="Loren already paid me $13 yesterday")],
        "user_id": user_id,
        "active_domain": None,
    })

    assert "marked their IOU as paid" in str(result.message.content)
    async with async_session_factory() as session:
        updated_tx = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == tx.id)
        )).scalar_one()
        task = (await session.execute(
            select(TaskItem).where(
                TaskItem.user_id == user_id,
                TaskItem.linked_expense_id == tx.id,
            )
        )).scalar_one()
        repayment = (await session.execute(
            select(IncomeTransaction).where(
                IncomeTransaction.linked_expense_id == tx.id,
            )
        )).scalar_one()

    assert updated_tx.split_data["paid_status"]["Loren"] is True
    assert task.status == "done"
    assert repayment.amount == 13.0
    assert repayment.source == "Loren"


@pytest.mark.asyncio
async def test_assistant_repayment_settles_web_split_without_iou_task():
    from langchain_core.messages import HumanMessage
    from orchestrator.router import ExpensePlugin

    user_id = 998816
    exp = ExtractedExpense(
        amount=37.05,
        currency="SGD",
        merchant="PLQ",
        category="Shopping",
        date=datetime.now(timezone.utc).replace(tzinfo=None),
        confidence=0.95,
        needs_clarification=False,
    )
    tx = await save_expense_transaction(user_id=user_id, expense=exp)
    async with async_session_factory() as session:
        saved_tx = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == tx.id)
        )).scalar_one()
        saved_tx.split_data = {
            "friends": ["Me", "lorren"],
            "paid_status": {"Me": True, "lorren": False},
            "custom_amounts": {"Me": 24.05, "lorren": 13.00},
            "split_mode": "custom",
        }
        session.add(saved_tx)
        await session.commit()

    result = await ExpensePlugin().execute({
        "messages": [HumanMessage(content="Loren already paid me $13 yesterday")],
        "user_id": user_id,
        "active_domain": None,
    })

    assert "marked their IOU as paid" in str(result.message.content)
    async with async_session_factory() as session:
        updated_tx = (await session.execute(
            select(ExpenseTransaction).where(ExpenseTransaction.id == tx.id)
        )).scalar_one()
        repayment = (await session.execute(
            select(IncomeTransaction).where(
                IncomeTransaction.linked_expense_id == tx.id,
            )
        )).scalar_one()

    assert updated_tx.split_data["paid_status"]["lorren"] is True
    assert updated_tx.split_data["paid_amounts"]["lorren"] == 13.0
    assert repayment.amount == 13.0


def test_parse_incoming_transaction_text():
    from capabilities.expenses.tools import parse_incoming_transaction_text

    parsed = parse_incoming_transaction_text("Loren already paid me $13 yesterday")
    assert parsed is not None
    assert parsed["amount"] == 13.0
    assert parsed["source"] == "Loren"
    assert parsed["category"] == "Friend Repayment"
    parsed_date = datetime.fromisoformat(parsed["date_iso"])
    assert parsed_date.date() == (datetime.now(timezone.utc) - timedelta(days=1)).date()


def test_parse_custom_split_amounts():
    from app.ingress import parse_custom_split_amounts

    assert parse_custom_split_amounts(
        "/split 30 with Alex, I pay $20 and Alex pays $10"
    ) == {"Me": 20.0, "Alex": 10.0}
    assert parse_custom_split_amounts(
        "/split 30 with Alex, my share $20, Alex: $10"
    ) == {"Me": 20.0, "Alex": 10.0}
    assert parse_custom_split_amounts("/split 30 with Alex") == {}
