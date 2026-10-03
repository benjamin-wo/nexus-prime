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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import duplicates as duplicate_cases
from nexus.application import receipts as receipt_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.ports import (
    Cipher,
    EmailReader,
    ForwardingInboxes,
    Mailbox,
    MailboxRevoked,
    ReceiptStore,
    SignInMailbox,
    UnitOfWork,
)
from nexus.application.splits import owing_person
from nexus.application.transactions import NewTransaction
from nexus.domain.duplicates import Candidate, better_name, likely_same
from nexus.domain.email import (
    ACTIONABLE,
    FILTER_WORDS,
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
    amount_in_text,
    external_id,
    forwarding_notice,
    is_test_email,
    needs_nudge,
    read_amount,
    short,
    sweep_from,
)
from nexus.domain.errors import Conflict, DuplicateSource, InvalidInput, NotFound
from nexus.domain.ledger import Direction, OpenIou, Source, Transaction, User, UserId
from nexus.domain.money import Money
from nexus.domain.notifications import Frequency
from nexus.domain.receipts import UNCLAIMED_TTL

log = logging.getLogger(__name__)
SWEEP_JOB = "email.sweep"
LOG_WINDOW_DAYS = 30

type UowFactory = Callable[[], UnitOfWork]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class EmailRuntime:
    """What email features need: Gmail, forwarding addresses, or both."""

    mailbox: SignInMailbox | None  # Connect Gmail, when Google is configured
    reader: EmailReader
    cipher: Cipher
    origin: str  # the web app, e.g. https://nexus.example.com
    forwarding: ForwardingInboxes | None = None  # forwarding addresses (AgentMail)

    @property
    def redirect_uri(self) -> str:
        """Where the provider sends the user back after sign-in."""
        return f"{self.origin}/api/email/gmail/callback"

    @property
    def review_url(self) -> str:
        return f"{self.origin}/email"

    def connect_url(self, token: str) -> str:
        return f"{self.origin}/connect/gmail?t={token}"

    def mailbox_for(self, provider: Provider) -> Mailbox | None:
        return self.forwarding if provider is Provider.FORWARD else self.mailbox


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
    mailbox: SignInMailbox,
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


async def set_up_forwarding(
    uow: UowFactory, inboxes: ForwardingInboxes, cipher: Cipher, user: User, *, now: datetime
) -> EmailConnection:
    """The user's own forwarding address, made the first time they ask for it."""
    async with uow() as tx:
        existing = [
            c
            for c in await tx.email.list_connections(user.id)
            if c.provider is Provider.FORWARD and c.status is ConnectionStatus.ACTIVE
        ]
    if existing:
        return existing[0]
    inbox_id, address = await inboxes.create_inbox(str(user.id))
    async with uow() as tx:
        connection = await tx.email.save_connection(
            EmailConnection(
                id=uuid4(),
                user_id=user.id,
                provider=Provider.FORWARD,
                address=address,
                token=cipher.encrypt(inbox_id),
                status=ConnectionStatus.ACTIVE,
                # A new address has nothing in it: no look-back.
                synced_until=now,
                created_at=now,
                updated_at=now,
            )
        )
        await tx.commit()
    return connection


FORWARDING_PROVIDERS = ("gmail", "outlook", "icloud", "yahoo", "other")


