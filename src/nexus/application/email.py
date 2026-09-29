"""Receipts from a connected mailbox.

The user connects a mailbox themselves, through a one-time link. A sweep then
reads only receipt-like emails, screens them cheaply, reads likely receipts into
draft expenses, and asks the user to confirm each one. Nothing reaches the ledger
without that confirmation, and an email whose expense was deleted is never
imported again.
"""

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import receipts as receipt_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import (
    Cipher,
    EmailReader,
    Mailbox,
    MailboxRevoked,
    ReceiptStore,
    UnitOfWork,
)
from nexus.application.transactions import NewTransaction
from nexus.domain.email import (
    ACTIONABLE,
    LINK_TTL,
    READ_TIMEOUT,
    RECEIPT_QUERY,
    SWEEP_BUDGET,
    SWEEP_LIMIT,
    ConnectionStatus,
    EmailConnection,
    EmailStatus,
    ExpenseDraft,
    FetchedEmail,
    InboundEmail,
    Provider,
    external_id,
    short,
    sweep_from,
)
from nexus.domain.errors import Conflict, DuplicateSource, InvalidInput, NotFound
from nexus.domain.ledger import Direction, Source, Transaction, User, UserId
from nexus.domain.money import Money

log = logging.getLogger(__name__)
LOG_WINDOW_DAYS = 30

type UowFactory = Callable[[], UnitOfWork]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EmailRuntime:
    """What mailbox features need, when Gmail is configured."""

    mailbox: Mailbox
    reader: EmailReader
    cipher: Cipher
    origin: str  # the web app, e.g. https://nexus.example.com

    @property
    def redirect_uri(self) -> str:
        """Where the provider sends the user back after sign-in."""
        return f"{self.origin}/api/email/gmail/callback"

    @property
    def review_url(self) -> str:
        return f"{self.origin}/email"

    def connect_url(self, token: str) -> str:
        return f"{self.origin}/connect/gmail?t={token}"


# --- connecting ---------------------------------------------------------------------


async def create_link(uow: UnitOfWork, user: User, *, now: datetime) -> str:
    """A one-time token that starts connecting a mailbox, valid for 10 minutes. It
    lets the sign-in run in the system browser, outside the app's session."""
    token = secrets.token_urlsafe(32)
    async with uow:
        await uow.email.insert_link(user.id, _hash(token), expires_at=now + LINK_TTL, now=now)
        await uow.commit()
    return token


async def link_owner(uow: UnitOfWork, token: str, *, now: datetime) -> UserId | None:
    async with uow:
        return await uow.email.link_owner(_hash(token), now)


async def finish_connect(
    uow: UowFactory,
    mailbox: Mailbox,
    cipher: Cipher,
    *,
    token: str,
    code: str,
    redirect_uri: str,
    now: datetime,
) -> EmailConnection:
    """Complete the provider's sign-in. The link is spent here, so a replayed
    callback connects nothing."""
    if await link_owner(uow(), token, now=now) is None:
        raise NotFound("this connect link has expired; ask Nexus for a new one")
    grant = await mailbox.exchange(code, redirect_uri=redirect_uri)
    async with uow() as tx:
        owner = await tx.email.use_link(_hash(token), now)
        if owner is None:
            raise NotFound("this connect link has already been used")
        connection = await tx.email.save_connection(
            EmailConnection(
                id=uuid4(),
                user_id=owner,
                provider=Provider.GMAIL,
                address=grant.address,
                token=cipher.encrypt(grant.refresh_token),
                status=ConnectionStatus.ACTIVE,
                synced_until=None,
                created_at=now,
                updated_at=now,
            )
        )
        await tx.commit()
    return connection


