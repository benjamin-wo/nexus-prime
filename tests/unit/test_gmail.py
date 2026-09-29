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
from nexus.infra.email.gmail import READ_SCOPE, GmailMailbox, body_text, html_text


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


def test_html_text_survives_an_unclosed_head() -> None:
    markup = "<html><head><title>Receipt</title><body><p>Total</p><p>$12.00</p></body>"
    assert html_text(markup) == "Total\n$12.00"


def _part(mime: str, text: str, charset: str = "utf-8", **extra: Any) -> dict[str, Any]:
    return {
        "mimeType": mime,
        "headers": [{"name": "Content-Type", "value": f'{mime}; charset="{charset}"'}],
        "body": {"data": b64(text.encode(charset))},
        **extra,
    }


def test_a_stub_plain_part_loses_to_the_real_html_one() -> None:
    parts = [
        _part("text/plain", "View this email in your browser."),
        _part("text/html", "<table><tr><td>Order total</td><td>SGD 42.10</td></tr></table>"),
    ]
    assert body_text(parts, "snippet") == "Order total SGD 42.10"


def test_a_full_plain_part_is_kept() -> None:
    parts = [
        _part("text/plain", "Thanks for your order. Order total: SGD 42.10. Paid by Visa."),
        _part("text/html", "<p>Thanks</p>"),
    ]
    assert body_text(parts, "snippet").startswith("Thanks for your order")


def test_body_text_honours_the_charset_and_skips_attachments() -> None:
    parts = [
        _part("text/plain", "Total payé: 12,50 EUR", charset="iso-8859-1"),
        _part("text/html", "<p>" + "attached " * 50 + "</p>", filename="terms.html"),
    ]
    assert body_text(parts, "snippet") == "Total payé: 12,50 EUR"


def test_an_empty_body_falls_back_to_the_snippet() -> None:
    assert body_text([], "Your total is $5") == "Your total is $5"


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
