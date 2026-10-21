"""Home's setup checklist: the few things that make Nexus useful, each worked out from what
the user already has (never stored), and a way to put the list away once they are done
with it. Read-only apart from the dismissal; always the signed-in user's own."""

from dataclasses import dataclass
from datetime import datetime

from nexus.application.ports import UnitOfWork
from nexus.domain.email import ConnectionStatus
from nexus.domain.ledger import User


@dataclass(frozen=True, slots=True)
class SetupItem:
    key: str  # stable: "payday", "receipts", "investments", "budget"
    label: str
    done: bool
    link: str  # the web app page where it is done
    ask: str  # one sentence the web can send to the chat to do it there


@dataclass(frozen=True, slots=True)
class Setup:
    dismissed: bool
    items: list[SetupItem]


async def checklist(uow: UnitOfWork, user: User) -> Setup:
    """The checklist as it stands. Done means: a salary schedule is set; a Gmail account
    works or a forwarding address is set up (one that was refused and needs reconnecting
    is not done); any stock is held or watched; any budget is set."""
    async with uow:
        has_payday = await uow.planning.get_salary_schedule(user.id) is not None
        has_receipts = any(
            c.status is ConnectionStatus.ACTIVE for c in await uow.email.list_connections(user.id)
        )
        has_stocks = bool(
            await uow.investments.list_holdings(user.id)
            or await uow.investments.list_watch(user.id)
        )
        has_budget = bool(await uow.planning.list_budgets(user.id))
    return Setup(
        dismissed=user.setup_dismissed_at is not None,
        items=[
            SetupItem(
                "payday",
                "Set your payday",
                has_payday,
                "/accounting/plan",
                "My payday is the 25th",
            ),
            SetupItem(
                "receipts",
                "Get receipts in automatically",
                has_receipts,
                "/accounting/email",
                "Help me get my receipts in from email automatically",
            ),
            SetupItem(
                "investments",
                "Add your stocks",
                has_stocks,
                "/investment",
                "Add NVDA to my watchlist",
            ),
            SetupItem(
                "budget",
                "Set a monthly budget",
                has_budget,
                "/accounting/plan",
                "Set my monthly budget to 2000",
            ),
        ],
    )


async def dismiss(uow: UnitOfWork, user: User, *, now: datetime) -> None:
    """Put the checklist away. Safe to repeat: the first time is kept."""
    if user.setup_dismissed_at is not None:
        return
    async with uow:
        await uow.ledger.set_setup_dismissed(user.id, now)
        await uow.commit()
