"""Forwarding addresses on AgentMail, over its REST API with plain HTTP.

Each user who asks gets their own inbox with an unguessable address. They forward
receipts to it (by hand, or with a rule in their mail app), and the sweep reads
what arrives. AgentMail leaves out spam and mail that fails sender checks.
"""

import secrets
from datetime import datetime
from email.utils import parseaddr
from typing import Any

import httpx

from nexus.application.ports import MailboxRevoked
from nexus.domain.email import FetchedEmail
from nexus.domain.receipts import MAX_BYTES
from nexus.infra.email.gmail import MAX_TEXT, html_text

API = "https://api.agentmail.to/v0"
MAX_LISTED = 200


def _pick_text(message: dict[str, Any]) -> str:
    """The full text, quoted part included: in a forwarded email the receipt is the
    quoted part. The HTML is used when it says more."""
    plain = str(message.get("text") or "").strip()
    markup = html_text(str(message.get("html") or ""))

    def richness(text: str) -> tuple[bool, int]:
        return any(c.isdigit() for c in text), len(text.split())

    return max((plain, markup), key=richness) or str(message.get("preview") or "")


class AgentMailInboxes:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str, domain: str | None = None):
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._domain = domain

    async def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = await self._http.request(method, API + path, headers=self._headers, **kwargs)
        if response.status_code == 404:
            raise MailboxRevoked("this forwarding address no longer exists")
        response.raise_for_status()
        return response

    async def create_inbox(self, owner: str) -> tuple[str, str]:
        """A new inbox for ``owner`` (an opaque id). Returns (inbox id, address)."""
        body: dict[str, Any] = {
            "username": f"nexus-{secrets.token_hex(6)}",
            "display_name": "Nexus receipts",
            "client_id": f"nexus-{owner}",  # makes a retried create return the same inbox
        }
        if self._domain:
            body["domain"] = self._domain
        data = (await self._call("POST", "/inboxes", json=body)).json()
        return str(data["inbox_id"]), str(data["email"]).lower()

    # --- the Mailbox port: the "token" is the inbox id -----------------------------

    async def access_token(self, refresh_token: str) -> str:
        return refresh_token

    async def search(self, access_token: str, query: str, *, after: datetime) -> list[str]:
        """Every message received after ``after``, oldest first. ``query`` is unused:
        the user's own forwarding rule decides what arrives."""
        ids: list[str] = []
        page: str | None = None
        while len(ids) < MAX_LISTED:
            params: dict[str, Any] = {"after": after.isoformat(), "ascending": "true", "limit": 100}
            if page:
                params["page_token"] = page
            data = (
                await self._call("GET", f"/inboxes/{access_token}/messages", params=params)
            ).json()
            for m in data.get("messages") or []:
                if "sent" not in (m.get("labels") or []):
                    ids.append(str(m["message_id"]))
            page = data.get("next_page_token")
            if not page:
                break
        return ids[:MAX_LISTED]

    async def fetch(self, access_token: str, message_id: str) -> FetchedEmail:
        path = f"/inboxes/{access_token}/messages/{message_id}"
        message = (await self._call("GET", path)).json()
        pdf = None
        for attachment in message.get("attachments") or []:
            is_pdf = str(attachment.get("content_type", "")).startswith("application/pdf")
            if is_pdf and int(attachment.get("size", 0)) <= MAX_BYTES:
                found = await self._call("GET", f"{path}/attachments/{attachment['attachment_id']}")
                # A presigned link on another host: fetched without our API key.
                download = await self._http.get(str(found.json()["download_url"]))
                download.raise_for_status()
                pdf = download.content
                break
        name, address = parseaddr(str(message.get("from") or ""))
        return FetchedEmail(
            provider_message_id=message_id,
            received_at=datetime.fromisoformat(str(message["timestamp"])),
            sender=address.lower() or name,
            subject=str(message.get("subject") or "")[:300],
            text=_pick_text(message)[:MAX_TEXT],
            pdf=pdf,
        )

    async def revoke(self, refresh_token: str) -> None:
        """Delete the inbox: the address stops accepting mail."""
        try:
            await self._call("DELETE", f"/inboxes/{refresh_token}")
        except MailboxRevoked:
            pass  # already gone