async def disconnect(
    uow: UowFactory, mailbox: Mailbox, cipher: Cipher, user_id: UserId, connection_id: UUID
) -> None:
    """Revoke our access with the provider and forget the mailbox. Expenses already
    logged from it stay, and so does their dedupe key."""
    async with uow() as tx:
        connection = await tx.email.get_connection(user_id, connection_id)
    if connection is None:
        raise NotFound("that mailbox isn't connected")
    try:
        await mailbox.revoke(cipher.decrypt(connection.token))
    except Exception:
        log.warning("could not revoke a mailbox grant", exc_info=True)
    async with uow() as tx:
        await tx.email.delete_connection(user_id, connection_id)
        await tx.commit()


# --- sweeping -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SweepResult:
    read: int
    waiting: int  # new receipts waiting for the user
    first: bool  # the first sweep after connecting (the 30-day look-back)


def _occurred(draft: ExpenseDraft, email: FetchedEmail, tz: ZoneInfo) -> datetime:
    if draft.date:
        try:
            return datetime.combine(date.fromisoformat(draft.date), time(12), tzinfo=tz)
        except ValueError:
            pass
    return email.received_at


def _amount(draft: ExpenseDraft, home: str) -> Money | None:
    if not draft.amount:
        return None
    try:
        money = Money.of(draft.amount.replace(",", ""), (draft.currency or home).upper())
    except (InvalidInput, ValueError):
        return None
    return money if money.is_positive else None


def prompt_text(email: InboundEmail, tz: ZoneInfo) -> str:
    draft = ExpenseDraft.from_dict(email.draft or {})
    where = f" at {draft.merchant}" if draft.merchant else ""
    day = email.received_at.astimezone(tz).date()
    if draft.date:
        try:
            day = date.fromisoformat(draft.date)
        except ValueError:
            pass
    money = _amount(draft, draft.currency or "")
    return f"📧 From your email: {money}{where} on {day:%-d %b}. Log it?"


async def _read_one(
    reader: EmailReader,
    archive: ReceiptStore | None,
    uow: UowFactory,
    user: User,
    connection: EmailConnection,
    fetched: FetchedEmail,
    now: datetime,
) -> InboundEmail:
    """Screen and read one email into its log entry."""
    status: EmailStatus = EmailStatus.FAILED
    reason: str | None = "couldn't be read"
    draft: dict[str, Any] | None = None
    try:
        screening = await asyncio.wait_for(reader.triage(fetched), READ_TIMEOUT.total_seconds())
        if not screening.is_receipt:
            status, reason = EmailStatus.NOT_RECEIPT, short(screening.reason, 80)
        else:
            expense = await asyncio.wait_for(reader.extract(fetched), READ_TIMEOUT.total_seconds())
            money = _amount(expense, user.home_currency)
            if money is None:
                status, reason = EmailStatus.NO_AMOUNT, "no total found"
                draft = expense.as_dict()
            else:
                status, reason = EmailStatus.PENDING, None
                draft = replace(
                    expense, amount=str(money.amount), currency=money.currency
                ).as_dict()
                draft["occurred_at"] = _occurred(
                    expense, fetched, ZoneInfo(user.timezone)
                ).isoformat()
                if fetched.pdf and archive is not None:
                    try:
                        kept = await receipt_cases.stash(
                            uow(), archive, user.id, fetched.pdf, "application/pdf", now=now
                        )
                        draft["receipt_id"] = str(kept.id)
                    except Exception:
                        log.warning("could not keep an email's PDF receipt", exc_info=True)
    except TimeoutError:
        reason = "took too long to read"
        log.warning("reading an email timed out")
    except Exception:
        log.exception("could not read an email")
    return InboundEmail(
        id=uuid4(),
        user_id=user.id,
        connection_id=connection.id,
        provider_message_id=fetched.provider_message_id,
        received_at=fetched.received_at,
        sender=short(fetched.sender, 200),
        subject=short(fetched.subject, 200),
        status=status,
        reason=reason,
        draft=draft,
        transaction_id=None,
        created_at=now,
    )


