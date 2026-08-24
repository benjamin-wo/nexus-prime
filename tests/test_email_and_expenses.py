import pytest
from pytest import MonkeyPatch
from sqlmodel import select
from core.shared_tools.email_presets import build_gmail_query
from core.db import async_session_factory
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


@pytest.mark.asyncio
async def test_finalize_expense_sets_active_domain_without_nameerror():
    """Regression (#11): _finalize_expense was a @staticmethod that referenced
    `self.name` for the active_domain state update, so every text/photo expense
    (e.g. "Record a $15 lunch expense") crashed with NameError: name 'self' is
    not defined once it reached the finalization step."""
    from orchestrator.router import ExpensePlugin

    out = await ExpensePlugin._finalize_expense(
        user_id=3060,
        extracted={
            "amount": 15.0,
            "currency": "SGD",
            "merchant": "Deli",
            "category": "Food",
            "date_iso": "",
            "confidence": 0.95,
            "needs_clarification": False,
        },
        source_id="test_finalize_expense_no_nameerror",
    )
    assert out.state_update["active_domain"] == "expenses"
    assert "15.00" in out.message

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
    """Outlook processed-tag hits Microsoft Graph when an OAuth token is stored."""
    from core.models import UserCredential
    from core.vault import encrypt_token
    from capabilities.email import providers as email_providers

    async with async_session_factory() as session:
        session.add(UserCredential(
            user_id=3002,
            provider="outlook",
            encrypted_token_payload=encrypt_token("fake-ms-refresh-token"),
        ))
        await session.commit()

    calls = {"patched": False, "categories_fetched": False}

    class FakeResponse:
        def __init__(self, status_code, json_data=None):
            self.status_code = status_code
            self._json = json_data or {}
        def json(self):
            return self._json

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def post(self, url, data=None, json=None):
            if "oauth2" in url and (data or {}).get("grant_type") == "refresh_token":
                return FakeResponse(200, {"access_token": "fake-access"})
            return FakeResponse(200)
        async def get(self, url, headers=None, params=None):
            if url.endswith("/messages/msg_outlook_1"):
                calls["categories_fetched"] = True
                return FakeResponse(200, {"categories": []})
            return FakeResponse(200)
        async def patch(self, url, headers=None, json=None):
            if "msg_outlook_1" in url and "Assistant/Processed" in (json or {}).get("categories", []):
                calls["patched"] = True
                return FakeResponse(200)
            return FakeResponse(404)

    monkey = MonkeyPatch()
    monkey.setattr(email_providers.httpx, "AsyncClient", FakeClient)
    try:
        assert await apply_email_processed_tag.ainvoke(
            {"user_id": 3002, "message_id": "msg_outlook_1", "provider": "outlook"}
        ) is True
        assert calls["patched"] and calls["categories_fetched"]
    finally:
        monkey.undo()

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


def test_bill_split_calculation():
    from capabilities.expenses.tools import calculate_bill_split

    items = [
        {"name": "Truffle Pasta", "price": 24.00, "quantity": 1, "assigned_to": ["Alice"]},
        {"name": "Salmon Bowl", "price": 20.00, "quantity": 1, "assigned_to": ["Bob"]},
        {"name": "Shared Fries", "price": 8.00, "quantity": 1, "assigned_to": ["Alice", "Bob"]},
        {"name": "Steak", "price": 30.00, "quantity": 1, "assigned_to": ["Me"]},
    ]
    friends = ["Alice", "Bob", "Me"]

    res = calculate_bill_split(
        items=items,
        friends=friends,
        service_charge_pct=10.0,
        tax_pct=9.0,
        discount=0.0,
    )

    friends_map = {f["name"]: f for f in res["friends"]}

    # Alice: Pasta (24) + Fries/2 (4) = 28.00 subtotal
    # Svc: 28 * 0.10 = 2.80; Tax: (28 + 2.80) * 0.09 = 2.772 -> ~33.57
    assert friends_map["Alice"]["subtotal"] == 28.00
    assert friends_map["Alice"]["total"] == pytest.approx(33.57, abs=0.05)

    # Bob: Salmon (20) + Fries/2 (4) = 24.00 subtotal
    assert friends_map["Bob"]["subtotal"] == 24.00
    assert friends_map["Bob"]["total"] == pytest.approx(28.78, abs=0.05)

    # Me: Steak (30) = 30.00 subtotal
    assert friends_map["Me"]["subtotal"] == 30.00
    assert friends_map["Me"]["total"] == pytest.approx(35.97, abs=0.05)

    # Total bill
    assert res["total_bill"] == pytest.approx(98.32, abs=0.1)


