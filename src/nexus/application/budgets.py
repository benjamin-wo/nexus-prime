"""Monthly budgets: set, remove, progress this month, and alerts at 50/80/100%.

Budgets are in the user's home currency and measured against this month's
confirmed spending, with foreign amounts converted at their day's rate (the
same figures as the dashboard). The limit is the same every month; nothing
rolls over.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from nexus.application import categories as category_cases
from nexus.application import transactions as tx_cases
from nexus.application.categories import require_category
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput, NotFound
from nexus.domain.ledger import User, UserId
from nexus.domain.money import Money
from nexus.domain.planning import Budget, month_start, next_month_start, reached

type UowFactory = Callable[[], UnitOfWork]

TELEGRAM_SEND = "telegram.send"


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    budget: Budget
    name: str  # "Overall" or the category's name
    spent: Money  # this month, in the home currency
    unconverted: list[Money]  # foreign spending left out for want of a rate (overall only)

    @property
    def percent(self) -> int:
        """Whole percent used, rounded down (so 99.9% shows as 99)."""
        return int(self.spent.amount * 100 // self.budget.limit.amount)

    @property
    def remaining(self) -> Money:
        return self.budget.limit - self.spent


def _month(user: User, now: datetime) -> tuple[date, datetime, datetime]:
    tz = ZoneInfo(user.timezone)
    first = month_start(now.astimezone(tz).date())
    return (
        first,
        datetime.combine(first, time(), tzinfo=tz),
        datetime.combine(next_month_start(first), time(), tzinfo=tz),
    )


async def set_budget(
    uow: UnitOfWork, user: User, category_id: UUID | None, limit: Money, *, now: datetime
) -> Budget:
    """Create or change the monthly limit, overall (no category) or for one category."""
    if limit.currency != user.home_currency:
        raise InvalidInput(f"budgets are in your home currency ({user.home_currency})")
    if not limit.is_positive:
        raise InvalidInput("a budget must be more than zero")
    async with uow:
        if category_id is not None:
            await require_category(uow.ledger, user.id, category_id)
        stored = await uow.planning.upsert_budget(
            Budget(uuid4(), user.id, category_id, limit, now, now)
        )
        await uow.commit()
    return stored


async def remove_budget(uow: UnitOfWork, actor: UserId, budget_id: UUID) -> None:
    async with uow:
        if not await uow.planning.delete_budget(actor, budget_id):
            raise NotFound("budget not found")
        await uow.commit()


async def budget_statuses(
    uow: UowFactory, rates: RateSource, user: User, *, now: datetime
) -> list[BudgetStatus]:
    """Each budget with what has been spent against it this month."""
    async with uow() as tx:
        budgets = await tx.planning.list_budgets(user.id)
    if not budgets:
        return []
    names = {
        c.id: c.name
        for c in await category_cases.list_categories(uow(), user.id, include_inactive=True)
    }
    _, start, end = _month(user, now)
    summary = await tx_cases.summarize_in_home(uow(), rates, user, start, end)
    out = summary.totals[0]
    by_category = {c.category_id: c.total for c in summary.spending_by_category}
    statuses = []
    for b in budgets:
        if b.limit.currency != summary.currency:
            continue  # set before the home currency changed; not comparable
        if b.is_overall:
            statuses.append(BudgetStatus(b, "Overall", out.total, out.unconverted))
        else:
            spent = by_category.get(b.category_id, Money.zero(summary.currency))
            name = names.get(b.category_id, "Category") if b.category_id else "Category"
            statuses.append(BudgetStatus(b, name, spent, []))
    return statuses


def alert_text(status: BudgetStatus, threshold: int, month: date) -> str:
    what = "overall budget" if status.budget.is_overall else f"{status.name} budget"
    when = month.strftime("%B")
    used = f"{status.spent} of {status.budget.limit}"
    if threshold >= 100:
        return f"You've reached your {what} for {when}: {used} ({status.percent}%)."
    return f"You've used {threshold}% of your {what} for {when}: {used}."


async def check_budgets(uow: UowFactory, rates: RateSource, user: User, *, now: datetime) -> int:
    """Record newly reached thresholds and queue one message per budget for the
    highest. Idempotent: a threshold is alerted once per budget per month.
    Returns how many messages were queued."""
    statuses = await budget_statuses(uow, rates, user, now=now)
    month, _, _ = _month(user, now)
    queued = 0
    async with uow() as tx:
        for status in statuses:
            budget = status.budget
            new = await tx.planning.record_alerts(
                user.id, budget.id, month, reached(status.spent, budget.limit), now
            )
            if not new:
                continue
            top = max(new)
            queued += await tx.jobs.enqueue(
                TELEGRAM_SEND,
                {"user_id": str(user.id), "text": alert_text(status, top, month)},
                dedupe_key=f"budget-alert:{budget.id}:{month.isoformat()}:{top}",
                run_at=now,
            )
        await tx.commit()
    return queued