async def sweep(
    uow: UowFactory,
    mailbox: Mailbox,
    reader: EmailReader,
    cipher: Cipher,
    archive: ReceiptStore | None,
    user: User,
    connection: EmailConnection,
    *,
    now: datetime,
    review_url: str | None = None,
) -> SweepResult:
    """Look for new receipts in one mailbox and ask the user about each."""
    first = connection.synced_until is None
    try:
        access = await mailbox.access_token(cipher.decrypt(connection.token))
        ids = await mailbox.search(access, RECEIPT_QUERY, after=sweep_from(connection, now))
    except MailboxRevoked:
        await _broken(uow, user, connection, now)
        return SweepResult(0, 0, first)
    async with uow() as tx:
        seen = await tx.email.seen_message_ids(connection.id, ids)
    fresh = [i for i in ids if i not in seen]
    batch, left = fresh[:SWEEP_LIMIT], fresh[SWEEP_LIMIT:]
    waiting: list[InboundEmail] = []
    started = monotonic()
    read = 0
    for message_id in batch:
        if monotonic() - started > SWEEP_BUDGET.total_seconds():
            left = [*batch[read:], *left]  # the next sweep picks these up
            break
        read += 1
        fetched = await mailbox.fetch(access, message_id)
        email = await _read_one(reader, archive, uow, user, connection, fetched, now)
        async with uow() as tx:
            if email.status is EmailStatus.PENDING and await tx.ledger.source_claimed(
                user.id,
                Source.EMAIL,
                external_id(connection.provider, connection.address, message_id),
            ):
                email = replace(email, status=EmailStatus.DUPLICATE, reason="already logged")
            if await tx.email.insert_inbound(email) and email.status is EmailStatus.PENDING:
                waiting.append(email)
            await tx.commit()
    async with uow() as tx:
        current = await tx.email.get_connection(user.id, connection.id, for_update=True)
        if current is not None:
            # Move the window on only once everything in it has been read.
            synced = now if not left else current.synced_until
            await tx.email.update_connection(
                replace(current, synced_until=synced, last_error=None, updated_at=now)
            )
        await _ask(tx, user, waiting, first=first, review_url=review_url)
        await tx.commit()
    log.info(
        "email sweep: read %d, %d waiting, %d left for next time", read, len(waiting), len(left)
    )
    return SweepResult(read, len(waiting), first)


async def _ask(
    tx: UnitOfWork,
    user: User,
    waiting: list[InboundEmail],
    *,
    first: bool,
    review_url: str | None,
) -> None:
    """One message per new receipt; after connecting, one summary of the look-back."""
    if not waiting:
        return
    tz = ZoneInfo(user.timezone)
    if first and len(waiting) > 1:
        buttons = [[{"label": "Review them", "data": f"url:{review_url}"}]] if review_url else []
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {
                "user_id": str(user.id),
                "text": f"📧 I found {len(waiting)} receipts from the last 30 days. "
                "Nothing is logged until you confirm each one.",
                "buttons": buttons,
            },
            dedupe_key=f"email.backfill:{waiting[0].connection_id}",
            run_at=waiting[0].created_at,
        )
        return
    for email in waiting:
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {
                "user_id": str(user.id),
                "text": prompt_text(email, tz),
                "buttons": [
                    [
                        {"label": "Log it", "data": f"email:log:{email.id}"},
                        {"label": "Skip", "data": f"email:skip:{email.id}"},
                    ]
                ],
            },
            dedupe_key=f"email.ask:{email.id}",
            run_at=email.created_at,
        )