def forwarding_steps(provider: str, address: str) -> str:
    """How to forward only receipts to ``address`` from the user's mail app."""
    words = ", ".join(FILTER_WORDS)
    either = " OR ".join(FILTER_WORDS)
    steps = {
        "gmail": [
            "In Gmail on a computer: Settings, See all settings, Forwarding and POP/IMAP, "
            f"Add a forwarding address: {address}",
            "Gmail sends a confirmation to that address. I'll pass the code and link on to "
            "you here; open the link to allow it.",
            f"Then Filters and Blocked Addresses, Create a new filter. Subject: {either}. "
            f"Create filter, tick Forward it to {address}, and save.",
        ],
        "outlook": [
            "In Outlook (outlook.com or the app): Settings, Mail, Rules, Add new rule.",
            f"Condition: Subject includes, and add these words: {words}.",
            f"Action: Forward to {address}. Save.",
        ],
        "icloud": [
            "On icloud.com: Mail, then the settings (gear), Rules, Add a Rule.",
            f'If a message: Subject contains "receipt". Then: Forward to {address}.',
            "Add one rule for each word you want: invoice, order, payment, transaction.",
        ],
        "yahoo": [
            "Yahoo only forwards automatically on Yahoo Mail Plus: Settings, More "
            f"settings, Mailboxes, then add the forwarding address {address}. It forwards "
            "everything, not just receipts.",
            "On free Yahoo Mail, forward receipts by hand instead.",
        ],
        "other": [
            "In your mail app, find Rules or Filters.",
            f"Make a rule: if the subject contains {words}, forward to {address}.",
        ],
    }[provider if provider in FORWARDING_PROVIDERS else "other"]
    lines = [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    lines.append(f"You can also forward any receipt to {address} by hand.")
    return "\n".join(lines)


def sender_checklist(emails: list[InboundEmail]) -> list[str]:
    """Who sent receipts and who sent other mail, for deciding what a filter keeps."""
    receipts: dict[str, int] = {}
    other: dict[str, int] = {}
    for e in emails:
        if e.status in (EmailStatus.FAILED,) or e.reason in (
            "your test email",
            "forwarding confirmation, sent to you",
        ):
            continue
        domain = e.sender.rsplit("@", 1)[-1].casefold() or e.sender
        bucket = other if e.status is EmailStatus.NOT_RECEIPT else receipts
        bucket[domain] = bucket.get(domain, 0) + 1

    def top(found: dict[str, int]) -> str:
        ranked = sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        return ", ".join(f"{d} ({n})" for d, n in ranked)

    lines = []
    if receipts:
        lines.append(f"Receipts came from: {top(receipts)}.")
    if other:
        lines.append(f"Not receipts (a filter can leave these out): {top(other)}.")
    return lines


async def forwarding_address(uow: UnitOfWork, user_id: UserId) -> EmailConnection | None:
    async with uow:
        found = await uow.email.list_connections(user_id)
    return next((c for c in found if c.provider is Provider.FORWARD), None)


async def test_setup(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> None:
    """Check a forwarding address a few times over the next minutes, so a test email
    is answered quickly rather than at the next regular sweep."""
    async with uow:
        for minutes in (1, 3, 6):
            at = now + timedelta(minutes=minutes)
            await uow.jobs.enqueue(
                SWEEP_JOB, {}, dedupe_key=f"email.test:{user_id}:{at.isoformat()}", run_at=at
            )
        await uow.commit()


async def disconnect(
    uow: UowFactory, runtime: EmailRuntime, user_id: UserId, connection_id: UUID
) -> None:
    """Revoke our access with the provider (or delete the forwarding address) and
    forget the mailbox. Expenses already logged from it stay, and so does their
    dedupe key."""
    async with uow() as tx:
        connection = await tx.email.get_connection(user_id, connection_id)
    if connection is None:
        raise NotFound("that mailbox isn't connected")
    mailbox = runtime.mailbox_for(connection.provider)
    try:
        if mailbox is not None:
            await mailbox.revoke(runtime.cipher.decrypt(connection.token))
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
    return read_amount(draft.amount, draft.currency, home)


def _day(email: InboundEmail, draft: ExpenseDraft, tz: ZoneInfo) -> date:
    if draft.date:
        try:
            return date.fromisoformat(draft.date)
        except ValueError:
            pass
    return email.received_at.astimezone(tz).date()


def prompt_text(email: InboundEmail, tz: ZoneInfo) -> str:
    draft = ExpenseDraft.from_dict(email.draft or {})
    money = _amount(draft, draft.currency or "")
    day = _day(email, draft, tz)
    if draft.received:
        sender = f" from {draft.merchant}" if draft.merchant else ""
        return f"📧 From your email: {money} came in{sender} on {day:%-d %b}. Log it as money in?"
    where = f" at {draft.merchant}" if draft.merchant else ""
    return f"📧 From your email: {money}{where} on {day:%-d %b}. Log it?"


def question(
    email: InboundEmail, tz: ZoneInfo, open_ious: list[OpenIou]
) -> tuple[str, list[list[dict[str, str]]]]:
    """What to ask about an email, and its buttons. Money in from someone who owes
    the user is offered as their repayment."""
    draft = ExpenseDraft.from_dict(email.draft or {})
    skip = {"label": "Skip", "data": f"email:skip:{email.id}"}
    twin = duplicate_of(email)
    if twin is not None:
        where = "already in your ledger" if "transaction_id" in twin else "in another email"
        return (
            f"{prompt_text(email, tz).rsplit('. ', 1)[0]}. This looks like {twin['label']}, "
            f"{where}. Same payment?",
            [
                [
                    {"label": "Same one", "data": f"email:same:{email.id}"},
                    {"label": "It's another", "data": f"email:log:{email.id}"},
                ],
                [skip],
            ],
        )
    person = owing_person(open_ious, draft.merchant) if draft.received and draft.merchant else None
    if person is None:
        return prompt_text(email, tz), [
            [{"label": "Log it", "data": f"email:log:{email.id}"}, skip]
        ]
    money = _amount(draft, draft.currency or "")
    owed = [i.outstanding for i in open_ious if i.split.participant_name == person]
    total = sum(owed[1:], owed[0])
    text = (
        f"📧 From your email: {money} came in from {draft.merchant} on "
        f"{_day(email, draft, tz):%-d %b}. {person} owes you {total}. Count it as paying "
        "that back?"
    )
    return text, [
        [
            {"label": "Yes, paid back", "data": f"email:repay:{email.id}"},
            {"label": "Just income", "data": f"email:income:{email.id}"},
        ],
        [skip],
    ]


def duplicate_of(email: InboundEmail) -> dict[str, str] | None:
    """What this email looks like a second record of, if anything."""
    found = (email.draft or {}).get("duplicate_of")
    return found if isinstance(found, dict) else None


async def _read_one(
    reader: EmailReader,
    archive: ReceiptStore | None,
    uow: UowFactory,
    user: User,
    connection: EmailConnection,
    fetched: FetchedEmail,
    now: datetime,
    categories: Sequence[str] = (),
    reads: int = 1,
) -> InboundEmail:
    """Screen and read one email into its log entry. ``reads`` counts this try; one
    that fails keeps the count, and the one amount the email states if it has one,
    so a later sweep can try again and the user can log it meanwhile."""
    status: EmailStatus = EmailStatus.FAILED
    reason: str | None = "couldn't be read"
    draft: dict[str, Any] | None = None
    try:
        screening = await asyncio.wait_for(reader.triage(fetched), READ_TIMEOUT.total_seconds())
        if not screening.is_receipt:
            status, reason = EmailStatus.NOT_RECEIPT, short(screening.reason, 80)
        else:
            expense = await asyncio.wait_for(
                reader.extract(fetched, categories=categories, received=screening.received),
                READ_TIMEOUT.total_seconds(),
            )
            # When the model's figure can't be read (once it gave the field's name,
            # "currency"), the one amount the email states with its currency will do.
            money = _amount(expense, user.home_currency) or amount_in_text(fetched.text)
            if money is None:
                status = EmailStatus.NO_AMOUNT
                raw = short(expense.amount or "", 40)
                reason = f'couldn\'t read the amount "{raw}"' if raw else "no total found"
                draft = replace(expense, amount=None).as_dict()
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
    if status is EmailStatus.FAILED:
        draft = {"reads": reads}
        stated = amount_in_text(fetched.text)
        if stated is not None:
            draft |= {"amount": str(stated.amount), "currency": stated.currency}
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
        categories = [
            c.name for c in await tx.ledger.list_categories(user.id, include_inactive=False)
        ]
    fresh = [i for i in ids if i not in seen]
    batch, left = fresh[:SWEEP_LIMIT], fresh[SWEEP_LIMIT:]
    waiting: list[InboundEmail] = []
    started = monotonic()
    read = 0
    newest: datetime | None = None  # the latest email to arrive, for a forwarding address
    for message_id in batch:
        if monotonic() - started > SWEEP_BUDGET.total_seconds():
            left = [*batch[read:], *left]  # the next sweep picks these up
            break
        read += 1
        fetched = await mailbox.fetch(access, message_id)
        if newest is None or fetched.received_at > newest:
            newest = fetched.received_at
        told = await _setup_email(uow, user, connection, fetched, now)
        email = told or await _read_one(
            reader, archive, uow, user, connection, fetched, now, categories
        )
        if saved := await _record(uow, user, connection, email, new=True):
            waiting.append(saved)
    # Then emails a slow or failing model couldn't read on an earlier sweep, while
    # time is left.
    async with uow() as tx:
        unread = await tx.email.unread(user.id, connection.id, SWEEP_LIMIT)
    for before in (e for e in unread if e.provider_message_id not in batch):
        if monotonic() - started > SWEEP_BUDGET.total_seconds():
            break
        read += 1
        try:
            fetched = await mailbox.fetch(access, before.provider_message_id)
        except MailboxRevoked:
            raise
        except Exception:
            log.warning("could not fetch an email again to read it", exc_info=True)
            again = replace(before, draft={**(before.draft or {}), "reads": before.reads + 1})
        else:
            result = await _read_one(
                reader, archive, uow, user, connection, fetched, now, categories, before.reads + 1
            )
            again = replace(before, status=result.status, reason=result.reason, draft=result.draft)
        if saved := await _record(uow, user, connection, again, new=False):
            waiting.append(saved)
    async with uow() as tx:
        current = await tx.email.get_connection(user.id, connection.id, for_update=True)
        if current is not None:
            # Move the window on only once everything in it has been read.
            synced = now if not left else current.synced_until
            current = replace(current, synced_until=synced, last_error=None, updated_at=now)
            if newest is not None and connection.provider is Provider.FORWARD:
                current = replace(
                    current, last_received_at=max(newest, current.last_received_at or newest)
                )
            if needs_nudge(current, now):
                current = replace(current, nudged_at=now)
                await _nudge(tx, user, current, now)
            await tx.email.update_connection(current)
        await _ask(tx, user, waiting, first=first, review_url=review_url)
        await tx.commit()
    log.info(
        "email sweep: read %d, %d waiting, %d left for next time", read, len(waiting), len(left)
    )
    return SweepResult(read, len(waiting), first)


async def _record(
    uow: UowFactory, user: User, connection: EmailConnection, email: InboundEmail, *, new: bool
) -> InboundEmail | None:
    """Save what a read found; the email if it's a receipt now waiting for the user."""
    if email.status is EmailStatus.PENDING:
        email = await _flag_duplicate(uow, user, email)
    async with uow() as tx:
        if not new:
            current = await tx.email.get_inbound(user.id, email.id, for_update=True)
            if current is None or current.status is not EmailStatus.FAILED:
                return None  # the user logged or skipped it while it was being read
        if email.status is EmailStatus.PENDING and await tx.ledger.source_claimed(
            user.id,
            Source.EMAIL,
            external_id(connection.provider, connection.address, email.provider_message_id),
        ):
            email = replace(email, status=EmailStatus.DUPLICATE, reason="already logged")
        if new:
            saved = await tx.email.insert_inbound(email)
        else:
            await tx.email.update_inbound(email)
            saved = True
        await tx.commit()
    return email if saved and email.status is EmailStatus.PENDING else None


def _candidate(email: InboundEmail, home: str) -> Candidate | None:
    draft = ExpenseDraft.from_dict(email.draft or {})
    money = _amount(draft, home)
    if money is None:
        return None
    occurred = (email.draft or {}).get("occurred_at")
    return Candidate(
        Direction.IN if draft.received else Direction.OUT,
        money,
        datetime.fromisoformat(occurred) if occurred else email.received_at,
        draft.merchant,
        Source.EMAIL,
        email.subject,
    )


def _label(merchant: str | None, money: Money, when: datetime, tz: ZoneInfo) -> str:
    return f"{merchant or 'no name'}, {money} on {when.astimezone(tz):%-d %b}"


async def _flag_duplicate(uow: UowFactory, user: User, email: InboundEmail) -> InboundEmail:
    """Note in the draft the ledger entry, or another email still waiting, that looks
    like this same payment (a card alert and the shop's receipt), so the user is
    asked "same one?" rather than logging it twice."""
    mine = _candidate(email, user.home_currency)
    if mine is None:
        return email
    tz = ZoneInfo(user.timezone)
    found: dict[str, str] | None = None
    tx = await duplicate_cases.check(uow(), user, mine)
    if tx is not None:
        found = {
            "transaction_id": str(tx.id),
            "label": _label(tx.counterparty, tx.amount, tx.occurred_at, tz),
        }
    else:
        async with uow() as db:
            recent = await db.email.list_inbound(
                user.id, since=mine.occurred_at - timedelta(days=3), limit=200
            )
        for other in recent:
            if other.id == email.id or other.status is not EmailStatus.PENDING:
                continue
            theirs = _candidate(other, user.home_currency)
            if theirs is not None and likely_same(mine, theirs, tz):
                found = {
                    "email_id": str(other.id),
                    "label": _label(theirs.merchant, theirs.amount, theirs.occurred_at, tz),
                }
                break
    if found is None:
        return email
    return replace(email, draft={**(email.draft or {}), "duplicate_of": found})


async def _setup_email(
    uow: UowFactory, user: User, connection: EmailConnection, fetched: FetchedEmail, now: datetime
) -> InboundEmail | None:
    """At a forwarding address, a provider's "confirm forwarding" email and the user's
    own test email are answered straight away instead of being read as receipts."""
    if connection.provider is not Provider.FORWARD:
        return None
    notice = forwarding_notice(fetched)
    if notice is not None:
        lines = [
            f"📨 Your mail provider sent a confirmation to your Nexus address: {notice.subject}"
        ]
        if notice.code:
            lines.append(f"Confirmation code: {notice.code}")
        lines.append(
            "Open the link or enter the code where you set up forwarding, then send a test."
            if notice.link or notice.code
            else "Check your mail app's forwarding settings to finish."
        )
        buttons = (
            [[{"label": "Confirm forwarding", "data": f"url:{notice.link}"}]] if notice.link else []
        )
        reason = "forwarding confirmation, sent to you"
    elif is_test_email(fetched):
        lines = [
            f"✅ Your test email from {fetched.sender} arrived. Forwarding works: "
            "receipts forwarded to me will show up here for you to confirm."
        ]
        buttons = []
        reason = "your test email"
    else:
        return None
    async with uow() as tx:
        payload: dict[str, Any] = {"user_id": str(user.id), "text": "\n".join(lines)}
        if buttons:
            payload["buttons"] = buttons
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            payload,
            dedupe_key=f"email.setup:{connection.id}:{fetched.provider_message_id}",
            run_at=now,
        )
        await tx.commit()
    return InboundEmail(
        id=uuid4(),
        user_id=user.id,
        connection_id=connection.id,
        provider_message_id=fetched.provider_message_id,
        received_at=fetched.received_at,
        sender=short(fetched.sender, 200),
        subject=short(fetched.subject, 200),
        status=EmailStatus.NOT_RECEIPT,
        reason=reason,
        draft=None,
        transaction_id=None,
        created_at=now,
    )


async def _nudge(tx: UnitOfWork, user: User, connection: EmailConnection, now: datetime) -> None:
    heard = connection.last_received_at
    since = "in the last 2 weeks" if heard else "since you set it up"
    await tx.jobs.enqueue(
        TELEGRAM_SEND,
        {
            "user_id": str(user.id),
            "text": f"I haven't received any forwarded emails at {connection.address} {since}. "
            "If you still want receipts logged from email, check your forwarding rule, or "
            "ask me to test your email setup. If you've stopped, you can disconnect it on "
            "the Email page.",
        },
        dedupe_key=f"email.quiet:{connection.id}:{now.date().isoformat()}",
        run_at=now,
    )


async def _ask(
    tx: UnitOfWork,
    user: User,
    waiting: list[InboundEmail],
    *,
    first: bool,
    review_url: str | None,
) -> None:
    """After connecting, one summary of the look-back. Later receipts are asked about
    one by one only if the user wants updates as they happen; otherwise they're in
    the user's next summary."""
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
    if not first:
        settings = await tx.planning.get_notifications(user.id)
        if settings.frequency is not Frequency.INSTANT:
            return
    open_ious = await tx.ledger.open_ious(user.id)
    for email in waiting:
        text, buttons = question(email, tz, open_ious)
        await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {"user_id": str(user.id), "text": text, "buttons": buttons},
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
    repayment: bool | None = None,
) -> Transaction:
    """The user said yes: save the expense (and its PDF, if kept). ``amount`` is the
    user's own figure, for an email where none was found. Money received is saved as
    money in; ``repayment`` says whether it pays off what the sender owes (True),
    is plain income (False), or, left out, pays it off if they owe anything."""
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
        when = datetime.fromisoformat(occurred) if occurred else email.received_at
        receipt = draft.get("receipt_id")
        key = external_id(connection.provider, connection.address, email.provider_message_id)
        read = ExpenseDraft.from_dict(draft)
        owes = (
            owing_person(await tx.ledger.open_ious(user.id), read.merchant)
            if read.received and read.merchant
            else None
        )
    if read.received:
        try:
            saved = await _log_received(uow, user, read, money, when, email, key, owes, repayment)
        except DuplicateSource:
            await _set(uow(), user.id, email_id, EmailStatus.DUPLICATE, "already logged")
            raise
        await _set(uow(), user.id, email_id, EmailStatus.LOGGED, None, saved.id)
        return saved
    async with uow() as tx:
        cmd = NewTransaction(
            direction=Direction.OUT,
            amount=money,
            occurred_at=when,
            counterparty=draft.get("merchant"),
            notes=email.subject or None,
            source=Source.EMAIL,
            external_id=key,
            fallback_category_id=await _category_named(tx, user.id, draft.get("category")),
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


async def _log_received(
    uow: UowFactory,
    user: User,
    draft: ExpenseDraft,
    money: Money,
    when: datetime,
    email: InboundEmail,
    key: str,
    owes: str | None,
    repayment: bool | None,
) -> Transaction:
    if repayment is True and owes is None:
        raise InvalidInput(f"{draft.merchant or 'the sender'} doesn't owe you anything")
    if owes is not None and repayment is not False:
        settled = await split_cases.settle_iou(
            uow(),
            user.id,
            owes,
            money,
            when,
            notes=email.subject or None,
            source=Source.EMAIL,
            external_id=key,
        )
        return settled.transaction
    return await tx_cases.log_transaction(
        uow(),
        user.id,
        NewTransaction(
            direction=Direction.IN,
            amount=money,
            occurred_at=when,
            counterparty=draft.merchant,
            notes=email.subject or None,
            source=Source.EMAIL,
            external_id=key,
        ),
    )


async def _category_named(tx: UnitOfWork, user_id: UserId, name: object) -> UUID | None:
    if not isinstance(name, str) or not name.strip():
        return None
    for c in await tx.ledger.list_categories(user_id, include_inactive=False):
        if c.name.casefold() == name.strip().casefold():
            return c.id
    return None


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


async def same_payment(
    uow: UowFactory, user: User, email_id: UUID, *, now: datetime
) -> Transaction | None:
    """The user says this email is the same payment as the one it looks like. Nothing
    new is logged: a ledger entry takes the more readable name (and this email's PDF
    receipt, if it has none), or the other waiting email does. Returns the ledger
    entry, or None when the other email is still waiting for an answer."""
    async with uow() as tx:
        email = await _pending(tx, user.id, email_id)
    twin = duplicate_of(email)
    if twin is None:
        raise InvalidInput("that email doesn't look like anything already logged")
    draft = ExpenseDraft.from_dict(email.draft or {})
    target = twin.get("transaction_id")
    if "email_id" in twin:
        async with uow() as tx:
            other = await tx.email.get_inbound(user.id, UUID(twin["email_id"]), for_update=True)
            if other is None or other.status is EmailStatus.SKIPPED:
                raise InvalidInput("the other email was skipped; log this one instead")
            if other.status is EmailStatus.LOGGED and other.transaction_id is not None:
                target = str(other.transaction_id)
            else:
                theirs = ExpenseDraft.from_dict(other.draft or {})
                named = better_name(theirs.merchant, draft.merchant)
                if named != theirs.merchant:
                    await tx.email.update_inbound(
                        replace(other, draft={**(other.draft or {}), "merchant": named})
                    )
                await tx.email.update_inbound(
                    replace(
                        email,
                        status=EmailStatus.DUPLICATE,
                        reason="the same payment as another email",
                    )
                )
                await tx.commit()
                return None
    if target is None:  # pragma: no cover - a draft always names one or the other
        raise InvalidInput("that email doesn't look like anything already logged")
    current = await tx_cases.get_transaction(uow(), user.id, UUID(target))
    if current.is_deleted:
        raise InvalidInput("that entry was deleted; log this email instead")
    named = better_name(current.counterparty, draft.merchant)
    if named != current.counterparty:
        current = await tx_cases.edit_transaction(
            uow(), user.id, current.id, tx_cases.TransactionChanges(counterparty=named)
        )
    receipt = (email.draft or {}).get("receipt_id")
    async with uow() as tx:
        if receipt and await tx.ledger.live_receipt(user.id, current.id) is None:
            await tx.ledger.attach_receipt(
                user.id, UUID(receipt), current.id, stashed_after=now - UNCLAIMED_TTL
            )
        await tx.email.update_inbound(
            replace(
                email,
                status=EmailStatus.LOGGED,
                reason="the same payment as one already logged",
                transaction_id=current.id,
            )
        )
        await tx.commit()
    return current


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


WAITING_DAYS = 14
WAITING_SHOWN = 5


async def waiting(uow: UnitOfWork, user_id: UserId, *, now: datetime) -> list[InboundEmail]:
    """Emails from the last two weeks still waiting for the user's answer, newest
    first: what the chat can talk about ("log that transfer just now")."""
    async with uow:
        emails = await uow.email.list_inbound(
            user_id, since=now - timedelta(days=WAITING_DAYS), limit=200
        )
    open_ = [
        e
        for e in emails
        if e.status in (EmailStatus.PENDING, EmailStatus.NO_AMOUNT, EmailStatus.FAILED)
    ]
    return sorted(open_, key=lambda e: e.received_at, reverse=True)[:WAITING_SHOWN]


def describe(email: InboundEmail, tz: ZoneInfo) -> str:
    """One line about an email waiting for an answer, for the chat."""
    draft = ExpenseDraft.from_dict(email.draft or {})
    when = email.received_at.astimezone(tz)
    money = _amount(draft, draft.currency or "") if draft.amount else None
    figure = str(money) if money else "no amount found"
    if email.status is EmailStatus.FAILED:
        stated = f", it states {money}" if money else ""
        return (
            f"{when:%a %-d %b %H:%M}, couldn't be read{stated} "
            f"(email from {short(email.sender, 40)}: {short(email.subject, 60)})"
        )
    if draft.received:
        sender = f" from {draft.merchant}" if draft.merchant else ""
        what = f"{figure} came in{sender}"
    else:
        where = f" at {draft.merchant}" if draft.merchant else ""
        what = f"{figure} spent{where}"
    twin = duplicate_of(email)
    same = f"; looks like the same payment as {twin['label']}" if twin else ""
    return f"{when:%a %-d %b %H:%M}, {what} (email: {short(email.subject, 60)}){same}"
