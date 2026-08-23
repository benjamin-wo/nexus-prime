from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_income_crud_and_summary():
    user_id = 3005
    date_iso = datetime.now(timezone.utc).isoformat()
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        salary = await client.post(
            f"/api/dashboard/income?user_id={user_id}",
            json={
                "amount": 3500.00,
                "currency": "SGD",
                "source": "Employer",
                "category": "Salary",
                "date": date_iso,
                "notes": "August salary",
            },
        )
        assert salary.status_code == 200
        salary_item = salary.json()["income"]
        assert salary_item["amount"] == 3500.0
        assert salary_item["category"] == "Salary"

        repayment = await client.post(
            f"/api/dashboard/income?user_id={user_id}",
            json={
                "amount": 13.00,
                "currency": "SGD",
                "source": "Loren",
                "category": "Friend repayment",
                "date": date_iso,
                "notes": "Cash repayment for dinner",
            },
        )
        assert repayment.status_code == 200
        repayment_id = repayment.json()["income"]["id"]

        listed = await client.get(f"/api/dashboard/income?user_id={user_id}")
        assert listed.status_code == 200
        assert listed.json()["count"] == 2

        summary = await client.get(f"/api/dashboard/summary?user_id={user_id}")
        assert summary.status_code == 200
        summary_data = summary.json()
        assert summary_data["total_income_month"] == 3513.0
        assert summary_data["income_transactions_count"] == 2
        assert summary_data["net_cash_flow_month"] == 3513.0

        updated = await client.put(
            f"/api/dashboard/income/{salary_item['id']}?user_id={user_id}",
            json={"amount": 3600.00, "notes": "Corrected salary amount"},
        )
        assert updated.status_code == 200
        assert updated.json()["income"]["amount"] == 3600.0

        deleted = await client.delete(
            f"/api/dashboard/income/{repayment_id}?user_id={user_id}"
        )
        assert deleted.status_code == 200
        assert deleted.json()["deleted_id"] == repayment_id

        remaining = await client.get(f"/api/dashboard/income?user_id={user_id}")
        assert remaining.json()["count"] == 1


@pytest.mark.asyncio
async def test_unified_transactions_exposes_both_directions():
    user_id = 3011
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        expense = await client.post(
            "/api/dashboard/expenses",
            json={
                "user_id": user_id,
                "amount": 42.50,
                "currency": "SGD",
                "merchant": "Amoy Hawker Centre",
                "category": "Dining",
            },
        )
        assert expense.status_code == 200

        income = await client.post(
            f"/api/dashboard/income?user_id={user_id}",
            json={
                "amount": 13.00,
                "currency": "SGD",
                "source": "Loren",
                "category": "Friend repayment",
            },
        )
        assert income.status_code == 200

        unified = await client.get(f"/api/dashboard/transactions?user_id={user_id}")
        assert unified.status_code == 200
        rows = unified.json()["transactions"]
        assert {row["direction"] for row in rows} == {"outgoing", "incoming"}
        outgoing_row = next(row for row in rows if row["direction"] == "outgoing")
        incoming_row = next(row for row in rows if row["direction"] == "incoming")
        assert outgoing_row["id"] == f"out-{outgoing_row['record_id']:06d}"
        assert incoming_row["id"] == f"in-{incoming_row['record_id']:06d}"
        assert any(row["title"] == "Amoy Hawker Centre" and row["signed_amount"] == -42.5 for row in rows)
        assert any(row["title"] == "Loren" and row["signed_amount"] == 13.0 for row in rows)

        incoming_row = next(row for row in rows if row["direction"] == "incoming")
        updated = await client.put(
            f"/api/dashboard/transactions/{incoming_row['id']}?user_id={user_id}",
            json={"notes": "Dinner repayment"},
        )
        assert updated.status_code == 200
        assert updated.json()["transaction"]["notes"] == "Dinner repayment"

        outgoing = await client.get(
            f"/api/dashboard/transactions?user_id={user_id}&direction=outgoing"
        )
        assert outgoing.status_code == 200
        assert all(row["direction"] == "outgoing" for row in outgoing.json()["transactions"])


@pytest.mark.asyncio
async def test_telegram_credit_command_records_incoming_transaction():
    from app.ingress import TelegramIngress

    result = await TelegramIngress().handle_slash_command(
        "/credit 240 from insurer claim",
        user_id=3012,
    )

    assert result is not None
    assert result["status"] == "ok"
    assert result["income"]["amount"] == 240.0
    assert result["income"]["category"] == "Claim Payout"


@pytest.mark.asyncio
async def test_assistant_records_incoming_money_from_conversation():
    from langchain_core.messages import HumanMessage
    from orchestrator.router import ExpensePlugin

    result = await ExpensePlugin().execute({
        "messages": [HumanMessage(content="Loren already paid me $13 yesterday")],
        "user_id": 3013,
        "active_domain": None,
    })

    assert "Logged" in str(result.message.content)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        transactions = await client.get("/api/dashboard/transactions?user_id=3013")
    assert transactions.status_code == 200
    incoming = transactions.json()["transactions"][0]
    assert incoming["direction"] == "incoming"
    assert incoming["title"] == "Loren"
    assert incoming["amount"] == 13.0
