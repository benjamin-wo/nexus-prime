import pytest
from core.shared_tools.email_presets import build_gmail_query
from capabilities.expenses.schemas import ExtractedExpense
from capabilities.expenses.tools import is_duplicate_expense, process_extracted_expense

def test_gmail_query_builder():
    query = build_gmail_query(
        tracked_banks=["chase.com", "citi.com"],
    )
    assert "chase.com" in query
    assert "newer_than:7d" in query

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

    # Register outlook credentials for user 3002 so active provider detection picks it up
    from core.models import UserCredential
    from core.db import async_session_factory
    async with async_session_factory() as session:
        cred = UserCredential(user_id=3002, provider="outlook", encrypted_token_payload="dummy")
        session.add(cred)
        await session.commit()

    # Unified search without explicit provider should default to configured providers
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


def test_email_merchant_resolution():
    from capabilities.expenses.tools import clean_sender_name, _resolve_email_merchant

    assert clean_sender_name("Grab <no-reply@grab.com>") == "Grab"
    assert clean_sender_name('"Starbucks Coffee SG" <receipts@starbucks.com.sg>') == "Starbucks Coffee SG"
    assert clean_sender_name("receipts@deliveroo.com.sg") == "Deliveroo"
    assert clean_sender_name("Apple <no_reply@email.apple.com>") == "Apple"

    # Bogus disclaimer extraction should be rejected and replaced by clean sender or subject
    resolved_grab = _resolve_email_merchant(
        extracted_merchant="receiving this",
        sender="Grab <no-reply@grab.com>",
        subject="Your Grab E-Receipt",
    )
    assert resolved_grab == "Grab"

    resolved_fp = _resolve_email_merchant(
        extracted_merchant="receiving this email and any",
        sender="no-reply@fairprice.com.sg",
        subject="Order Confirmation",
    )
    assert resolved_fp == "Fairprice"

    resolved_clean = _resolve_email_merchant(
        extracted_merchant="Toast Box",
        sender="DBS Alerts <alerts@dbs.com>",
        subject="Transaction Alert",
    )
    assert resolved_clean == "Toast Box"


def test_regex_expense_amount_precision_and_non_expense_emails():
    from capabilities.expenses.tools import _regex_extract_expense

    # 1. Genuine receipts with currency prefix
    assert _regex_extract_expense("Total Paid: SGD 11.50 for your ride")["amount"] == 11.50
    assert _regex_extract_expense("Your receipt: $5.90 at Chicken Stea")["amount"] == 5.90
    assert _regex_extract_expense("Paid: S$12.80 to Toast Box")["amount"] == 12.80

    # 2. Non-expense advisory / terms emails should NOT extract dates/years/ref IDs as prices
    assert _regex_extract_expense("DBS PayLah! Alert: Ref 7873098920963352 on 21 Aug 2026")["amount"] is None
    assert _regex_extract_expense("Apple Distribution International Ltd 2026. Privacy Policy.")["amount"] is None
    assert _regex_extract_expense("Terms & conditions update for August 2026")["amount"] is None
    assert _regex_extract_expense("Your login was detected on 21 Aug 2026")["amount"] is None


def test_gmail_payload_body_extraction():
    import base64
    from capabilities.email.providers import _extract_gmail_body

    # 1. Plain text payload
    plain_content = "Total amount paid: SGD 14.50 to Merchant XYZ on 21 Aug 2026."
    b64_plain = base64.urlsafe_b64encode(plain_content.encode("utf-8")).decode("utf-8")
    payload_plain = {
        "mimeType": "text/plain",
        "body": {"data": b64_plain},
    }
    assert "SGD 14.50" in _extract_gmail_body(payload_plain)

    # 2. HTML multipart payload
    html_content = "<html><body><p>Apple Invoice</p><p>Total: <b>$2.98</b></p><style>.hide{display:none}</style></body></html>"
    b64_html = base64.urlsafe_b64encode(html_content.encode("utf-8")).decode("utf-8")
    payload_html = {
        "mimeType": "multipart/alternative",
        "parts": [
            {
                "mimeType": "text/html",
                "body": {"data": b64_html},
            }
        ],
    }
    extracted_html = _extract_gmail_body(payload_html)
    assert "Total: $2.98" in extracted_html
    assert "<style>" not in extracted_html



