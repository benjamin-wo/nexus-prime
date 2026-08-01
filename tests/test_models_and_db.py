import pytest
from datetime import datetime, timezone as dt_timezone
from sqlmodel import select
from sqlalchemy.exc import IntegrityError
from core.db import async_session_factory
from core.models import UserProfile, ExpenseTransaction

@pytest.mark.asyncio
async def test_user_profile_crud():
    async with async_session_factory() as session:
        user = UserProfile(
            user_id=1001,
            telegram_chat_id=5001,
            current_timezone="Asia/Tokyo",
            home_currency="JPY",
            tracked_banks=["chase.com"],
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        assert user.user_id == 1001
        assert user.current_timezone == "Asia/Tokyo"
        assert "chase.com" in user.tracked_banks

@pytest.mark.asyncio
async def test_expense_unique_source_message_id():
    async with async_session_factory() as session:
        tx1 = ExpenseTransaction(
            user_id=1001,
            amount=15.00,
            currency="USD",
            merchant="Starbucks",
            category="Food",
            date=datetime.now(dt_timezone.utc),
            source_message_id="msg_unique_001",
        )
        session.add(tx1)
        await session.commit()

        tx2 = ExpenseTransaction(
            user_id=1001,
            amount=20.00,
            currency="USD",
            merchant="Starbucks",
            category="Food",
            date=datetime.now(dt_timezone.utc),
            source_message_id="msg_unique_001",  # Same ID should violate unique index
        )
        session.add(tx2)
        with pytest.raises(IntegrityError):
            await session.commit()
