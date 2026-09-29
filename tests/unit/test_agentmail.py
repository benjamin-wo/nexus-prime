import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest

from nexus.application.ports import MailboxRevoked
from nexus.domain.email import (
    ConnectionStatus,
    EmailConnection,
    FetchedEmail,
    Provider,
    forwarding_notice,
    is_test_email,
    needs_nudge,
)
from nexus.domain.ledger import UserId
from nexus.infra.email.agentmail import AgentMailInboxes

NOW = datetime(2026, 9, 28, 4, 0, tzinfo=UTC)


def inboxes(handler: Any) -> AgentMailInboxes:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AgentMailInboxes(http, api_key="am_test", domain=None)


async def test_an_inbox_per_user_with_an_unguessable_name() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"inbox_id": "ibx_1", "email": f"{body['username']}@AgentMail.to"}
        )

    inbox, address = await inboxes(handler).create_inbox("user-1")
    [request] = seen
    body = json.loads(request.content)
    assert request.url == "https://api.agentmail.to/v0/inboxes"
    assert request.headers["Authorization"] == "Bearer am_test"
    assert body["client_id"] == "nexus-user-1"  # a retried create returns the same inbox
    assert body["username"].startswith("nexus-") and len(body["username"]) == 18
    assert "domain" not in body
    assert inbox == "ibx_1" and address == body["username"] + "@agentmail.to"


async def test_search_pages_oldest_first_and_skips_sent_mail() -> None:
    pages = {
        None: {"messages": [{"message_id": "m1", "labels": ["received"]}], "next_page_token": "p2"},
        "p2": {"messages": [{"message_id": "m2", "labels": ["sent"]}, {"message_id": "m3"}]},
    }
    asked: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.params)
        return httpx.Response(200, json=pages[request.url.params.get("page_token")])

    after = datetime(2026, 9, 1, tzinfo=UTC)
    assert await inboxes(handler).search("ibx_1", "ignored", after=after) == ["m1", "m3"]
    assert asked[0]["after"] == after.isoformat() and asked[0]["ascending"] == "true"
    assert asked[1]["page_token"] == "p2"


async def test_fetch_keeps_the_forwarded_part_and_the_pdf() -> None:
    message = {
        "timestamp": "2026-09-27T09:30:00Z",
        "from": "Ann <ANN@outlook.com>",
        "subject": "Fwd: Your receipt",
        "text": "FYI",
        "html": "<p>FYI</p><blockquote><p>Total paid</p><p>SGD 42.10</p></blockquote>",
        "attachments": [
            {"attachment_id": "a1", "content_type": "application/pdf", "size": 8},
        ],
    }
    auth: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        auth[request.url.host] = request.headers.get("Authorization")
        if request.url.host == "files.test":
            return httpx.Response(200, content=b"%PDF-1.7")
        if request.url.path.endswith("/attachments/a1"):
            return httpx.Response(200, json={"download_url": "https://files.test/a1?sig=x"})
        return httpx.Response(200, json=message)

    email = await inboxes(handler).fetch("ibx_1", "m1")
    assert email.sender == "ann@outlook.com"
    assert email.text == "FYI\nTotal paid\nSGD 42.10"  # the fuller HTML, quoted part and all
    assert email.pdf == b"%PDF-1.7"
    assert email.received_at == datetime(2026, 9, 27, 9, 30, tzinfo=UTC)
    assert auth["files.test"] is None  # our API key never goes to the download host


async def test_a_deleted_inbox_is_reported_and_deleting_twice_is_fine() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    with pytest.raises(MailboxRevoked):
        await inboxes(handler).search("gone", "", after=NOW)
    await inboxes(handler).revoke("gone")


def email(sender: str, subject: str, text: str = "") -> FetchedEmail:
    return FetchedEmail("m1", NOW, sender, subject, text)


def test_gmail_forwarding_confirmations_are_passed_on() -> None:
    notice = forwarding_notice(
        email(
            "forwarding-noreply@google.com",
            "(#123456789) Gmail Forwarding Confirmation - Receive Mail from ann@gmail.com",
            "To allow, click https://mail-settings.google.com/mail/vf-abc123 or "
            "visit https://evil.test/phish",
        )
    )
    assert notice is not None
    assert notice.code == "123456789"
    assert notice.link == "https://mail-settings.google.com/mail/vf-abc123"


@pytest.mark.parametrize(
    ("sender", "subject", "text"),
    [
        ("forwarding-noreply@google.com.evil.test", "Forwarding Confirmation", ""),
        ("alerts@bank.test", "Please confirm your forwarding", ""),
        ("no-reply@google.com", "Your Google Play receipt", ""),
    ],
)
def test_lookalikes_and_ordinary_mail_are_not(sender: str, subject: str, text: str) -> None:
    assert forwarding_notice(email(sender, subject, text)) is None


def test_a_provider_link_elsewhere_is_dropped() -> None:
    notice = forwarding_notice(
        email("noreply@microsoft.com", "Verify forwarding", "Go to https://evil.test/x")
    )
    assert notice is not None and notice.link is None


def test_test_emails_are_recognised() -> None:
    assert is_test_email(email("ann@outlook.com", "Nexus test receipt"))
    assert is_test_email(email("ann@outlook.com", "FW: nexus TEST"))
    assert not is_test_email(email("ann@outlook.com", "Your receipt"))


def connection(**changes: Any) -> EmailConnection:
    base: dict[str, Any] = {
        "id": uuid4(),
        "user_id": UserId(uuid4()),
        "provider": Provider.FORWARD,
        "address": "nexus-x@agentmail.test",
        "token": b"",
        "status": ConnectionStatus.ACTIVE,
        "synced_until": NOW,
        "created_at": NOW - timedelta(days=30),
        "updated_at": NOW,
    }
    return EmailConnection(**{**base, **changes})


def test_a_quiet_forwarding_address_is_nudged_once_per_quiet_spell() -> None:
    later = NOW + timedelta(days=1)
    assert needs_nudge(connection(last_received_at=NOW - timedelta(days=14)), NOW)
    assert not needs_nudge(connection(last_received_at=NOW - timedelta(days=13)), NOW)
    assert needs_nudge(connection(), NOW)  # nothing ever arrived since it was made
    nudged = connection(last_received_at=NOW - timedelta(days=20), nudged_at=NOW)
    assert not needs_nudge(nudged, later)
    # Mail arrived after the nudge, then went quiet again: nudge again.
    again = connection(last_received_at=later, nudged_at=NOW)
    assert needs_nudge(again, later + timedelta(days=14))
    assert not needs_nudge(connection(provider=Provider.GMAIL), NOW)
    assert not needs_nudge(connection(status=ConnectionStatus.BROKEN), NOW)