def test_bill_split_all_inclusive_total():
    """An already-settled total must not receive tax/service charges twice."""
    from capabilities.expenses.tools import calculate_bill_split

    result = calculate_bill_split(
        items=[{"name": "PLQ", "price": 37.05, "quantity": 1, "assigned_to": ["Me"]}],
        friends=["Me"],
        service_charge_pct=0.0,
        tax_pct=9.0,
        total_inclusive=True,
    )

    assert result["total_bill"] == pytest.approx(37.05, abs=0.01)
    assert result["friends"][0]["total"] == pytest.approx(37.05, abs=0.01)
    assert result["friends"][0]["tax"] == 0.0
    assert result["total_inclusive"] is True

    # The cent remainder must not disappear in an even/shared split.
    shared = calculate_bill_split(
        items=[{"name": "PLQ", "price": 37.05, "quantity": 1, "assigned_to": ["Me", "Alex"]}],
        friends=["Me", "Alex"],
        tax_pct=9.0,
        total_inclusive=True,
    )
    assert shared["total_bill"] == pytest.approx(37.05, abs=0.001)
    assert sum(p["total"] for p in shared["friends"]) == pytest.approx(37.05, abs=0.001)






@pytest.mark.asyncio
async def test_cross_source_duplicate_receipt_vs_bank_alert():
    """Merchant receipt + bank transaction alert for the SAME purchase logs once."""
    from datetime import datetime, timedelta, timezone as dt_tz
    from capabilities.expenses.tools import (
        find_cross_source_duplicate,
        save_expense_transaction,
        log_expenses_from_emails,
    )
    from capabilities.expenses.schemas import ExtractedExpense

    user_id = 8899
    now_utc = datetime.now(dt_tz.utc).replace(tzinfo=None)

    # 1. Merchant receipt email arrives first -> logged normally
    receipt_email = {
        "id": "dup_rcpt_1",
        "provider": "gmail",
        "subject": "Your receipt from Starbucks",
        "sender": "receipts@starbucks.com",
        "snippet": "Total paid: $15.00 on " + now_utc.date().isoformat(),
        "body": "Thanks for your order. Total paid: $15.00",
        "date": now_utc.isoformat() + "Z",
    }

    async def _fake_extract(user_text=None):
        return {"amount": 15.0, "currency": "SGD", "merchant": "Starbucks",
                "category": "Dining", "date_iso": "", "confidence": 0.95,
                "needs_clarification": False}

    _fake_extract.ainvoke = lambda payload: _fake_extract(payload.get("user_text", ""))

    import capabilities.expenses.tools as exp_tools
    orig_extract = exp_tools.extract_expense_from_text
    exp_tools.extract_expense_from_text = _fake_extract
    try:
        res1 = await log_expenses_from_emails.ainvoke({"user_id": user_id, "emails": [receipt_email], "notify": False})
        assert len(res1["logged"]) == 1

        # 2. Bank alert for the same purchase arrives an hour later -> deduped
        bank_alert = {
            "id": "dup_bank_1",
            "provider": "gmail",
            "subject": "Transaction alert: SGD 15.00 spent at STARBUCKS",
            "sender": "alerts@dbs.com.sg",
            "snippet": "Card ending 1234 used at STARBUCKS SINGAPORE for SGD 15.00",
            "body": "Your card ending 1234 was used at STARBUCKS SINGAPORE for SGD 15.00 on " + now_utc.date().isoformat(),
            "date": (now_utc + timedelta(hours=1)).isoformat() + "Z",
        }
        res2 = await log_expenses_from_emails.ainvoke({"user_id": user_id, "emails": [bank_alert], "notify": False})
        assert len(res2["logged"]) == 0
        assert len(res2["deduped"]) == 1
        assert res2["deduped"][0]["matched_transaction_id"] == res1["logged"][0]["transaction_id"]

        # 3. A DIFFERENT purchase, same merchant, same amount two days later -> still logs
        later_purchase = dict(receipt_email)
        later_purchase["id"] = "dup_rcpt_2"
        later_purchase["date"] = (now_utc + timedelta(days=3)).isoformat() + "Z"
        res3 = await log_expenses_from_emails.ainvoke({"user_id": user_id, "emails": [later_purchase], "notify": False})
        assert len(res3["logged"]) == 1
    finally:
        exp_tools.extract_expense_from_text = orig_extract


