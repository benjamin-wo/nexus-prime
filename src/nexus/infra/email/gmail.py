"""Gmail over its REST API with plain HTTP: OAuth, search, fetch and revoke.

Read-only access (gmail.readonly). Only messages matching the receipt query are
listed, and only those are fetched.
"""

import base64
import html
import re
from datetime import UTC, datetime
from email.utils import parseaddr
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode

import httpx

from nexus.application.ports import MailboxGrant, MailboxRevoked
from nexus.domain.email import FetchedEmail
from nexus.domain.errors import InvalidInput
from nexus.domain.receipts import MAX_BYTES

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
MAX_TEXT = 8000
MAX_LISTED = 200


_HIDDEN = frozenset({"script", "style", "head", "title"})


class _Text(HTMLParser):
    """The visible text of an HTML email."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self._skip = 0  # a <head> left unclosed must not hide the whole email
        elif tag in _HIDDEN:
            self._skip += 1
        elif tag in {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "td"}:
            self.parts.append("\n" if tag != "td" else " ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_text(markup: str) -> str:
    parser = _Text()
    parser.feed(markup)
    text = html.unescape("".join(parser.parts))
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\xa0]+", " ", text)).strip()


def _decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _charset(part: dict[str, Any]) -> str:
    match = re.search(r'charset="?([\w.:-]+)', _header(part, "content-type"), re.IGNORECASE)
    return match.group(1) if match else "utf-8"


def _part_text(part: dict[str, Any]) -> str:
    raw = _decode(part["body"]["data"])
    try:
        text = raw.decode(_charset(part), errors="replace")
    except LookupError:  # a charset Python doesn't know
        text = raw.decode(errors="replace")
    return html_text(text) if part.get("mimeType") == "text/html" else text.strip()


def _richness(text: str) -> tuple[bool, int]:
    # A part with figures in it beats one without; then the longer one wins.
    return any(c.isdigit() for c in text), len(text.split())


def body_text(parts: list[dict[str, Any]], snippet: str) -> str:
    """The email's readable text. Many receipts carry a stub plain-text part ("view
    this email in your browser") next to the real HTML one, so the part that has
    figures in it, then the longer one, is kept rather than always the plain one."""
    found = [
        _part_text(p)
        for p in parts
        if p.get("mimeType") in ("text/plain", "text/html")
        and (p.get("body") or {}).get("data")
        and not (p.get("filename") or "")  # an attached .txt or .html isn't the body
    ]
    return max(found, key=_richness, default="") or snippet


def _walk(part: dict[str, Any]) -> list[dict[str, Any]]:
    found = [part]
    for child in part.get("parts") or []:
        found += _walk(child)
    return found


def _header(payload: dict[str, Any], name: str) -> str:
    for header in payload.get("headers") or []:
        if str(header.get("name", "")).lower() == name:
            return str(header.get("value", ""))
    return ""


class GmailMailbox:
    def __init__(self, http: httpx.AsyncClient, *, client_id: str, client_secret: str) -> None:
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        return f"{AUTH_URL}?" + urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": READ_SCOPE,
                "access_type": "offline",
                "prompt": "consent",  # always hand back a refresh token
                "state": state,
            }
        )

    async def exchange(self, code: str, *, redirect_uri: str) -> MailboxGrant:
        response = await self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if response.status_code != 200:
            raise InvalidInput("Google didn't accept that sign-in; please try again")
        body = response.json()
        if READ_SCOPE not in str(body.get("scope", "")).split() or not body.get("refresh_token"):
            raise InvalidInput("Nexus needs permission to read your email to find receipts")
        profile = await self._get(str(body["access_token"]), "/profile")
        return MailboxGrant(str(profile["emailAddress"]).lower(), str(body["refresh_token"]))

    async def access_token(self, refresh_token: str) -> str:
        response = await self._http.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        if response.status_code in (400, 401) and "invalid_grant" in response.text:
            raise MailboxRevoked("Google no longer accepts this connection")
        response.raise_for_status()
        return str(response.json()["access_token"])

    async def _get(self, token: str, path: str, **params: Any) -> dict[str, Any]:
        response = await self._http.get(
            API + path, params=params, headers={"Authorization": f"Bearer {token}"}
        )
        if response.status_code == 401:
            raise MailboxRevoked("Google no longer accepts this connection")
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    async def search(self, access_token: str, query: str, *, after: datetime) -> list[str]:
        q = f"{query} after:{int(after.timestamp())}"
        ids: list[str] = []
        page: str | None = None
        while len(ids) < MAX_LISTED:
            params: dict[str, Any] = {"q": q, "maxResults": 100}
            if page:
                params["pageToken"] = page
            data = await self._get(access_token, "/messages", **params)
            ids += [str(m["id"]) for m in data.get("messages") or []]
            page = data.get("nextPageToken")
            if not page:
                break
        return ids[:MAX_LISTED]

    async def fetch(self, access_token: str, message_id: str) -> FetchedEmail:
        data = await self._get(access_token, f"/messages/{message_id}", format="full")
        payload = data.get("payload") or {}
        parts = _walk(payload)
        text = body_text(parts, html.unescape(str(data.get("snippet", ""))))
        pdf = None
        for part in parts:
            body = part.get("body") or {}
            if part.get("mimeType") == "application/pdf" and body.get("attachmentId"):
                if int(body.get("size", 0)) <= MAX_BYTES:
                    attachment = await self._get(
                        access_token, f"/messages/{message_id}/attachments/{body['attachmentId']}"
                    )
                    pdf = _decode(str(attachment["data"]))
                break
        name, address = parseaddr(_header(payload, "from"))
        return FetchedEmail(
            provider_message_id=message_id,
            received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, UTC),
            sender=address.lower() or name,
            subject=_header(payload, "subject")[:300],
            text=text[:MAX_TEXT],
            pdf=pdf,
        )

    async def revoke(self, refresh_token: str) -> None:
        await self._http.post(REVOKE_URL, data={"token": refresh_token})
