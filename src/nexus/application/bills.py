"""Scheduled payments (bills, and whatever else the user names: a regular
investment, a transfer to savings): remember due dates, remind 7/3/1 days before,
snooze and mark paid.

Nothing here pays, invests or moves anything. Marking one paid records that the
user says it's paid and, if it counts as spending, logs it as an expense; one that
doesn't (money moved, not spent) is only marked done. A scheduled move (not spending,
pointing at a wallet) also logs the move from Spending to that wallet, unless one like
it is already logged.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import duplicates as duplicate_cases
from nexus.application import scheduled_moves as moves
from nexus.application import transactions as tx_cases
from nexus.application import wallets as wallet_cases
from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.ports import UnitOfWork
from nexus.application.transactions import NewTransaction
from nexus.domain.duplicates import Candidate
from nexus.domain.errors import DuplicateSource, InvalidInput, NotFound
from nexus.domain.ledger import (
    Direction,
    Source,
    Transaction,
    User,
    UserId,
    Wallet,
    WalletKind,
    clean_name,
)
from nexus.domain.money import Money, minor_units
from nexus.domain.planning import (
    OVERDUE_GRACE,
    Bill,
    BillOccurrence,
    Cadence,
    due_dates,
    reminder_offset,
)

# Far enough ahead to find the next due date of any cadence.
_LOOKAHEAD = timedelta(days=400)
SNOOZE = timedelta(days=1)
# A scheduled move that hasn't shown up this long after its due date is worth asking about,
# for this long (older ones are let go).
MISSED_AFTER = timedelta(days=3)
MISSED_WITHIN = timedelta(days=35)


@dataclass(frozen=True, slots=True)
class BillView:
    """A bill with its current due date: the earliest unpaid one, counting dates up
    to a week overdue."""

    bill: Bill
    due: date
    occurrence: BillOccurrence | None  # stored state for that date, if any
    today: date

    @property
    def days_until(self) -> int:
        return (self.due - self.today).days

    def snoozed(self, now: datetime) -> bool:
        until = self.occurrence.snoozed_until if self.occurrence else None
        return until is not None and until > now


def _today(user: User, now: datetime) -> date:
    return now.astimezone(ZoneInfo(user.timezone)).date()


async def _view(tx: UnitOfWork, bill: Bill, today: date) -> BillView | None:
    since = today - OVERDUE_GRACE
    stored = {o.due: o for o in await tx.planning.occurrences(bill.user_id, bill.id, since)}
    for day in due_dates(bill.anchor, bill.cadence, since, today + _LOOKAHEAD):
        occurrence = stored.get(day)
        if occurrence is None or (occurrence.paid_at is None and occurrence.skipped_at is None):
            return BillView(bill, day, occurrence, today)
    return None  # a one-off bill that's paid or long past


async def _target(tx: UnitOfWork, bill: Bill, today: date, due: date | None) -> BillView | None:
    """The occurrence to act on: the current one, or the given due date (which must be one
    of the bill's and not already marked done or skipped)."""
    if due is None:
        return await _view(tx, bill, today)
    if due not in due_dates(bill.anchor, bill.cadence, due, due):
        raise InvalidInput(f"{bill.name} isn't due on {due:%-d %b %Y}")
    stored = next(
        (o for o in await tx.planning.occurrences(bill.user_id, bill.id, due) if o.due == due), None
    )
    if stored is not None and (stored.paid_at is not None or stored.skipped_at is not None):
        raise InvalidInput(f"{bill.name} on {due:%-d %b} is already marked done or skipped")
    return BillView(bill, due, stored, today)


def describe_due(view: BillView) -> str:
    when = view.due.strftime("%a %-d %b")
    match view.days_until:
        case 0:
            return f"due today ({when})"
        case 1:
            return f"due tomorrow ({when})"
        case n if n < 0:
            return f"overdue since {when}"
        case n:
            return f"due in {n} days ({when})"


def _label(bill: Bill) -> str:
    return f"{bill.name} ({bill.amount})" if bill.amount else bill.name


def done_word(bill: Bill) -> str:
    """What marking it off is called: spending is paid, money moved is done."""
    return "paid" if bill.spending else "done"


async def add_bill(
    uow: UnitOfWork,
    user: User,
    name: str,
    due: date,
    cadence: Cadence,
    amount: Money | None,
    *,
    now: datetime,
    spending: bool = True,
    wallet_id: UUID | None = None,
) -> Bill:
    """Remember a scheduled payment. With ``wallet_id`` it is a scheduled move of money
    from Spending to that wallet, so it can't count as spending."""
    if amount is not None and not amount.is_positive:
        raise InvalidInput("a bill's amount must be more than zero")
    if due < _today(user, now) - OVERDUE_GRACE and cadence is Cadence.ONCE:
        raise InvalidInput("that due date has already passed")
    if wallet_id is not None and spending:
        raise InvalidInput("a bill that counts as spending can't move money to a wallet")
    bill = Bill(
        uuid4(),
        user.id,
        clean_name(name, field_name="bill name"),
        amount,
        cadence,
        due,
        now,
        spending=spending,
        wallet_id=wallet_id,
    )
    async with uow:
        if wallet_id is not None:
            target = await wallet_cases.require_wallet(uow.ledger, user.id, wallet_id)
            if target.kind is WalletKind.SPENDING:
                raise InvalidInput("a scheduled move goes to a wallet other than Spending")
        await uow.planning.insert_bill(bill)
        await uow.commit()
    return bill


async def set_bill_wallet(
    uow: UnitOfWork, user: User, bill_id: UUID, wallet_id: UUID | None
) -> Bill:
    """Point an existing bill at a wallet, making it a scheduled move, or at none. A bill
    that counts as spending can't have one, and the wallet can't be Spending."""
    async with uow:
        bill = await _bill(uow, user.id, bill_id)
        if wallet_id is not None:
            if bill.spending:
                raise InvalidInput("a bill that counts as spending can't move money to a wallet")
            target = await wallet_cases.require_wallet(uow.ledger, user.id, wallet_id)
            if target.kind is WalletKind.SPENDING:
                raise InvalidInput("a scheduled move goes to a wallet other than Spending")
        await uow.planning.set_bill_wallet(user.id, bill.id, wallet_id)
        await uow.commit()
    return replace(bill, wallet_id=wallet_id)


async def list_bills(uow: UowFactory, user: User, *, now: datetime) -> list[BillView]:
    """Active bills by their current due date."""
    today = _today(user, now)
    async with uow() as tx:
        views = [await _view(tx, b, today) for b in await tx.planning.list_bills(user.id)]
    return sorted((v for v in views if v is not None), key=lambda v: (v.due, v.bill.name))


async def _bill(tx: UnitOfWork, actor: UserId, bill_id: UUID) -> Bill:
    bill = await tx.planning.get_bill(actor, bill_id)
    if bill is None or bill.archived_at is not None:
        raise NotFound("bill not found")
    return bill


BILLS_CATEGORY = "Bills & Utilities"


@dataclass(frozen=True, slots=True)
class Paid:
    """A bill marked paid, and what happened in the ledger."""

    view: BillView
    logged: Transaction | None  # the expense logged now
    already: Transaction | None  # an expense already in the ledger that looks like this payment
    amount: Money | None  # what was paid, when known
    # For a scheduled move: where it goes, the move logged now, and one already in the
    # ledger that looks like it.
    wallet: Wallet | None = None
    moved: Transaction | None = None
    already_moved: Transaction | None = None

    def message(self, tz: ZoneInfo) -> str:
        bill = self.view.bill
        head = f"Marked {bill.name} ({self.view.due:%-d %b}) as {done_word(bill)}"
        if not bill.spending:
            if self.wallet is None:
                return f"{head}. It doesn't count as spending, so nothing was logged."
            return self._move_message(head, self.wallet, tz)
        if self.logged is not None:
            return f"{head} and logged {self.logged.amount} in this month's spending."
        if self.already is not None:
            when = self.already.occurred_at.astimezone(tz)
            return (
                f"{head}. It's already in your spending: {self.already.amount} on "
                f"{when:%-d %b}, so I didn't log it again."
            )
        return (
            f"{head}. It has no set amount, so nothing was added to your spending; tell me "
            "how much it was to log it."
        )

    def _move_message(self, head: str, wallet: Wallet, tz: ZoneInfo) -> str:
        if self.moved is not None:
            return (
                f"{head} and logged a move of {self.moved.amount} from Spending to {wallet.name}."
            )
        if self.already_moved is not None:
            when = self.already_moved.occurred_at.astimezone(tz)
            return (
                f"{head}. The move is already logged: {self.already_moved.amount} to "
                f"{wallet.name} on {when:%-d %b}, so I didn't log it again."
            )
        if self.amount is None:
            return (
                f"{head}. It has no set amount, so no move was logged; tell me how much it "
                "was to log it."
            )
        return f"{head}. That move was already logged, so I didn't log it again."


async def mark_paid(
    uow: UowFactory,
    user: User,
    bill_id: UUID,
    *,
    now: datetime,
    amount: Money | None = None,
    due: date | None = None,
) -> Paid:
    """Mark the current due date (or the given one) paid and log what was paid as an
    expense, so it counts in the month's spending. Nothing is paid by the app. If a
    matching expense is already in the ledger (from email or a statement), it isn't
    logged twice; a bill with no amount is logged only when the user gives one. One that
    doesn't count as spending (an investment, a transfer to savings) is only marked done,
    unless it moves money to a wallet: then the move from Spending to that wallet is
    logged, once, unless one like it is already there."""
    async with uow() as tx:
        view = await _target(tx, await _bill(tx, user.id, bill_id), _today(user, now), due)
        if view is None:
            raise InvalidInput("that bill has nothing left to pay")
        if amount is not None and not amount.is_positive:
            raise InvalidInput("an amount must be more than zero")
        current = view.occurrence or BillOccurrence(uuid4(), user.id, bill_id, view.due)
        await tx.planning.save_occurrence(
            replace(current, paid_at=now, snoozed_until=None, skipped_at=None)
        )
        categories = await tx.ledger.list_categories(user.id)
        await tx.commit()
    money = amount or view.bill.amount
    if not view.bill.spending:
        if view.bill.wallet_id is None:
            return Paid(view, None, None, money)
        return await _log_scheduled_move(uow, user, view, money, now)
    if money is None:
        return Paid(view, None, None, None)
    found = await duplicate_cases.check(
        uow(),
        user,
        Candidate(Direction.OUT, money, now, view.bill.name, Source.MANUAL, None),
        any_source=True,
    )
    if found is not None:
        return Paid(view, None, found, money)
    category = next((c.id for c in categories if c.name == BILLS_CATEGORY), None)
    try:
        logged = await tx_cases.log_transaction(
            uow(),
            user.id,
            NewTransaction(
                direction=Direction.OUT,
                amount=money,
                occurred_at=now,
                counterparty=view.bill.name,
                notes=f"Bill due {view.due:%-d %b %Y}",
                external_id=f"bill:{bill_id}:{view.due.isoformat()}",
                fallback_category_id=category,
            ),
        )
    except DuplicateSource:
        return Paid(view, None, None, money)
    return Paid(view, logged, None, money)


async def _log_scheduled_move(
    uow: UowFactory, user: User, view: BillView, money: Money | None, now: datetime
) -> Paid:
    """Log the move a scheduled move stands for, from Spending to its wallet: dated now, or
    on its due date when that has passed (confirmed late, it belongs to that day's month).
    Not when a move like it is already logged, and the same due date only once (the
    external id)."""
    bill = view.bill
    if bill.wallet_id is None:  # pragma: no cover - the caller checked
        return Paid(view, None, None, money)
    async with uow() as tx:
        wallet = await wallet_cases.require_wallet(tx.ledger, user.id, bill.wallet_id)
        existing = (
            await moves.find_matching_move(
                tx.ledger,
                user.id,
                to_wallet_id=wallet.id,
                amount=money,
                due=view.due,
                tz=ZoneInfo(user.timezone),
            )
            if money is not None
            else None
        )
    if money is None:
        return Paid(view, None, None, None, wallet)
    if existing is not None:
        return Paid(view, None, None, money, wallet, None, existing)
    try:
        moved = await wallet_cases.log_move(
            uow(),
            user.id,
            amount=money,
            to_wallet_id=wallet.id,
            occurred_at=_moved_at(view.due, user, now),
            counterparty=bill.name,
            notes=f"Scheduled payment due {view.due:%-d %b %Y}",
            external_id=f"bill:{bill.id}:{view.due.isoformat()}",
        )
    except DuplicateSource:
        return Paid(view, None, None, money, wallet)
    return Paid(view, None, None, money, wallet, moved)


def _moved_at(due: date, user: User, now: datetime) -> datetime:
    """Now, or noon on the due date when that's an earlier day."""
    tz = ZoneInfo(user.timezone)
    if due >= now.astimezone(tz).date():
        return now
    return datetime.combine(due, time(12), tzinfo=tz)


async def snooze(uow: UowFactory, user: User, bill_id: UUID, *, now: datetime) -> BillView:
    """Hold reminders for a day; then the current one is sent again."""
    async with uow() as tx:
        view = await _view(tx, await _bill(tx, user.id, bill_id), _today(user, now))
        if view is None:
            raise InvalidInput("that bill has nothing left to pay")
        current = view.occurrence or BillOccurrence(uuid4(), user.id, bill_id, view.due)
        await tx.planning.save_occurrence(
            replace(current, snoozed_until=now + SNOOZE, reminded_offset=None)
        )
        await tx.commit()
    return view


async def skip(
    uow: UowFactory, user: User, bill_id: UUID, *, now: datetime, due: date | None = None
) -> BillView:
    """Say this due date (the current one, or the given one) isn't happening: nothing is
    logged, the reminders stop, and the next due date takes over."""
    async with uow() as tx:
        view = await _target(tx, await _bill(tx, user.id, bill_id), _today(user, now), due)
        if view is None:
            raise InvalidInput("that bill has nothing left to skip")
        current = view.occurrence or BillOccurrence(uuid4(), user.id, bill_id, view.due)
        await tx.planning.save_occurrence(replace(current, skipped_at=now, snoozed_until=None))
        await tx.commit()
    return view


async def occurrence_bill(uow: UnitOfWork, actor: UserId, occurrence_id: UUID) -> UUID | None:
    """The bill a reminder's button refers to, if it's still this user's to act on."""
    async with uow:
        occurrence = await uow.planning.get_occurrence(actor, occurrence_id)
        if occurrence is None or occurrence.paid_at is not None or occurrence.skipped_at:
            return None
        return occurrence.bill_id


async def remove_bill(uow: UnitOfWork, actor: UserId, bill_id: UUID, *, now: datetime) -> None:
    async with uow:
        if not await uow.planning.archive_bill(actor, bill_id, now):
            raise NotFound("bill not found")
        await uow.commit()


def reminder_text(view: BillView) -> str:
    return f"Reminder: {_label(view.bill)} is {describe_due(view)}."


async def send_reminders(uow: UowFactory, user: User, *, now: datetime) -> int:
    """Queue the reminder due for each bill: the most urgent of 7/3/1 days reached,
    once each, none while snoozed. Returns how many were queued."""
    queued = 0
    for view in await list_bills(uow, user, now=now):
        offset = reminder_offset(view.days_until)
        if offset is None or view.snoozed(now):
            continue
        sent = view.occurrence.reminded_offset if view.occurrence else None
        if sent is not None and offset >= sent:
            continue
        async with uow() as tx:
            current = view.occurrence or BillOccurrence(uuid4(), user.id, view.bill.id, view.due)
            stored = await tx.planning.save_occurrence(replace(current, reminded_offset=offset))
            # A snooze resets the reminder, so it's part of the key.
            round_ = stored.snoozed_until.isoformat() if stored.snoozed_until else "0"
            queued += await tx.jobs.enqueue(
                TELEGRAM_SEND,
                {
                    "user_id": str(user.id),
                    "text": reminder_text(view),
                    "buttons": [
                        [
                            {
                                "label": f"Mark {done_word(view.bill)}",
                                "data": f"bill:paid:{stored.id}",
                            },
                            {"label": "Snooze 1 day", "data": f"bill:snooze:{stored.id}"},
                        ]
                    ],
                },
                dedupe_key=f"bill-reminder:{stored.id}:{offset}:{round_}",
                run_at=now,
            )
            await tx.commit()
    return queued


@dataclass(frozen=True, slots=True)
class MissedMove:
    """A scheduled move whose due date has passed with no sign of the move."""

    bill: Bill
    wallet: Wallet
    due: date
    amount: Money

    def text(self) -> str:
        shown = (
            f"{self.amount.currency} {self.amount.amount:,.{minor_units(self.amount.currency)}f}"
        )
        return (
            f"Your {shown} {self.bill.name} on {self.due:%-d %b} hasn't shown up. "
            "Did it go through?"
        )


async def missed_moves(uow: UowFactory, user: User, *, now: datetime) -> list[MissedMove]:
    """Scheduled moves (with an amount) due three or more days ago, and within the last
    35, that are not marked done or skipped and have no matching move logged. Nothing is
    marked automatically; a snoozed one waits. Oldest first."""
    tz = ZoneInfo(user.timezone)
    today = _today(user, now)
    oldest, newest = today - MISSED_WITHIN, today - MISSED_AFTER
    missed: list[MissedMove] = []
    async with uow() as tx:
        wallets = {w.id: w for w in await tx.ledger.list_wallets(user.id)}
        for bill in await tx.planning.list_bills(user.id):
            wallet = wallets.get(bill.wallet_id) if bill.wallet_id else None
            if wallet is None or bill.amount is None:
                continue
            # Nothing is asked about before the bill was added.
            first = max(oldest, bill.created_at.astimezone(tz).date())
            stored = {o.due: o for o in await tx.planning.occurrences(user.id, bill.id, first)}
            for due in due_dates(bill.anchor, bill.cadence, first, newest):
                occurrence = stored.get(due)
                if occurrence is not None and (
                    occurrence.paid_at is not None
                    or occurrence.skipped_at is not None
                    or (occurrence.snoozed_until is not None and occurrence.snoozed_until > now)
                ):
                    continue
                found = await moves.find_matching_move(
                    tx.ledger, user.id, to_wallet_id=wallet.id, amount=bill.amount, due=due, tz=tz
                )
                if found is None:
                    missed.append(MissedMove(bill, wallet, due, bill.amount))
    return sorted(missed, key=lambda m: (m.due, m.bill.name))
