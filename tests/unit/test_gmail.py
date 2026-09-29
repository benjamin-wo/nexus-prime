import base64
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from nexus.agent.service import Button
from nexus.application.ports import MailboxRevoked
from nexus.channels.telegram.client import keyboard
from nexus.domain.errors import InvalidInput
from nexus.infra.email.gmail import READ_SCOPE, GmailMailbox, html_text


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def mailbox(handler: Any) -> GmailMailbox:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GmailMailbox(http, client_id="cid", client_secret="secret")


def test_consent_asks_for_read_only_offline_access() -> None:
    url = urlparse(mailbox(lambda r: None).authorize_url(state="tok", redirect_uri="https://n/cb"))
    query = parse_qs(url.query)
    assert query["scope"] == [READ_SCOPE]
    assert query["access_type"] == ["offline"] and query["prompt"] == ["consent"]
    assert query["state"] == ["tok"] and query["redirect_uri"] == ["https://n/cb"]


async def test_exchange_needs_the_read_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            scope = "openid" if b"code=bad" in request.content else READ_SCOPE
            return httpx.Response(
                200, json={"access_token": "a", "refresh_token": "r", "scope": scope}
            )
        assert request.headers["Authorization"] == "Bearer a"
        return httpx.Response(200, json={"emailAddress": "Ann@Gmail.com"})

    box = mailbox(handler)
    grant = await box.exchange("good", redirect_uri="x")
    assert (grant.address, grant.refresh_token) == ("ann@gmail.com", "r")
    with pytest.raises(InvalidInput, match="permission"):
        await box.exchange("bad", redirect_uri="x")


async def test_a_revoked_grant_is_reported() -> None:
    box = mailbox(lambda r: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(MailboxRevoked):
        await box.access_token("r")


async def test_search_pages_and_scopes_by_date() -> None:
    seen: list[dict[str, list[str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlparse(str(request.url)).query)
        seen.append(query)
        if "pageToken" in query:
            return httpx.Response(200, json={"messages": [{"id": "c"}]})
        return httpx.Response(
            200, json={"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "p"}
        )

    ids = await mailbox(handler).search(
        "a", "subject:receipt", after=datetime(2026, 9, 1, tzinfo=UTC)
    )
    assert ids == ["a", "b", "c"]
    assert seen[0]["q"] == ["subject:receipt after:1788220800"]


async def test_fetch_reads_html_and_the_pdf() -> None:
    html = (
        b"<html><head><style>x{}</style></head>"
        b"<body><p>Total&nbsp;paid:</p><td>SGD 18.50</td></body></html>"
    )
    message = {
        "internalDate": "1790568000000",
        "payload": {
            "headers": [
                {"name": "From", "value": "Grab <No-Reply@Grab.com>"},
                {"name": "Subject", "value": "Your Grab E-Receipt"},
            ],
            "parts": [
                {"mimeType": "text/html", "body": {"data": b64(html)}},
                {"mimeType": "application/pdf", "body": {"attachmentId": "att1", "size": 8}},
            ],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/attachments/att1"):
            return httpx.Response(200, content=json.dumps({"data": b64(b"%PDF-1.7")}))
        return httpx.Response(200, json=message)

    email = await mailbox(handler).fetch("a", "m1")
    assert email.sender == "no-reply@grab.com"
    assert email.subject == "Your Grab E-Receipt"
    assert email.text == "Total paid: SGD 18.50"
    assert email.pdf == b"%PDF-1.7"
    assert email.received_at == datetime.fromtimestamp(1790568000, UTC)


def test_html_text_skips_scripts_and_styles() -> None:
    assert html_text("<script>alert(1)</script><b>Paid</b> &amp; done") == "Paid & done"


def test_url_buttons_open_links_in_telegram() -> None:
    rows = keyboard(
        [[Button("Connect Gmail", "url:https://n/connect"), Button("Skip", "email:skip:1")]]
    )
    assert rows == {
        "inline_keyboard": [
            [
                {"text": "Connect Gmail", "url": "https://n/connect"},
                {"text": "Skip", "callback_data": "email:skip:1"},
            ]
        ]
    }