async def _broken(uow: UowFactory, user: User, connection: EmailConnection, now: datetime) -> None:
    """The provider refused us: stop sweeping and tell the user once."""
    async with uow() as tx:
        current = await tx.email.get_connection(user.id, connection.id, for_update=True)
        if current is None or current.status is ConnectionStatus.BROKEN:
            return
        await tx.email.update_connection(
            replace(
                current,
                status=ConnectionStatus.BROKEN,
                last_error="access was revoked or expired",
                updated_at=now,
            )
        )
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {
                "user_id": str(user.id),
                "text": f"I can't read {current.address} any more (access was removed or "
                "expired), so I've stopped checking it. Ask me to connect it again anytime.",
            },
            dedupe_key=f"email.broken:{current.id}:{current.updated_at.isoformat()}",
            run_at=now,
        )
        await tx.commit()


# --- the user's answer --------------------------------------------------------------


async def _pending(tx: UnitOfWork, user_id: UserId, email_id: UUID) -> InboundEmail:
    email = await tx.email.get_inbound(user_id, email_id, for_update=True)
    if email is None:
        raise NotFound("that email isn't in your list")
    if email.status is EmailStatus.LOGGED:
        raise Conflict("that email is already logged")
    if email.status not in ACTIONABLE | {EmailStatus.SKIPPED}:
        raise Conflict("that email can't be logged")
    return email


async def log_email(
    uow: UowFactory,
    user: User,
    email_id: UUID,
    *,
    now: datetime,
    amount: Money | None = None,
) -> Transaction:
    """The user said yes: save the expense (and its PDF, if kept). ``amount`` is the
    user's own figure, for an email where none was found."""
    async with uow() as tx:
        email = await _pending(tx, user.id, email_id)
        connection = await tx.email.get_connection(user.id, email.connection_id)
        if connection is None:  # pragma: no cover - the foreign key cascades
            raise NotFound("that mailbox isn't connected")
        draft = email.draft or {}
        money = amount or _amount(ExpenseDraft.from_dict(draft), user.home_currency)
        if money is None:
            raise InvalidInput("no amount was found in that email; tell me the amount")
        occurred = draft.get("occurred_at")
        receipt = draft.get("receipt_id")
        key = external_id(connection.provider, connection.address, email.provider_message_id)
        cmd = NewTransaction(
            direction=Direction.OUT,
            amount=money,
            occurred_at=datetime.fromisoformat(occurred) if occurred else email.received_at,
            counterparty=draft.get("merchant"),
            notes=email.subject or None,
            source=Source.EMAIL,
            external_id=key,
        )
    try:
        saved = await receipt_cases.log_with_receipt(
            uow(), user.id, cmd, UUID(receipt) if receipt else None, now=now
        )
    except DuplicateSource:
        await _set(uow(), user.id, email_id, EmailStatus.DUPLICATE, "already logged")
        raise
    except NotFound:
        # The kept PDF expired (a day unconfirmed): log the expense without it.
        saved = await receipt_cases.log_with_receipt(uow(), user.id, cmd, None, now=now)
    await _set(uow(), user.id, email_id, EmailStatus.LOGGED, None, saved.id)
    return saved


async def _set(
    uow: UnitOfWork,
    user_id: UserId,
    email_id: UUID,
    status: EmailStatus,
    reason: str | None,
    transaction_id: UUID | None = None,
) -> None:
    async with uow:
        email = await uow.email.get_inbound(user_id, email_id, for_update=True)
        if email is not None:
            await uow.email.update_inbound(
                replace(email, status=status, reason=reason, transaction_id=transaction_id)
            )
            await uow.commit()


async def skip_email(uow: UnitOfWork, user_id: UserId, email_id: UUID) -> None:
    async with uow:
        email = await _pending(uow, user_id, email_id)
        await uow.email.update_inbound(
            replace(email, status=EmailStatus.SKIPPED, reason="you skipped it")
        )
        await uow.commit()


# --- the Email page -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Overview:
    connections: list[EmailConnection]
    emails: list[InboundEmail]


async def overview(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> Overview:
    async with uow:
        connections = await uow.email.list_connections(user_id)
        emails = await uow.email.list_inbound(
            user_id, since=now - timedelta(days=LOG_WINDOW_DAYS), limit=200
        )
    return Overview(connections, emails)