@pytest.mark.asyncio
async def test_outlook_oauth_flow_stores_credential(monkeypatch):
    """/auth/microsoft/callback exchanges the code and stores an outlook credential."""
    from app import auth as auth_mod

    class FakeResponse:
        def __init__(self, data):
            self._data = data
            self.status_code = 200
        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def post(self, url, data=None):
            assert "login.microsoftonline.com" in url
            assert "/consumers/" in url
            assert data.get("grant_type") == "authorization_code"
            return FakeResponse({"refresh_token": "fake-ms-refresh"})

    monkeypatch.setattr(auth_mod.httpx, "AsyncClient", FakeClient)
    resp = await auth_mod.microsoft_callback(request=None, code="abc", state="9101")
    assert "Outlook connected" in resp.body.decode()

    from capabilities.email.providers import _get_outlook_refresh_token
    stored = await _get_outlook_refresh_token(9101)
    assert stored == "fake-ms-refresh"

    # Graph search with mocked HTTP returns mapped messages
    from capabilities.email.providers import OutlookProvider
    from unittest.mock import AsyncMock

    class FakeGraphResponse:
        def __init__(self, data, status_code=200):
            self._data, self.status_code = data, status_code
        def json(self):
            return self._data

    class FakeGraphClient(FakeClient):
        async def post(self, url, data=None):
            if data and data.get("grant_type") == "refresh_token":
                return FakeGraphResponse({"access_token": "fake-graph-token"})
            return FakeGraphResponse({})
        async def get(self, url, headers=None, params=None):
            if url.endswith("/messages"):
                return FakeGraphResponse({"value": [{
                    "id": "msgraph-1",
                    "subject": "Receipt from Uniqlo",
                    "from": {"emailAddress": {"name": "Uniqlo", "address": "no-reply@uniqlo.com"}},
                    "body": {"content": "<html><body>Total paid: $59.90</body></html>"},
                    "receivedDateTime": "2026-08-20T10:00:00Z",
                    "categories": [],
                }]})
            return FakeGraphResponse({})

    from capabilities.email import providers as ep
    monkeypatch.setattr(ep.httpx, "AsyncClient", FakeGraphClient)
    msgs = await OutlookProvider().search_messages(user_id=9101, tracked_banks=[])
    assert len(msgs) == 1
    assert msgs[0]["id"] == "msgraph-1"
    assert msgs[0]["provider"] == "outlook"
    assert "Total paid: $59.90" in msgs[0]["body"]


@pytest.mark.asyncio
async def test_outlook_latest_mode_fetches_newest_first(monkeypatch: MonkeyPatch):
    """Latest-email mode must query Graph for newest messages WITHOUT a financial query."""
    from core.models import UserCredential
    from core.vault import encrypt_token
    from capabilities.email import providers as ep
    from capabilities.email.providers import OutlookProvider

    user_id = 9312
    async with async_session_factory() as session:
        session.add(UserCredential(
            user_id=user_id,
            provider="outlook",
            encrypted_token_payload=encrypt_token("fake-ms-refresh-token"),
        ))
        await session.commit()

    seen_params: dict = {}

    class FakeResp:
        def __init__(self, data, status_code=200):
            self._data, self.status_code = data, status_code
        def json(self):
            return self._data

    class LatestGraphClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def post(self, url, data=None):
            if data and data.get("grant_type") == "refresh_token":
                return FakeResp({"access_token": "fake-graph-token"})
            return FakeResp({})
        async def get(self, url, headers=None, params=None):
            if url.endswith("/messages"):
                seen_params.update(params or {})
                return FakeResp({"value": [{
                    "id": "msgraph-latest-1",
                    "subject": "Catchup from Alice",
                    "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                    "body": {"content": "Hi!"},
                    "receivedDateTime": "2026-08-24T09:00:00Z",
                    "categories": [],
                }]})
            return FakeResp({})

    monkeypatch.setattr(ep.httpx, "AsyncClient", LatestGraphClient)
    msgs = await OutlookProvider().search_messages(user_id=user_id, tracked_banks=[], latest=True)
    assert msgs[0]["subject"] == "Catchup from Alice"
    assert msgs[0]["provider"] == "outlook"
    assert "$search" not in seen_params
    assert "$filter" not in seen_params
    assert seen_params.get("$orderby") == "receivedDateTime desc"


def test_merge_sorts_messages_newest_first():
    from capabilities.email.tools import _sort_messages_newest_first
    msgs = [
        {"id": "old", "date": "2026-08-01T10:00:00Z"},
        {"id": "no-date", "date": ""},
        {"id": "newest", "date": "2026-08-24T09:00:00Z"},
        {"id": "mid", "date": "Mon, 10 Aug 2026 12:00:00 +0800"},
    ]
    ordered = [m["id"] for m in _sort_messages_newest_first(msgs)]
    assert ordered == ["newest", "mid", "old", "no-date"]


