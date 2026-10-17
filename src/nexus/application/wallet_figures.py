"""What the user put away and what left their Spending wallet, from their wallet moves.

A move between two of the user's wallets is never spending and never income, so the
usual totals leave it out. These numbers add it back where it answers a question:

- put away: money moved into savings or investment wallets from anywhere else, less money
  moved back out of them to anywhere else. Between two savings or investment wallets
  it nets to nothing.
- total out: spending, plus money moved from Spending to any wallet other than a card
  (paying a card is not extra: the card's purchases are already spending).
- saving rate: put away as a share of the month's income.

Everything is in the home currency, converted the way ``summarize_in_home`` converts.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import fx
from nexus.application import transactions as tx_cases
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import User, WalletKind, require_aware
from nexus.domain.money import Money
from nexus.domain.planning import month_start, next_month_start

type UowFactory = Callable[[], UnitOfWork]

# Wallets whose money counts as put away.
PUT_AWAY_KINDS = frozenset({WalletKind.SAVINGS, WalletKind.INVESTMENT})


@dataclass(frozen=True, slots=True)
class WalletFigures:
    start: datetime
    end: datetime
    currency: str
    put_away: Money  # net into savings and investments, from outside them
    total_out: Money  # spent, plus moved from Spending to anything but a card
    spent: Money  # as ``summarize_in_home`` reports it
    income: Money  # as ``summarize_in_home`` reports it
    saving_rate: Decimal | None  # put_away / income (0.24 is 24%); None without income
    # Foreign amounts with no exchange rate, left out of the figures above.
    unconverted: list[Money]


def month_range(user: User, now: datetime) -> tuple[datetime, datetime]:
    """The calendar month ``now`` falls in, in the user's timezone: [start, end)."""
    tz = ZoneInfo(user.timezone)
    first: date = month_start(now.astimezone(tz).date())
    return (
        datetime.combine(first, time(), tzinfo=tz),
        datetime.combine(next_month_start(first), time(), tzinfo=tz),
    )


async def wallet_figures(
    uow: UowFactory, rates: RateSource, user: User, start: datetime, end: datetime
) -> WalletFigures:
    """The figures for [start, end): confirmed, undeleted entries only."""
    require_aware(start, field_name="start")
    require_aware(end, field_name="end")
    if start >= end:
        raise InvalidInput("start must be before end")
    home = user.home_currency
    summary = await tx_cases.summarize_in_home(uow(), rates, user, start, end)
    async with uow() as tx:
        kinds: dict[UUID, WalletKind] = {
            w.id: w.kind for w in await tx.ledger.list_wallets(user.id)
        }
        moves = await tx.ledger.moves_by_day(user.id, start, end, user.timezone)
    found = await fx.rates_for(rates, home, ((m.total.currency, m.day) for m in moves))

    put_away = Money.zero(home)
    moved_out = Money.zero(home)  # from Spending to anything but a card
    unconverted = list(summary.out.unconverted) + list(summary.income.unconverted)
    for m in moves:
        origin, target = kinds.get(m.from_wallet_id), kinds.get(m.to_wallet_id)
        into = target in PUT_AWAY_KINDS and origin not in PUT_AWAY_KINDS
        back = origin in PUT_AWAY_KINDS and target not in PUT_AWAY_KINDS
        leaves = origin is WalletKind.SPENDING and target is not WalletKind.CARD
        if not (into or back or leaves):
            continue
        amount = fx.convert(m.total, m.day, home, found).home
        if amount is None:
            unconverted.append(m.total)
            continue
        if into:
            put_away = put_away + amount
        elif back:
            put_away = put_away - amount
        if leaves:
            moved_out = moved_out + amount

    spent, income = summary.out.total, summary.income.total
    rate = put_away.amount / income.amount if income.amount > 0 else None
    return WalletFigures(
        start=start,
        end=end,
        currency=home,
        put_away=put_away,
        total_out=spent + moved_out,
        spent=spent,
        income=income,
        saving_rate=rate,
        unconverted=_by_currency(unconverted),
    )


async def month_figures(
    uow: UowFactory, rates: RateSource, user: User, *, now: datetime
) -> WalletFigures:
    """The figures for the month ``now`` falls in, in the user's timezone."""
    start, end = month_range(user, now)
    return await wallet_figures(uow, rates, user, start, end)


async def put_away(
    uow: UowFactory, rates: RateSource, user: User, start: datetime, end: datetime
) -> Money:
    return (await wallet_figures(uow, rates, user, start, end)).put_away


async def total_out(
    uow: UowFactory, rates: RateSource, user: User, start: datetime, end: datetime
) -> Money:
    return (await wallet_figures(uow, rates, user, start, end)).total_out


def _by_currency(amounts: list[Money]) -> list[Money]:
    merged: dict[str, Money] = {}
    for m in amounts:
        merged[m.currency] = merged[m.currency] + m if m.currency in merged else m
    return [merged[c] for c in sorted(merged)]
