import pytest
from core.shared_tools.email_presets import build_gmail_query
from capabilities.expenses.schemas import ExtractedExpense
from capabilities.expenses.tools import is_duplicate_expense, process_extracted_expense

def test_gmail_query_builder():
    query = build_gmail_query(
        tracked_banks=["chase.com", "citi.com"],
    )
    assert "-label:Assistant/Processed" in query
    assert "chase.com" in query

    custom = build_gmail_query(custom_query="receipt")
    assert custom == "receipt"

@pytest.mark.asyncio
async def test_expense_processing_and_hitl_trigger():
    # 1. High confidence expense should process silently
    res_high = await process_extracted_expense.ainvoke({
        "user_id": 3001,
        "amount": 12.50,
        "currency": "USD",
        "merchant": "Target",
        "category": "Shopping",
        "date_iso": "2026-08-01T10:00:00Z",
        "confidence": 0.95,
        "needs_clarification": False,
        "source_message_id": "msg_target_001",
    })
    assert res_high["status"] == "saved_silently"

    # 2. Duplicate source_message_id should be rejected by layer 2 deduplication
    res_dup = await process_extracted_expense.ainvoke({
        "user_id": 3001,
        "amount": 12.50,
        "currency": "USD",
        "merchant": "Target",
        "category": "Shopping",
        "date_iso": "2026-08-01T10:00:00Z",
        "confidence": 0.95,
        "needs_clarification": False,
        "source_message_id": "msg_target_001",
    })
    assert res_dup["status"] == "duplicate"

from core.shared_tools.email_presets import build_outlook_query
from capabilities.email.tools import (
    search_email_messages,
    search_outlook_messages,
    apply_email_processed_tag,
    apply_outlook_processed_category,
)

def test_outlook_query_builder():
    odata_params = build_outlook_query(tracked_banks=["chase.com", "citi.com"])
    assert "$search" in odata_params
    assert "$filter" in odata_params
    assert "not(categories/any(c:c eq 'Assistant/Processed'))" in odata_params["$filter"]
    assert "chase.com" in odata_params["$search"]

    custom = build_outlook_query(custom_query="receipt")
    assert custom["$search"] == '"receipt"'

@pytest.mark.asyncio
async def test_search_email_messages_multi_provider():
    # Explicitly query Outlook provider
    outlook_results = await search_outlook_messages.ainvoke({"user_id": 3002})
    assert len(outlook_results) == 1
    assert outlook_results[0]["provider"] == "outlook"
    assert "Amazon" in outlook_results[0]["subject"]

    # Unified search without explicit provider should default to configured providers (default: gmail)
    unified_results = await search_email_messages.ainvoke({"user_id": 3002})
    assert len(unified_results) >= 1

@pytest.mark.asyncio
async def test_apply_email_processed_tag():
    assert await apply_email_processed_tag.ainvoke({"user_id": 3002, "message_id": "msg_outlook_1", "provider": "outlook"}) is True
    assert await apply_outlook_processed_category.ainvoke({"user_id": 3002, "message_id": "msg_outlook_1"}) is True

@pytest.mark.asyncio
async def test_deleted_expense_tombstone_deduplication():
    from core.models import DeletedExpenseMessage
    from core.db import async_session_factory
    from capabilities.expenses.tools import is_duplicate_expense

    msg_id = "test_tombstone_msg_123"
    # Initially not duplicate
    assert await is_duplicate_expense(msg_id) is False

    # Insert tombstone
    async with async_session_factory() as session:
        session.add(DeletedExpenseMessage(user_id=9999, source_message_id=msg_id))
        await session.commit()

    # Now is_duplicate_expense should return True
    assert await is_duplicate_expense(msg_id) is True