@pytest.mark.asyncio
async def test_disconnect_email_provider_and_all(monkeypatch):
    """Disconnect removes only the requested provider, or every mailbox for all."""
    from unittest.mock import AsyncMock
    from core.models import UserCredential, UserProfile
    from core.vault import encrypt_token
    import capabilities.email.tools as email_tools

    user_id = 9211
    async with async_session_factory() as session:
        session.add(UserProfile(user_id=user_id, telegram_chat_id=19211, current_timezone="UTC"))
        session.add_all([
            UserCredential(user_id=user_id, provider="gmail", encrypted_token_payload=encrypt_token("gmail-refresh")),
            UserCredential(user_id=user_id, provider="outlook", encrypted_token_payload=encrypt_token("outlook-refresh")),
        ])
        await session.commit()

    revoke = AsyncMock(return_value=True)
    monkeypatch.setattr(email_tools, "_revoke_gmail_token", revoke)

    outlook_result = await email_tools.disconnect_email_account(user_id, "outlook")
    assert outlook_result["disconnected"] == ["outlook"]
    assert outlook_result["count"] == 1
    revoke.assert_not_awaited()

    async with async_session_factory() as session:
        remaining = (await session.execute(
            select(UserCredential).where(UserCredential.user_id == user_id)
        )).scalars().all()
        assert [credential.provider for credential in remaining] == ["gmail"]

    all_result = await email_tools.disconnect_email_account(user_id, "all")
    assert all_result["disconnected"] == ["gmail"]
    assert all_result["gmail_tokens_revoked"] == 1
    revoke.assert_awaited_once_with("gmail-refresh")

    invalid = await email_tools.disconnect_email_account(user_id, "yahoo")
    assert invalid["status"] == "invalid_provider"

    async with async_session_factory() as session:
        assert not (await session.execute(
            select(UserCredential).where(UserCredential.user_id == user_id)
        )).scalars().all()


def test_reconcile_expense_date_guards_against_wrong_years():
    """LLM-invented years (2022/2023) snap back to the email's real receive time."""
    from datetime import datetime
    from capabilities.expenses.tools import _reconcile_expense_date

    anchor = datetime(2026, 8, 22, 19, 16, 0)
    wrong_year = datetime(2023, 8, 22, 0, 0, 0)
    result = _reconcile_expense_date(wrong_year, anchor)
    assert result == anchor  # 3 years off -> trust the anchor

    wrong_year_full = datetime(2022, 8, 26, 21, 33, 37)
    assert _reconcile_expense_date(wrong_year_full, anchor) == anchor


def test_reconcile_expense_date_date_only_adopts_email_time():
    """Date-only extractions don't surface as 00:00 midnight rows."""
    from datetime import datetime
    from capabilities.expenses.tools import _reconcile_expense_date

    anchor = datetime(2026, 8, 22, 14, 25, 0)
    date_only = datetime(2026, 8, 22, 0, 0, 0)
    result = _reconcile_expense_date(date_only, anchor)
    assert result == datetime(2026, 8, 22, 14, 25, 0)

    # A sane full timestamp within the window is respected exactly
    exact = datetime(2026, 8, 22, 11, 2, 33)
    assert _reconcile_expense_date(exact, anchor) == exact


def test_reconcile_expense_date_no_extraction_uses_anchor():
    from datetime import datetime
    from capabilities.expenses.tools import _reconcile_expense_date

    anchor = datetime(2026, 8, 22, 8, 0, 0)
    assert _reconcile_expense_date(None, anchor) == anchor


