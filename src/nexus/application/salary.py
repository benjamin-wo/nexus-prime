"""The salary schedule and the payday check-in.

Salary is only ever what the user reports: the schedule and usual amount are
set by the user, and the usual amount changes only after they confirm. Nothing
is inferred from transactions or statements.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from nexus.application import transactions as tx_cases
from nexus.application.budgets import TELEGRAM_SEND, UowFactory
from nexus.application.categories import list_categories
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import Direction, Source, Transaction, User, UserId
from nexus.domain.money import Money
from nexus.domain.planning import (
    PAYDAY_CHECKIN,
    PayRule,
    SalarySchedule,
    next_payday,
    paydays,
)


@dataclass(frozen=True, slots=True)
class PayView:
    schedule: SalarySchedule
    next_payday: date
    today: date

    @property
    def days_until(self) -> int:
        return (self.next_payday - self.today).days


def _today(user: User, now: datetime) -> date:
    return now.astimezone(ZoneInfo(user.timezone)).date()


def describe_rule(schedule: SalarySchedule) -> str:
    match schedule.rule:
        case PayRule.MONTHLY_DAY:
            day = schedule.day or 1
            suffix = (
                "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            )
            return f"the {day}{suffix} of each month"
        case PayRule.LAST_WEEKDAY:
            return "the last weekday of each month"
        case PayRule.BIWEEKLY:
            return "every two weeks"


async def set_schedule(
    uow: UnitOfWork,
    user: User,
    rule: PayRule,
    *,
    day: int | None = None,
    anchor: date | None = None,
    now: datetime,
) -> SalarySchedule:
    """Set when the user is paid. Keeps their usual amount."""
    async with uow:
        existing = await uow.planning.get_salary_schedule(user.id)
        try:
            schedule = SalarySchedule(
                user.id,
                rule,
                day if rule is PayRule.MONTHLY_DAY else None,
                anchor if rule is PayRule.BIWEEKLY else None,
                existing.baseline if existing else None,
                existing.created_at if existing else now,
                now,
            )
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        await uow.planning.save_salary_schedule(schedule)
        await uow.commit()
    return schedule


async def set_baseline(uow: UnitOfWork, user: User, amount: Money, *, now: datetime) -> None:
    """Change the usual salary. Callers get the user's confirmation first."""
    if not amount.is_positive:
        raise InvalidInput("a salary must be more than zero")
    async with uow:
        schedule = await uow.planning.get_salary_schedule(user.id)
        if schedule is None:
            raise InvalidInput("set when you're paid first")
        await uow.planning.save_salary_schedule(replace(schedule, baseline=amount, updated_at=now))
        await uow.commit()


async def remove_schedule(uow: UnitOfWork, actor: UserId) -> None:
    async with uow:
        if not await uow.planning.delete_salary_schedule(actor):
            raise NotFound("no pay schedule set")
        await uow.commit()


async def view(uow: UnitOfWork, user: User, *, now: datetime) -> PayView | None:
    async with uow:
        schedule = await uow.planning.get_salary_schedule(user.id)
    if schedule is None:
        return None
    today = _today(user, now)
    return PayView(schedule, next_payday(schedule, today), today)


def baseline_question(schedule: SalarySchedule | None, reported: Money) -> str | None:
    """After the user reports a salary: whether to ask about changing the usual amount."""
    if schedule is None or reported == schedule.baseline:
        return None
    if schedule.baseline is None:
        return f"Save {reported} as your usual salary?"
    return (
        f"That's different from your usual {schedule.baseline}. Make {reported} your usual salary?"
    )


async def payday_checkin(uow: UowFactory, user: User, *, now: datetime) -> int:
    """On payday, from 09:00, queue one cheerful check-in. Returns 1 if queued."""
    local = now.astimezone(ZoneInfo(user.timezone))
    today = local.date()
    async with uow() as tx:
        schedule = await tx.planning.get_salary_schedule(user.id)
        if schedule is None or local.timetz().replace(tzinfo=None) < PAYDAY_CHECKIN:
            return 0
        if paydays(schedule, today, today) != [today]:
            return 0
        if schedule.baseline is not None:
            text = (
                f"It's payday! 🎉 Has your salary of {schedule.baseline} come in? "
                "Tap to log it, or tell me the amount if it's different."
            )
            buttons = [
                [
                    {
                        "label": f"Log {schedule.baseline}",
                        "data": f"salary:log:{today.isoformat()}",
                    },
                    {"label": "Not yet", "data": "salary:later"},
                ]
            ]
        else:
            text = (
                "It's payday! 🎉 Once your salary is in, tell me the amount "
                "(like 'salary 5000') and I'll log it."
            )
            buttons = []
        queued = await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {"user_id": str(user.id), "text": text, "buttons": buttons},
            dedupe_key=f"payday:{user.id}:{today.isoformat()}",
            run_at=now,
        )
        await tx.commit()
    return int(queued)


async def log_payday_salary(
    uow: UowFactory, user: User, day: date, *, now: datetime
) -> Transaction:
    """The check-in's "Log" button: record the usual salary once for that payday.

    Raises DuplicateSource if it's already logged for that day.
    """
    async with uow() as tx:
        schedule = await tx.planning.get_salary_schedule(user.id)
    if schedule is None or schedule.baseline is None:
        raise InvalidInput("there's no usual salary to log; tell me the amount instead")
    income = next(
        (c.id for c in await list_categories(uow(), user.id) if c.name.casefold() == "income"), None
    )
    return await tx_cases.log_transaction(
        uow(),
        user.id,
        tx_cases.NewTransaction(
            direction=Direction.IN,
            amount=schedule.baseline,
            occurred_at=now,
            category_id=income,
            notes="Salary",
            source=Source.MANUAL,
            external_id=f"payday:{day.isoformat()}",
        ),
    )
