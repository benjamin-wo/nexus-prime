"""Holdings: read from a broker screenshot (and saved only once the user says so),
or changed one trade at a time. Research only: nothing here trades."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.fx import RateSource, convert, rates_for
from nexus.application.market import PRICE_CURRENCY, queue_refresh
from nexus.application.ports import UnitOfWork
from nexus.domain.errors import Conflict, InvalidInput, NotFound
from nexus.domain.investments import (
    Dividend,
    DraftStatus,
    Expected,
    Holding,
    HoldingsDraft,
    Position,
    Trade,
    TradeSide,
    buy,
    changes,
    describe_position,
    expected,
    held_on,
    merge_positions,
    plain,
    realised,
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


Side = TradeSide


@dataclass(frozen=True, slots=True)
class Recorded:
    trade: Trade
    position: Position | None  # after the trade; None when it's all sold


async def record(
    uow: UnitOfWork,
    user_id: UserId,
    side: Side,
    symbol: str,
    quantity: Decimal,
    price: Money | None,
    *,
    now: datetime,
    traded_on: date | None = None,
) -> Recorded:
    """A trade the user made at their broker, kept in their trade history. A
    purchase needs the price paid; a sale with its price also records what it
    locked in against the average cost."""
    day = traded_on or now.date()
    if day > now.date():
        raise InvalidInput("that trade's date is in the future")
    async with uow:
        held = {h.position.symbol: h.position for h in await uow.investments.list_holdings(user_id)}
        before = held.get(symbol)
        gain: Money | None = None
        if side is Side.BUY:
            if price is None:
                raise InvalidInput(f"what price did you pay for the {symbol}?")
            after: Position | None = buy(before, symbol, quantity, price)
        else:
            after = sell(before, symbol, quantity)
            if before is not None and price is not None:
                gain = realised(before, quantity, price)
        trade = Trade(uuid4(), user_id, symbol, side, quantity, price, day, gain, now)
        await uow.investments.insert_trade(trade)
        if after is None:
            await uow.investments.remove_position(user_id, symbol)
        else:
            await uow.investments.save_position(user_id, after, now)
            await queue_refresh(uow, now)
        await uow.commit()
    return Recorded(trade, after)


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
    """A trade the user made: the position after it, or None when it's all sold."""
    return (await record(uow, user_id, side, symbol, quantity, price, now=now)).position


async def trade_history(uow: UnitOfWork, user_id: UserId) -> list[Trade]:
    """The user's trades, newest first."""
    async with uow:
        return list(reversed(await uow.investments.list_trades(user_id)))


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
    # Locked in by sales and received as dividends (after tax withheld), in the home
    # currency at today's rate; None when there are none.
    realised: Money | None = None
    dividends: Money | None = None

    @property
    def total_return(self) -> Money | None:
        """What the holdings have made: unrealised, realised and dividends."""
        parts = [m for m in (self.gain, self.realised, self.dividends) if m is not None]
        if not parts:
            return None
        return sum(parts[1:], parts[0])


async def valuation(uow: UnitOfWork, rates: RateSource, user: User) -> Valuation:
    async with uow:
        held = await uow.investments.list_holdings(user.id)
        bars = await uow.investments.latest_bars([h.position.symbol for h in held])
        trades = await uow.investments.list_trades(user.id)
        paid = await uow.investments.list_dividends(user.id)
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
    as_of = max((v.price_day for _, v in valued if v is not None), default=None)
    day = as_of or max((t.traded_on for t in trades), default=date.today())
    locked = await _in_home(
        rates, home, [t.realised for t in trades if t.realised is not None], day
    )
    income = await _in_home(rates, home, [d.net for d in paid], day)
    return Valuation(
        rows=rows,
        home=home,
        value=total if counted else None,
        cost=cost if counted else None,
        gain=gain if counted else None,
        gain_percent=percent(gain.amount, cost.amount) if counted else None,
        day_change=change if changed else None,
        day_percent=percent(change.amount, before.amount) if changed else None,
        as_of=as_of,
        missing=missing,
        realised=locked,
        dividends=income,
    )


async def _in_home(rates: RateSource, home: str, amounts: list[Money], day: date) -> Money | None:
    """A sum of amounts in any currency, in the home currency at ``day``'s rate (the
    latest close's, as gains are). None when there's nothing, or no rate."""
    if not amounts:
        return None
    found = await rates_for(rates, home, [(m.currency, day) for m in amounts])
    total = Money.zero(home)
    for m in amounts:
        converted = convert(m, day, home, found).home
        if converted is None:
            return None
        total += converted
    return total


# --- dividends --------------------------------------------------------------------------

# Dividends going ex within this many days back are collected (later ones as they come).
DIVIDEND_LOOKBACK_DAYS = 30


