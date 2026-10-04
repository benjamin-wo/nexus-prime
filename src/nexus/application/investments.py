"""Holdings: read from a broker screenshot (and saved only once the user says so),
or changed one trade at a time. Research only: nothing here trades."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from nexus.application.fx import RateSource, convert, rates_for
from nexus.application.market import PRICE_CURRENCY, queue_refresh
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.investments import (
    DraftStatus,
    Holding,
    HoldingsDraft,
    Position,
    buy,
    changes,
    describe_position,
    merge_positions,
    sell,
)
from nexus.domain.ledger import User, UserId
from nexus.domain.market import Valued, percent, value
from nexus.domain.money import Money

type UowFactory = Callable[[], UnitOfWork]


async def portfolio(uow: UnitOfWork, user_id: UserId) -> list[Holding]:
    async with uow:
        return await uow.investments.list_holdings(user_id)


@dataclass(frozen=True, slots=True)
class Proposal:
    draft: HoldingsDraft
    changes: list[str]  # what saving it would change; empty if nothing would
    first: bool  # no holdings yet: this would be the whole portfolio


async def propose(
    uow: UnitOfWork, user_id: UserId, positions: Sequence[Position], *, now: datetime
) -> Proposal:
    """Keep positions read from a screenshot as a draft for the user to check. An
    older draft still waiting is dropped: the newest screenshot wins."""
    merged = merge_positions(list(positions))
    if not merged:
        raise InvalidInput("no positions were found in that screenshot")
    async with uow:
        held = [h.position for h in await uow.investments.list_holdings(user_id)]
        older = await uow.investments.latest_waiting_draft(user_id)
        if older is not None:
            await uow.investments.set_draft_status(user_id, older.id, DraftStatus.DISCARDED)
        draft = HoldingsDraft(uuid4(), user_id, merged, DraftStatus.WAITING, now)
        await uow.investments.insert_draft(draft)
        await uow.commit()
    return Proposal(draft, changes(held, merged), first=not held)


def describe_proposal(proposal: Proposal) -> str:
    """The question about a screenshot, for Telegram and the chat."""
    positions = proposal.draft.positions
    if proposal.first:
        lines = [f"📈 I read {len(positions)} positions from your screenshot:"]
        lines += [f"• {describe_position(p)}" for p in positions]
        lines.append("Save these as your holdings?")
    elif proposal.changes:
        lines = ["📈 Compared with what I have, your screenshot shows:"]
        lines += [f"• {line}" for line in proposal.changes]
        lines.append("Update your holdings to match?")
    else:
        lines = ["📈 Your screenshot matches the holdings I already have. Nothing to change."]
    return "\n".join(lines)


async def _waiting(uow: UnitOfWork, user_id: UserId, draft_id: UUID) -> HoldingsDraft:
    draft = await uow.investments.get_draft(user_id, draft_id, for_update=True)
    if draft is None:
        raise NotFound("that screenshot isn't waiting any more")
    if draft.status is not DraftStatus.WAITING:
        raise Conflict(f"that screenshot was already {draft.status.value}")
    return draft


async def save_draft(
    uow: UnitOfWork, user_id: UserId, draft_id: UUID, *, now: datetime
) -> list[Position]:
    """The user said yes: the screenshot is the whole portfolio now. Stocks it
    doesn't list are removed."""
    async with uow:
        draft = await _waiting(uow, user_id, draft_id)
        keep = {p.symbol for p in draft.positions}
        for held in await uow.investments.list_holdings(user_id):
            if held.position.symbol not in keep:
                await uow.investments.remove_position(user_id, held.position.symbol)
        for position in draft.positions:
            await uow.investments.save_position(user_id, position, now)
        await uow.investments.set_draft_status(user_id, draft_id, DraftStatus.SAVED)
        await queue_refresh(uow, now)
        await uow.commit()
    return draft.positions


async def discard_draft(uow: UnitOfWork, user_id: UserId, draft_id: UUID) -> None:
    async with uow:
        await _waiting(uow, user_id, draft_id)
        await uow.investments.set_draft_status(user_id, draft_id, DraftStatus.DISCARDED)
        await uow.commit()


async def waiting_draft(uow: UnitOfWork, user_id: UserId) -> HoldingsDraft | None:
    async with uow:
        return await uow.investments.latest_waiting_draft(user_id)


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


async def record_trade(
    uow: UnitOfWork,
    user_id: UserId,
    side: Side,
    symbol: str,
    quantity: Decimal,
    price: Money | None,
    *,
    now: datetime,
) -> Position | None:
    """A trade the user made (at their broker): the position after it, or None
    when it's all sold. A purchase needs the price paid."""
    async with uow:
        held = {h.position.symbol: h.position for h in await uow.investments.list_holdings(user_id)}
        if side is Side.BUY:
            if price is None:
                raise InvalidInput(f"what price did you pay for the {symbol}?")
            after: Position | None = buy(held.get(symbol), symbol, quantity, price)
        else:
            after = sell(held.get(symbol), symbol, quantity)
        if after is None:
            await uow.investments.remove_position(user_id, symbol)
        else:
            await uow.investments.save_position(user_id, after, now)
            await queue_refresh(uow, now)
        await uow.commit()
    return after