def test_gmail_provider_prefers_internal_date(monkeypatch):
    """internalDate wins over the spoofable Date header."""
    import capabilities.email.providers as ep
    from core.models import UserCredential
    from core.vault import encrypt_token
    import asyncio

    async def _seed_token():
        async with async_session_factory() as session:
            session.add(UserCredential(
                user_id=3311, provider="gmail",
                encrypted_token_payload=encrypt_token("fake-gmail-refresh"),
            ))
            await session.commit()

    asyncio.run(_seed_token())

    class FakeResp:
        def __init__(self, data, status=200):
            self._data, self.status_code = data, status
        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def post(self, url, data=None):
            assert data.get("grant_type") == "refresh_token"
            return FakeResp({"access_token": "acc"})
        async def get(self, url, headers=None, params=None):
            if url.endswith("/messages"):
                return FakeResp({"messages": [{"id": "m1"}]})
            if "/messages/m1" in url:
                return FakeResp({
                    "internalDate": "1755874560000",  # real receive time
                    "payload": {
                        "headers": [
                            {"name": "Date", "value": "Sat, 22 Aug 2020 03:00:00 +0000"},
                            {"name": "From", "value": "receipts@x.com"},
                            {"name": "Subject", "value": "receipt"},
                        ],
                        "body": {"data": ""},
                    },
                })
            return FakeResp({})

    monkeypatch.setattr(ep.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(ep.settings, "google_client_id", "cid")

    provider = ep.GmailProvider()
    msgs = asyncio.run(provider.search_messages(user_id=3311, tracked_banks=[]))
    assert len(msgs) == 1
    # 1755874560000 ms = 2025-08-22T14:56:00Z — must NOT be the 2020 header date
    assert msgs[0]["date"].startswith("2025-08-22T14:56:00")


@pytest.mark.asyncio
async def test_daily_email_digest_consolidates_and_is_idempotent(monkeypatch):
    """Polling can run often, but Telegram receives one digest per local day."""
    from datetime import datetime, timezone as dt_timezone
    from core.models import ExpenseTransaction, UserProfile
    from core.scheduler import _send_daily_email_expense_digest

    user_id = 9951
    async with async_session_factory() as session:
        session.add(UserProfile(
            user_id=user_id,
            telegram_chat_id=19951,
            current_timezone="Asia/Singapore",
        ))
        session.add_all([
            # Historical rows have no ingestion timestamp and must not appear
            # in the first digest after this feature is deployed.
            ExpenseTransaction(
                user_id=user_id,
                amount=4.0,
                currency="SGD",
                merchant="Old Row",
                category="General",
                date=datetime(2026, 8, 1, 10, 0),
                logged_at=None,
            ),
            ExpenseTransaction(
                user_id=user_id,
                amount=105.50,
                currency="USD",
                merchant="OpenRouter, Inc",
                category="Software/Saas",
                date=datetime(2026, 8, 22, 15, 48, 37),
                logged_at=datetime(2026, 8, 23, 0, 48, 37),
            ),
            ExpenseTransaction(
                user_id=user_id,
                amount=28.99,
                currency="SGD",
                merchant="Google Play",
                category="Bills",
                date=datetime(2026, 8, 22, 17, 31, 9),
                logged_at=datetime(2026, 8, 23, 0, 58, 9),
            ),
        ])
        await session.commit()

    sent = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append((chat_id, text, reply_markup))
        return True

    monkeypatch.setattr("app.ingress.send_telegram_message", fake_send)
    nine_am_sgt = datetime(2026, 8, 23, 1, 5, tzinfo=dt_timezone.utc)

    assert await _send_daily_email_expense_digest(user_id, nine_am_sgt) is True
    assert len(sent) == 1
    assert "Daily expense digest" in sent[0][1]
    assert "OpenRouter, Inc" in sent[0][1]
    assert "Google Play" in sent[0][1]
    assert "Old Row" not in sent[0][1]

    # Same local day: no second Telegram message.
    assert await _send_daily_email_expense_digest(
        user_id,
        datetime(2026, 8, 23, 2, 0, tzinfo=dt_timezone.utc),
    ) is False
    assert len(sent) == 1

    async with async_session_factory() as session:
        profile = (await session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        )).scalar_one()
        assert profile.last_email_digest_at is not None


@pytest.mark.asyncio
async def test_daily_email_digest_respects_quiet_hours(monkeypatch):
    """A pre-09:00 local poll never sends a routine email summary."""
    from datetime import datetime, timezone as dt_timezone
    from core.models import ExpenseTransaction, UserProfile
    from core.scheduler import _send_daily_email_expense_digest

    user_id = 9952
    async with async_session_factory() as session:
        session.add(UserProfile(
            user_id=user_id,
            telegram_chat_id=19952,
            current_timezone="Asia/Singapore",
        ))
        session.add(ExpenseTransaction(
            user_id=user_id,
            amount=12.0,
            currency="SGD",
            merchant="Early Purchase",
            category="General",
            date=datetime(2026, 8, 23, 0, 30),
            logged_at=datetime(2026, 8, 23, 0, 40),
        ))
        await session.commit()

    sent = []

    async def fake_send(chat_id, text, reply_markup=None):
        sent.append(text)
        return True

    monkeypatch.setattr("app.ingress.send_telegram_message", fake_send)
    eight_am_sgt = datetime(2026, 8, 23, 0, 0, tzinfo=dt_timezone.utc)
    assert await _send_daily_email_expense_digest(user_id, eight_am_sgt) is False
    assert sent == []