async def collect_dividends(uow: UowFactory, *, now: datetime) -> int:
    """Records the dividends on shares users held when each went ex, and tells them.
    Only from when Nexus knew of the holding (its first save or the first trade
    recorded): before that, it can't know they held it. Returns how many."""
    async with uow() as tx:
        symbols = await tx.investments.held_symbols()
        going_ex = await tx.investments.dividends_since(
            symbols, now.date() - timedelta(days=DIVIDEND_LOOKBACK_DAYS)
        )
    found = 0
    for bar in going_ex:
        async with uow() as tx:
            for h in await tx.investments.holders(bar.symbol):
                if h.position.average_cost.currency != PRICE_CURRENCY:
                    continue
                trades = await tx.investments.list_trades(h.user_id, bar.symbol)
                since = min([h.created_at.date(), *(t.traded_on for t in trades)])
                if since >= bar.day:
                    continue
                # Shares held at the close before the ex-date earn the dividend.
                shares = held_on(h.position.quantity, trades, bar.day - timedelta(days=1))
                if shares <= 0:
                    continue
                dividend = Dividend(
                    uuid4(), h.user_id, bar.symbol, bar.day,
                    Money(bar.div_cash.quantize(Decimal("0.0001")), PRICE_CURRENCY),
                    shares, now,
                )  # fmt: skip
                if await tx.investments.insert_dividend(dividend):
                    found += 1
                    await tx.jobs.enqueue(
                        TELEGRAM_SEND,
                        {"user_id": str(h.user_id), "text": describe_dividend(dividend)},
                        dedupe_key=f"dividend:{dividend.id}",
                        run_at=now,
                    )
            await tx.commit()
    return found


def describe_dividend(d: Dividend) -> str:
    tax = f", {d.net} after {d.withheld} withheld" if d.withheld.is_positive else ""
    return (
        f"💵 {d.symbol} went ex-dividend on {d.ex_date:%d %b}: {d.per_share} a share on your "
        f"{describe_shares(d.shares)} shares is {d.gross}{tax}. It's paid to your broker "
        "in the next few weeks."
    )


@dataclass(frozen=True, slots=True)
class DividendView:
    received: list[Dividend]  # newest first
    received_home: Money | None  # after tax withheld, in the home currency
    this_year_home: Money | None
    expected: list[Expected]  # per holding, from the last 12 months
    expected_home: Money | None  # the next 12 months, after tax, in the home currency


async def dividend_view(
    uow: UowFactory, rates: RateSource, user: User, *, now: datetime
) -> DividendView:
    """Dividends received, and what the holdings would pay over the next year if
    each pays what it paid in the last one."""
    async with uow() as tx:
        held = await tx.investments.list_holdings(user.id)
        received = await tx.investments.list_dividends(user.id)
        symbols = [h.position.symbol for h in held]
        past = await tx.investments.dividends_since(symbols, now.date() - timedelta(days=365))
        bars = await tx.investments.latest_bars(symbols, 1)
    home = user.home_currency
    outlook: list[Expected] = []
    for h in held:
        per = [b.div_cash for b in past if b.symbol == h.position.symbol]
        close = bars.get(h.position.symbol, [None])[0]
        found = expected(h.position, per, close.close if close else None)
        if found is not None:
            outlook.append(found)
    today = now.date()
    year = today.year
    return DividendView(
        received=received,
        received_home=await _in_home(rates, home, [d.net for d in received], today),
        this_year_home=await _in_home(
            rates, home, [d.net for d in received if d.ex_date.year == year], today
        ),
        expected=outlook,
        expected_home=await _in_home(rates, home, [e.net for e in outlook], today),
    )


def describe_dividends(view: DividendView) -> str:
    """For the chat."""
    lines: list[str] = []
    if view.received:
        lines.append(
            f"Received (after tax withheld): {view.received_home or 'no rate yet'} in all, "
            f"{view.this_year_home or 'none'} this year."
        )
        lines += [
            f"• {d.symbol} ex {d.ex_date:%d %b %Y}: {d.per_share}/share on "
            f"{describe_shares(d.shares)} shares = {d.gross}, {d.net} after tax"
            for d in view.received[:10]
        ]
    else:
        lines.append("No dividends recorded yet on your holdings.")
    if view.expected:
        lines.append(
            f"Next 12 months if each pays what it paid in the last 12: about "
            f"{view.expected_home or 'no rate yet'} after tax."
        )
        for e in view.expected:
            y = (
                f", yield {e.yield_on_value}% (on cost {e.yield_on_cost}%)"
                if e.yield_on_value
                else ""
            )
            lines.append(
                f"• {e.symbol}: {e.per_share}/share over {e.payments} payment(s), "
                f"about {e.net} after tax{y}"
            )
    lines.append("US dividends have 30% withheld for Singapore residents.")
    return "\n".join(lines)


def describe_shares(quantity: Decimal) -> str:
    return f"{plain(quantity):,f}"


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
    if v.realised is not None:
        lines.append(f"Locked in by sales: {v.realised.amount:+,.2f} {v.home}.")
    if v.dividends is not None:
        lines.append(f"Dividends received, after tax: {v.dividends.amount:,.2f} {v.home}.")
    total = v.total_return
    if total is not None and (v.realised is not None or v.dividends is not None):
        lines.append(f"Total return (held, sold and dividends): {total.amount:+,.2f} {v.home}.")
    if v.missing:
        lines.append(f"No price yet for {', '.join(v.missing)}.")
    return "\n".join(lines)
