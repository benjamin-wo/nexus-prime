"""Connect Gmail, and the Email page's API.

Connecting runs in whatever browser opens the link, often the phone's browser
from a Telegram button, where there's no Nexus session. So it's authorised by a
one-time link instead:

    POST /api/email/link          (signed in) -> a link valid for 10 minutes, once
    GET  /connect/gmail?t=...     (web app page) says whose account it will join
    GET  /api/email/gmail/start   -> Google's consent screen
    GET  /api/email/gmail/callback -> spends the link, saves the encrypted grant
"""

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from nexus.application import email as email_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.email import EmailRuntime
from nexus.application.users import get_user
from nexus.channels.web.security import Auth, Runtime, WebRuntime
from nexus.domain.email import ACTIONABLE, EmailStatus, ExpenseDraft
from nexus.domain.errors import NexusError, NotFound
from nexus.domain.money import Money
from nexus.jobs.handlers import EMAIL_SWEEP

router = APIRouter(prefix="/api/email")


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _email(web: WebRuntime) -> EmailRuntime:
    if web.email is None:
        raise NotFound("connecting email isn't set up on this server")
    return web.email


class LinkOut(Model):
    url: str


@router.post("/link")
async def link(auth: Auth, web: Runtime) -> LinkOut:
    email = _email(web)
    token = await email_cases.create_link(web.uow(), auth.user, now=web.clock())
    return LinkOut(url=email.connect_url(token))


class LinkCheckOut(Model):
    valid: bool
    account_hint: str | None  # the end of the Nexus account's Telegram id


@router.get("/link")
async def check_link(web: Runtime, t: Annotated[str, Query(max_length=100)]) -> LinkCheckOut:
    """For the connect page, before any session exists: is this link still good, and
    whose account will the mailbox join? (So nobody connects theirs to a stranger's.)"""
    owner = await email_cases.link_owner(web.uow(), t, now=web.clock())
    if owner is None:
        return LinkCheckOut(valid=False, account_hint=None)
    user = await get_user(web.uow(), owner)
    return LinkCheckOut(valid=True, account_hint=str(user.telegram_user_id)[-4:])


@router.get("/gmail/start", include_in_schema=False)
async def start(web: Runtime, t: Annotated[str, Query(max_length=100)]) -> RedirectResponse:
    email = _email(web)
    if await email_cases.link_owner(web.uow(), t, now=web.clock()) is None:
        return RedirectResponse("/connect/gmail/done?error=expired", status_code=303)
    url = email.mailbox.authorize_url(state=t, redirect_uri=email.redirect_uri)
    return RedirectResponse(url, status_code=303)


@router.get("/gmail/callback", include_in_schema=False)
async def callback(
    web: Runtime,
    state: Annotated[str, Query(max_length=100)] = "",
    code: Annotated[str | None, Query(max_length=2000)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> RedirectResponse:
    email = _email(web)
    if error or not code:
        return RedirectResponse("/connect/gmail/done?error=declined", status_code=303)
    now = web.clock()
    try:
        connection = await email_cases.finish_connect(
            web.uow,
            email.mailbox,
            email.cipher,
            token=state,
            code=code,
            redirect_uri=email.redirect_uri,
            now=now,
        )
    except NotFound:
        return RedirectResponse("/connect/gmail/done?error=expired", status_code=303)
    except NexusError:
        return RedirectResponse("/connect/gmail/done?error=permission", status_code=303)
    async with web.uow() as tx:
        # Tell the user first; the look-back sweep follows a moment later (jobs run in
        # order of run_at, so a slow sweep can't hold up this message).
        await tx.jobs.enqueue(
            EMAIL_SWEEP,
            {},
            dedupe_key=f"email.connected:{connection.id}:{now}",
            run_at=now + timedelta(seconds=10),
        )
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {
                "user_id": str(connection.user_id),
                "text": f"✅ Connected {connection.address}. I'm looking for receipts from "
                "the last 30 days now. Nothing is logged until you confirm it.",
            },
            dedupe_key=f"email.connected.tell:{connection.id}:{now}",
            run_at=now,
        )
        await tx.commit()
    return RedirectResponse("/connect/gmail/done?ok=1", status_code=303)


# --- the Email page -----------------------------------------------------------------


class ConnectionOut(Model):
    id: UUID
    address: str
    status: str
    last_checked: datetime | None


class EmailOut(Model):
    id: UUID
    received_at: datetime
    sender: str
    subject: str
    status: str
    reason: str | None
    amount: str | None
    currency: str | None
    merchant: str | None
    transaction_id: UUID | None
    actionable: bool


class OverviewOut(Model):
    available: bool  # Connect Gmail is set up on this server
    connections: list[ConnectionOut]
    emails: list[EmailOut]


@router.get("")
async def overview(auth: Auth, web: Runtime) -> OverviewOut:
    found = await email_cases.overview(web.uow(), auth.user.id, now=web.clock())
    emails = []
    for e in found.emails:
        draft = ExpenseDraft.from_dict(e.draft or {})
        emails.append(
            EmailOut(
                id=e.id,
                received_at=e.received_at,
                sender=e.sender,
                subject=e.subject,
                status=e.status.value,
                reason=e.reason,
                amount=draft.amount,
                currency=draft.currency,
                merchant=draft.merchant,
                transaction_id=e.transaction_id,
                actionable=e.status in ACTIONABLE or e.status is EmailStatus.SKIPPED,
            )
        )
    return OverviewOut(
        available=web.email is not None,
        connections=[
            ConnectionOut(
                id=c.id, address=c.address, status=c.status.value, last_checked=c.synced_until
            )
            for c in found.connections
        ],
        emails=emails,
    )


class LogIn(Model):
    amount: str | None = Field(None, max_length=32)  # the user's figure, if none was found


@router.post("/{email_id}/log", status_code=204)
async def log_email(email_id: UUID, body: LogIn, auth: Auth, web: Runtime) -> None:
    user = auth.user
    amount = Money.of(body.amount, user.home_currency) if body.amount else None
    await email_cases.log_email(web.uow, user, email_id, now=web.clock(), amount=amount)


@router.post("/{email_id}/skip", status_code=204)
async def skip_email(email_id: UUID, auth: Auth, web: Runtime) -> None:
    await email_cases.skip_email(web.uow(), auth.user.id, email_id)


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect(connection_id: UUID, auth: Auth, web: Runtime) -> None:
    email = web.email
    if email is None:
        raise HTTPException(status_code=404)
    await email_cases.disconnect(web.uow, email.mailbox, email.cipher, auth.user.id, connection_id)
