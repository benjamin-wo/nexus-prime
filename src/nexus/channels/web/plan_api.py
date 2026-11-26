"""Web API: budgets, bills, salary, cash flow and subscriptions."""

from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from nexus.application import bills as bill_cases
from nexus.application import budgets as budget_cases
from nexus.application import cashflow as cashflow_cases
from nexus.application import salary as salary_cases
from nexus.application import subscriptions as subscription_cases
from nexus.application import transactions as tx_cases
from nexus.application import wallet_figures as figure_cases
from nexus.application import wallets as wallet_cases
from nexus.channels.web.security import (
    Auth,
    Runtime,
)
from nexus.channels.web.shapes import Model, MoneyOut, _tz, money
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import (
    Wallet,
)
from nexus.domain.money import Money
from nexus.domain.planning import MAX_PAYER, Cadence, PayRule, next_month_start

router = APIRouter(prefix="/api")

# --- budgets --------------------------------------------------------------------------


class BudgetOut(Model):
    id: UUID
    category_id: UUID | None
    name: str
    limit: MoneyOut
    spent: MoneyOut
    remaining: MoneyOut
    percent: int
    unconverted: list[MoneyOut]


@router.get("/budgets")
async def budgets(
    auth: Auth,
    web: Runtime,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> list[BudgetOut]:
    """Each budget against this month's spending, or against ``month`` (``2026-10``,
    not a future one) at today's limits."""
    user = auth.user
    now = web.clock()
    first: date | None = None
    if month:
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise InvalidInput("month must be a real month, like 2026-10") from exc
        if first > now.astimezone(_tz(user)).date().replace(day=1):
            raise InvalidInput("month can't be in the future")
    statuses = await budget_cases.budget_statuses(web.uow, web.rates, user, now=now, month=first)
    return [
        BudgetOut(
            id=s.budget.id,
            category_id=s.budget.category_id,
            name=s.name,
            limit=money(s.budget.limit),
            spent=money(s.spent),
            remaining=money(s.remaining),
            percent=s.percent,
            unconverted=[money(m) for m in s.unconverted],
        )
        for s in statuses
    ]


class MonthPlanOut(Model):
    """Left to spend this month: income - total_out - still_due_out (home currency)."""

    currency: str
    total_out: MoneyOut  # spent so far, plus moved from the main account to anything but a card
    left_to_spend: MoneyOut  # can be negative
    still_due_out: MoneyOut  # bills, subscriptions and trip set-asides still ahead this month
    income: MoneyOut  # received so far, plus salary still due before month end
    budget_left: MoneyOut | None  # overall budget less spending so far; null without one
    spending_due: MoneyOut  # still-due bills that are spending, and subscriptions
    # budget_left less spending_due: what the budget has once those are paid (can be negative);
    # null without a budget.
    budget_left_after_due: MoneyOut | None
    # The lower of budget_left_after_due and left_to_spend; null without a budget.
    tighter: Literal["budget", "left_to_spend"] | None
    plan_warning: str | None  # the budget plus scheduled moves outgrow usual income
    skipped: list[str]  # scheduled items left out for want of an amount or a rate


@router.get("/budgets/month")
async def budgets_month(auth: Auth, web: Runtime) -> MonthPlanOut:
    """Where this month stands. Separate from ``/budgets``, whose list shape stays."""
    plan = await figure_cases.month_plan(web.uow, web.rates, auth.user, now=web.clock())
    return MonthPlanOut(
        currency=plan.currency,
        total_out=money(plan.total_out),
        left_to_spend=money(plan.left_to_spend),
        still_due_out=money(plan.still_due_out),
        income=money(plan.income),
        budget_left=money(plan.budget_left) if plan.budget_left is not None else None,
        spending_due=money(plan.spending_due),
        budget_left_after_due=(
            money(plan.budget_left_after_due) if plan.budget_left_after_due is not None else None
        ),
        tighter=plan.tighter,
        plan_warning=plan.plan_warning,
        skipped=plan.skipped,
    )


class BudgetIn(Model):
    category_id: UUID | None = None
    amount: str = Field(max_length=32)


@router.put("/budgets", status_code=204)
async def set_budget(body: BudgetIn, auth: Auth, web: Runtime) -> None:
    user = auth.user
    limit = Money.of(body.amount.replace(",", ""), user.home_currency)
    await budget_cases.set_budget(web.uow(), user, body.category_id, limit, now=web.clock())


@router.delete("/budgets/{budget_id}", status_code=204)
async def remove_budget(budget_id: UUID, auth: Auth, web: Runtime) -> None:
    await budget_cases.remove_budget(web.uow(), auth.user.id, budget_id)


# --- bills ----------------------------------------------------------------------------


class BillWalletOut(Model):
    id: UUID
    name: str
    kind: str


class BillOut(Model):
    id: UUID
    name: str
    spending: bool  # marking it paid logs an expense; False for money moved, not spent
    wallet: BillWalletOut | None  # a scheduled move's destination; never set on spending
    amount: MoneyOut | None
    cadence: str
    due: date
    days_until: int
    snoozed: bool


def bill_out(view: bill_cases.BillView, now: datetime, wallets: dict[UUID, Wallet]) -> BillOut:
    bill = view.bill
    wallet = wallets.get(bill.wallet_id) if bill.wallet_id else None
    return BillOut(
        id=bill.id,
        name=bill.name,
        spending=bill.spending,
        wallet=BillWalletOut(id=wallet.id, name=wallet.name, kind=wallet.kind.value)
        if wallet
        else None,
        amount=money(bill.amount) if bill.amount else None,
        cadence=bill.cadence.value,
        due=view.due,
        days_until=view.days_until,
        snoozed=view.snoozed(now),
    )


@router.get("/bills")
async def bills(auth: Auth, web: Runtime) -> list[BillOut]:
    now = web.clock()
    wallet_names = {w.id: w for w in await wallet_cases.list_wallets(web.uow(), auth.user.id)}
    views = await bill_cases.list_bills(web.uow, auth.user, now=now)
    return [bill_out(v, now, wallet_names) for v in views]


class BillIn(Model):
    name: str = Field(min_length=1, max_length=100)
    due: date
    cadence: Literal["once", "weekly", "monthly", "yearly"] = "monthly"
    spending: bool = True
    # Makes it a scheduled move to this wallet; refused (422) on a spending bill.
    wallet_id: UUID | None = None
    amount: str | None = Field(None, max_length=32)
    currency: str | None = Field(None, max_length=3)


@router.post("/bills", status_code=201)
async def add_bill(body: BillIn, auth: Auth, web: Runtime) -> BillOut:
    user, now = auth.user, web.clock()
    amount = (
        Money.of(body.amount.replace(",", ""), body.currency or user.home_currency)
        if body.amount and body.amount.strip()
        else None
    )
    bill = await bill_cases.add_bill(
        web.uow(),
        user,
        body.name,
        body.due,
        Cadence(body.cadence),
        amount,
        now=now,
        spending=body.spending,
        wallet_id=body.wallet_id,
    )
    today = now.astimezone(_tz(user)).date()
    wallet_names = {w.id: w for w in await wallet_cases.list_wallets(web.uow(), user.id)}
    return bill_out(bill_cases.BillView(bill, body.due, None, today), now, wallet_names)


class BillPatch(Model):
    # Only the wallet can change: a wallet makes it a scheduled move, null unlinks it.
    wallet_id: UUID | None


@router.patch("/bills/{bill_id}")
async def patch_bill(bill_id: UUID, body: BillPatch, auth: Auth, web: Runtime) -> BillOut:
    user, now = auth.user, web.clock()
    bill = await bill_cases.set_bill_wallet(web.uow(), user, bill_id, body.wallet_id)
    views = await bill_cases.list_bills(web.uow, user, now=now)
    view = next(
        (v for v in views if v.bill.id == bill.id),
        bill_cases.BillView(bill, bill.anchor, None, now.astimezone(_tz(user)).date()),
    )
    wallet_names = {w.id: w for w in await wallet_cases.list_wallets(web.uow(), user.id)}
    return bill_out(view, now, wallet_names)


class BillPaidIn(Model):
    amount: str | None = Field(None, max_length=32)
    currency: str | None = Field(None, max_length=3)


class BillPaidOut(Model):
    message: str
    logged: bool  # a new expense was added for it
    moved: bool  # a scheduled move: the move to its wallet was logged now
    # spending, or a scheduled move, with no set amount and none given: nothing was logged
    needs_amount: bool


@router.post("/bills/{bill_id}/paid")
async def bill_paid(
    bill_id: UUID, auth: Auth, web: Runtime, body: BillPaidIn | None = None, due: date | None = None
) -> BillPaidOut:
    """Mark the current due date paid (done, for money moved), or the one on ``due``; a
    scheduled move logs the move to its wallet unless one like it is already there."""
    user = auth.user
    amount = (
        Money.of(body.amount.replace(",", ""), body.currency or user.home_currency)
        if body and body.amount and body.amount.strip()
        else None
    )
    paid = await bill_cases.mark_paid(
        web.uow, user, bill_id, now=web.clock(), amount=amount, due=due
    )
    bill = paid.view.bill
    return BillPaidOut(
        message=paid.message(_tz(user)),
        logged=paid.logged is not None,
        moved=paid.moved is not None,
        needs_amount=paid.amount is None and (bill.spending or bill.wallet_id is not None),
    )


@router.post("/bills/{bill_id}/snooze", status_code=204)
async def snooze_bill(bill_id: UUID, auth: Auth, web: Runtime) -> None:
    await bill_cases.snooze(web.uow, auth.user, bill_id, now=web.clock())


@router.post("/bills/{bill_id}/skip", status_code=204)
async def skip_bill(bill_id: UUID, auth: Auth, web: Runtime, due: date | None = None) -> None:
    """Say the current due date (or the one on ``due``) isn't happening: nothing is logged."""
    await bill_cases.skip(web.uow, auth.user, bill_id, now=web.clock(), due=due)


@router.delete("/bills/{bill_id}", status_code=204)
async def remove_bill(bill_id: UUID, auth: Auth, web: Runtime) -> None:
    await bill_cases.remove_bill(web.uow(), auth.user.id, bill_id, now=web.clock())


# --- salary ---------------------------------------------------------------------------


class SalaryOut(Model):
    rule: str
    day: int | None
    anchor: date | None
    description: str
    usual: MoneyOut | None
    payer: str | None
    # Earlier salaries with no name, which "fill in" could put the payer on (0 with no payer).
    unnamed_salaries: int
    next_payday: date
    days_until: int


@router.get("/salary")
async def salary(auth: Auth, web: Runtime) -> SalaryOut | None:
    view = await salary_cases.view(web.uow(), auth.user, now=web.clock())
    if view is None:
        return None
    s = view.schedule
    unnamed = await salary_cases.count_unnamed(web.uow(), auth.user) if s.payer else 0
    return SalaryOut(
        rule=s.rule.value,
        day=s.day,
        anchor=s.anchor,
        description=salary_cases.describe_rule(s),
        usual=money(s.baseline) if s.baseline else None,
        payer=s.payer,
        unnamed_salaries=unnamed,
        next_payday=view.next_payday,
        days_until=view.days_until,
    )


class SalaryIn(Model):
    rule: Literal["monthly_day", "last_weekday", "biweekly"]
    day: int | None = Field(None, ge=1, le=31)
    anchor: date | None = None
    # Who pays you. Left out keeps the saved name; null (or blank) clears it.
    payer: str | None = Field(None, max_length=MAX_PAYER)


@router.put("/salary", status_code=204)
async def set_salary_schedule(body: SalaryIn, auth: Auth, web: Runtime) -> None:
    await salary_cases.set_schedule(
        web.uow(),
        auth.user,
        PayRule(body.rule),
        day=body.day,
        anchor=body.anchor,
        payer=body.payer if "payer" in body.model_fields_set else tx_cases.UNSET,
        now=web.clock(),
    )


class NamedSalariesOut(Model):
    named: int


@router.post("/salary/name-earlier")
async def name_earlier_salaries(auth: Auth, web: Runtime) -> NamedSalariesOut:
    """The Payday page's "fill in the earlier salaries" button."""
    named = await salary_cases.name_unnamed(web.uow(), auth.user, now=web.clock())
    return NamedSalariesOut(named=named)


class UsualSalaryIn(Model):
    amount: str = Field(max_length=32)


@router.put("/salary/usual", status_code=204)
async def set_usual_salary(body: UsualSalaryIn, auth: Auth, web: Runtime) -> None:
    """Saving the form is the user's confirmation."""
    user = auth.user
    amount = Money.of(body.amount.replace(",", ""), user.home_currency)
    await salary_cases.set_baseline(web.uow(), user, amount, now=web.clock())


@router.delete("/salary", status_code=204)
async def remove_salary(auth: Auth, web: Runtime) -> None:
    await salary_cases.remove_schedule(web.uow(), auth.user.id)


# --- cash flow --------------------------------------------------------------------------


class ExpectedOut(Model):
    kind: str
    name: str
    direction: str
    amount: MoneyOut | None
    home: MoneyOut | None


class CashDayOut(Model):
    day: date
    money_in: MoneyOut
    money_out: MoneyOut
    net: MoneyOut
    expected: list[ExpectedOut]
    expected_net: MoneyOut


class CashFlowOut(Model):
    start: date
    end: date
    today: date
    currency: str
    days: list[CashDayOut]
    logged_in: MoneyOut
    logged_out: MoneyOut
    expected_in: MoneyOut
    expected_out: MoneyOut
    unknown_amounts: int
    unconverted: list[MoneyOut]


@router.get("/cashflow")
async def cashflow(
    auth: Auth,
    web: Runtime,
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> CashFlowOut:
    """One month, day by day: what was logged so far, and what's expected ahead."""
    user = auth.user
    now = web.clock()
    if month:
        try:
            first = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise InvalidInput("month must be a real month, like 2026-10") from exc
    else:
        first = now.astimezone(_tz(user)).date().replace(day=1)
    last = next_month_start(first) - timedelta(days=1)
    flow = await cashflow_cases.cash_flow(web.uow, web.rates, user, first, last, now=now)
    return CashFlowOut(
        start=flow.start,
        end=flow.end,
        today=flow.today,
        currency=flow.currency,
        days=[
            CashDayOut(
                day=d.day,
                money_in=money(d.money_in),
                money_out=money(d.money_out),
                net=money(d.net),
                expected=[
                    ExpectedOut(
                        kind=e.kind.value,
                        name=e.name,
                        direction=e.direction.value,
                        amount=money(e.amount) if e.amount else None,
                        home=money(e.home) if e.home else None,
                    )
                    for e in d.expected
                ],
                expected_net=money(d.expected_net),
            )
            for d in flow.days
        ],
        logged_in=money(flow.logged_in),
        logged_out=money(flow.logged_out),
        expected_in=money(flow.expected_in),
        expected_out=money(flow.expected_out),
        unknown_amounts=flow.unknown_amounts,
        unconverted=[money(m) for m in flow.unconverted],
    )


# --- subscriptions ----------------------------------------------------------------------


class SubscriptionOut(Model):
    id: UUID
    name: str
    cadence: str
    amount: MoneyOut
    monthly: MoneyOut
    last_charged_on: date
    next_charge: date
    previous_amount: MoneyOut | None
    price_changed_on: date | None


class SubscriptionsOut(Model):
    tracked: list[SubscriptionOut]
    proposed: list[SubscriptionOut]
    monthly_totals: list[MoneyOut]


def _subscription_out(view: subscription_cases.SubscriptionView) -> SubscriptionOut:
    s = view.subscription
    return SubscriptionOut(
        id=s.id,
        name=s.name,
        cadence=s.cadence.value,
        amount=money(s.amount),
        monthly=money(view.monthly),
        last_charged_on=s.last_charged_on,
        next_charge=view.next_charge,
        previous_amount=money(s.previous_amount) if s.previous_amount else None,
        price_changed_on=s.price_changed_on,
    )


@router.get("/subscriptions")
async def subscriptions(auth: Auth, web: Runtime) -> SubscriptionsOut:
    found = await subscription_cases.overview(web.uow(), auth.user.id)
    return SubscriptionsOut(
        tracked=[_subscription_out(v) for v in found.tracked],
        proposed=[_subscription_out(v) for v in found.proposed],
        monthly_totals=[money(m) for m in found.monthly_totals],
    )


@router.post("/subscriptions/{subscription_id}/track", status_code=204)
async def track_subscription(subscription_id: UUID, auth: Auth, web: Runtime) -> None:
    await subscription_cases.track(web.uow(), auth.user.id, subscription_id, now=web.clock())


@router.post("/subscriptions/{subscription_id}/dismiss", status_code=204)
async def dismiss_subscription(subscription_id: UUID, auth: Auth, web: Runtime) -> None:
    """Turn down a proposal, or stop tracking one. It isn't proposed again."""
    await subscription_cases.dismiss(web.uow(), auth.user.id, subscription_id, now=web.clock())