async def set_position(
    uow: UnitOfWork, user_id: UserId, position: Position, *, now: datetime
) -> None:
    """Set a position outright, as the web app's edit does."""
    async with uow:
        await uow.investments.save_position(user_id, position, now)
        await queue_refresh(uow, now)
        await uow.commit()


async def remove(uow: UnitOfWork, user_id: UserId, symbol: str) -> None:
    async with uow:
        if not await uow.investments.remove_position(user_id, symbol):
            raise NotFound(f"you don't hold any {symbol}")
        await uow.commit()


@dataclass(frozen=True, slots=True)
class Row:
    holding: Holding
    valued: Valued | None  # None until the stock has a price
    value_home: Money | None  # the value in the home currency; None without a rate
    gain_home: Money | None
    day_change_home: Money | None


@dataclass(frozen=True, slots=True)
class Valuation:
    """The portfolio at the last close, in the user's home currency. Gains use
    today's exchange rate for cost and value alike: Nexus doesn't know when each
    share was bought, so it can't know the rate paid."""

    rows: list[Row]
    home: str
    value: Money | None  # None when nothing could be valued
    cost: Money | None
    gain: Money | None
    gain_percent: Decimal | None
    day_change: Money | None
    day_percent: Decimal | None
    as_of: date | None  # the latest close used
    missing: list[str]  # stocks left out of the totals (no price or no rate yet)


async def valuation(uow: UnitOfWork, rates: RateSource, user: User) -> Valuation:
    async with uow:
        held = await uow.investments.list_holdings(user.id)
        bars = await uow.investments.latest_bars([h.position.symbol for h in held])
    home = user.home_currency
    valued: list[tuple[Holding, Valued | None]] = []
    for h in held:
        # Prices are in USD; a position kept in another currency can't be valued
        # against them.
        same = h.position.average_cost.currency == PRICE_CURRENCY
        found = bars.get(h.position.symbol, []) if same else []
        previous = found[1] if len(found) > 1 else None
        valued.append((h, value(h.position, found[0], previous) if found else None))
    wanted = [(v.price.currency, v.price_day) for _, v in valued if v is not None]
    looked_up = await rates_for(rates, home, wanted)

    def at_home(amount: Money | None, v: Valued) -> Money | None:
        return None if amount is None else convert(amount, v.price_day, home, looked_up).home

    rows: list[Row] = []
    total = cost = gain = change = before = Money.zero(home)
    missing: list[str] = []
    changed = False
    for h, v in valued:
        if v is None:
            rows.append(Row(h, None, None, None, None))
            missing.append(h.position.symbol)
            continue
        row = Row(h, v, at_home(v.value, v), at_home(v.gain, v), at_home(v.day_change, v))
        rows.append(row)
        if row.value_home is None or row.gain_home is None:
            missing.append(h.position.symbol)
            continue
        total += row.value_home
        gain += row.gain_home
        cost += row.value_home - row.gain_home
        if row.day_change_home is not None:
            change += row.day_change_home
            before += row.value_home - row.day_change_home
            changed = True
    counted = len(held) > len(missing)
    return Valuation(
        rows=rows,
        home=home,
        value=total if counted else None,
        cost=cost if counted else None,
        gain=gain if counted else None,
        gain_percent=percent(gain.amount, cost.amount) if counted else None,
        day_change=change if changed else None,
        day_percent=percent(change.amount, before.amount) if changed else None,
        as_of=max((v.price_day for _, v in valued if v is not None), default=None),
        missing=missing,
    )


def describe_valuation(v: Valuation) -> str:
    """The portfolio in a few lines, for the chat."""
    if not v.rows:
        return "You don't have any holdings saved yet. Send a screenshot of your portfolio."
    lines = []
    for row in v.rows:
        line = describe_position(row.holding.position)
        p = row.valued
        if p is not None:
            line += f"; {p.price} on {p.price_day:%d %b}, worth {p.value}"
            if p.gain_percent is not None:
                line += f" ({p.gain_percent:+}%)"
        lines.append(f"• {line}")
    if v.value is not None and v.gain is not None:
        way = "up" if v.gain.amount >= 0 else "down"
        summary = f"Total {v.value}, {way} {abs(v.gain.amount):,.2f}"
        if v.gain_percent is not None:
            summary += f" ({v.gain_percent:+}%)"
        if v.day_change is not None and v.day_percent is not None:
            summary += f"; {v.day_change.amount:+,.2f} ({v.day_percent:+}%) on the day"
        lines.append(summary + ".")
    if v.missing:
        lines.append(f"No price yet for {', '.join(v.missing)}.")
    return "\n".join(lines)
