"""Recording money the user received: salary, a repayment of what someone owed, or
other income. Shared by the chat's exact phrasings and the model's confirmed tool."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from nexus.application import salary as salary_cases
from nexus.application import splits as split_cases
from nexus.application import transactions as tx_cases
from nexus.application.categories import list_categories
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import Direction, Source, User
from nexus.domain.money import Money

type UowFactory = Callable[[], UnitOfWork]


class IncomeKind(StrEnum):
    SALARY = "salary"
    REPAYMENT = "repayment"  # someone paying back what they owed
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Recorded:
    text: str  # what to tell the user
    buttons: list[list[tuple[str, str]]] = field(default_factory=list)


async def record_income(
    uow: UowFactory,
    user: User,
    *,
    kind: IncomeKind,
    amount: Money,
    occurred_at: datetime,
    counterparty: str | None = None,
    note: str | None = None,
    external_id: str | None = None,
    settle_first: bool = False,
) -> Recorded:
    """Record it. A repayment (or, with ``settle_first``, any money from a named
    person) settles that person's open IOUs first; without one it's plain income."""
    if counterparty and (kind is IncomeKind.REPAYMENT or settle_first):
        try:
            settled = await split_cases.settle_iou(
                uow(),
                user.id,
                counterparty,
                amount,
                occurred_at,
                notes=note,
                source=Source.TEXT,
                external_id=external_id,
            )
        except InvalidInput:
            pass  # no open IOU with them: plain income below
        else:
            counterparty = settled.transaction.counterparty or counterparty
            remaining = await split_cases.list_open_ious(
                uow(), user.id, participant_name=counterparty
            )
            left = [i.outstanding for i in remaining]
            status = (
                f"{counterparty} still owes {', '.join(map(str, left))}."
                if left
                else f"{counterparty} is all settled."
            )
            return Recorded(f"Recorded {amount} from {counterparty}. {status}")

    category = None
    if kind is IncomeKind.SALARY:
        cats = await list_categories(uow(), user.id)
        category = next((c.id for c in cats if c.name.casefold() == "income"), None)
    await tx_cases.log_transaction(
        uow(),
        user.id,
        tx_cases.NewTransaction(
            direction=Direction.IN,
            amount=amount,
            occurred_at=occurred_at,
            counterparty=counterparty,
            category_id=category,
            notes=note or ("Salary" if kind is IncomeKind.SALARY else None),
            source=Source.TEXT,
            external_id=external_id,
        ),
    )
    what = "salary" if kind is IncomeKind.SALARY else "income"
    source = f" from {counterparty}" if counterparty else ""
    done = f"Recorded {amount} {what}{source}."
    if kind is IncomeKind.SALARY:
        async with uow() as tx:
            schedule = await tx.planning.get_salary_schedule(user.id)
        question = salary_cases.baseline_question(schedule, amount)
        if question:
            # The usual amount only changes if the user says so.
            usual = f"{amount.amount}:{amount.currency}"
            return Recorded(
                f"{done} {question}",
                [[("Yes, update", f"salary:base:{usual}"), ("No", "salary:keep")]],
            )
    return Recorded(done)
