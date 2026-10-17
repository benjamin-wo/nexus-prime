"""Telling whether a scheduled move has already happened: a move into the wallet, around
the due date, for about the amount."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application.ports import LedgerQuery, LedgerRepository
from nexus.domain.ledger import Direction, Transaction, TransactionStatus, UserId
from nexus.domain.money import Money

# A move "matches" a scheduled one when it went to the same wallet within this many days of
# the due date, for an amount within this share of the scheduled one.
MATCH_DAYS = 5
MATCH_TOLERANCE = Decimal("0.01")


def _near(found: Money | None, wanted: Money) -> bool:
    return (
        found is not None
        and found.currency == wanted.currency
        and abs(found.amount - wanted.amount) <= wanted.amount * MATCH_TOLERANCE
    )


async def find_matching_move(
    repo: LedgerRepository,
    actor: UserId,
    *,
    to_wallet_id: UUID,
    amount: Money,
    due: date,
    tz: ZoneInfo,
) -> Transaction | None:
    """A live, confirmed move into the wallet that looks like the scheduled one due on
    ``due``: for the amount (or what arrived) give or take 1%, within five days of that
    day. The closest in time if several."""
    start = datetime.combine(due - timedelta(days=MATCH_DAYS), time(), tzinfo=tz)
    end = datetime.combine(due + timedelta(days=MATCH_DAYS + 1), time(), tzinfo=tz)
    page = await repo.list_transactions(
        actor,
        LedgerQuery(
            direction=Direction.MOVE,
            to_wallet_id=to_wallet_id,
            status=TransactionStatus.CONFIRMED,
            start=start,
            end=end,
            limit=200,
        ),
    )
    centre = datetime.combine(due, time(12), tzinfo=tz)
    close = [m for m in page.items if _near(m.amount, amount) or _near(m.received_amount, amount)]
    return min(close, key=lambda m: abs(m.occurred_at - centre), default=None)
