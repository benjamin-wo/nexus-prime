"""Splitting habits ("I always split dinners with Ann"): saving, listing, forgetting, and
applying them to an expense that was just logged.

The code supplies the split; the caller (the chat) decides whether this expense is one the
habit holds for (``apply`` is skipped for "my treat tonight")."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from nexus.application import splits as split_cases
from nexus.application.clock import utcnow
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import Conflict, NotFound
from nexus.domain.ledger import Direction, Transaction, UserId
from nexus.domain.split_habits import (
    SplitHabit,
    clean_habit,
    habit_shares,
    matching,
    select_for_removal,
)

type UowFactory = Callable[[], UnitOfWork]


async def set_habit(
    uow: UnitOfWork,
    actor: UserId,
    person: str,
    applies_to: str | None,
    share: Decimal,
    *,
    now: datetime | None = None,
) -> SplitHabit:
    """Saves "split ``applies_to`` (None: anything) with ``person``, their share ``share``";
    replacing the share if there is a habit for that person and category already."""
    name, category, share = clean_habit(person, applies_to, share)
    async with uow:
        habit = await uow.ledger.upsert_split_habit(actor, name, category, share, now or utcnow())
        await uow.commit()
    return habit


async def list_habits(uow: UnitOfWork, actor: UserId) -> list[SplitHabit]:
    async with uow:
        return await uow.ledger.list_split_habits(actor)


async def remove_habit(
    uow: UnitOfWork, actor: UserId, person: str, applies_to: str | None = None
) -> list[SplitHabit]:
    """Forgets the habit with ``person`` for ``applies_to``; without a category, all of that
    person's habits. Returns what was removed."""
    async with uow:
        found = select_for_removal(await uow.ledger.list_split_habits(actor), person, applies_to)
        if not found:
            raise NotFound(f"no split habit with {person.strip()}")
        await uow.ledger.delete_split_habits(actor, [h.id for h in found])
        await uow.commit()
    return found


async def apply_to_expense(
    uow: UowFactory, actor: UserId, expense: Transaction, category: str | None
) -> split_cases.SplitResult | None:
    """Splits a logged expense in ``category`` the way the user's habits say. None when no
    habit holds for it, it isn't money out, or it was split already. Raises InvalidInput if
    the habits together claim more than the bill."""
    if expense.direction is not Direction.OUT or expense.is_deleted:
        return None
    habits = matching(await list_habits(uow(), actor), category)
    if not habits:
        return None
    requests = habit_shares(expense.amount, habits)
    if not requests:
        return None
    try:
        return await split_cases.split_bill(uow(), actor, expense.id, requests, if_unsplit=True)
    except Conflict:
        return None
