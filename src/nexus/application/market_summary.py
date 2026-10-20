"""The morning summary of the US market, on Telegram.

At 08:00 in each user's timezone (any time until noon if a sweep was missed), on a morning
after a US trading day, a user who holds or watches stocks (and hasn't turned it off) gets
one message: the portfolio's change in that session ("Portfolio +1.2% yesterday (SGD
+312.40)"), the three biggest movers each with the day's newest headline, then the alerts
held unsent during the session (marked sent), then the plan events found by the evening
follow on daily bars. It is sent at 08:00 whatever quiet hours say: the user's morning.

Two jobs, so the work is done once per user and day: a sweep every few minutes checks who is
due and queues ``market.summary.user`` under the key user and local date; that job builds the
message and queues it as a ``telegram.send`` with ``anytime``.

The session is the last weekday whose 16:00 New York close has passed. The summary is skipped
when that day was a NYSE holiday (``NYSE_HOLIDAYS``) or its close is more than a day old (a
Sunday or Monday morning in Asia, or any morning after a weekend), so a weekend never repeats
Friday.
"""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.application import moves
from nexus.application.budgets import TELEGRAM_SEND
from nexus.application.fx import RateSource
from nexus.application.ports import UnitOfWork
from nexus.domain.alerts import MINUS, MarketAlert, signed
from nexus.domain.ledger import User, UserId
from nexus.domain.market import (
    REGULAR_CLOSE,
    US_MARKET,
    is_holiday,
    last_weekday_closed,
)
from nexus.domain.money import Money
from nexus.domain.news import clean_text

type UowFactory = Callable[[], UnitOfWork]

SWEEP_JOB = "market.summary"
USER_JOB = "market.summary.user"
SEND_AT = time(8)
# A sweep that was missed still sends it, until this local time.
SEND_UNTIL = time(12)
# Valued at this hour in New York on the session's day, whatever the clock says: after the
# close and the official closing prices, before any later trading.
VALUED_AT = time(20)
# The session's close must be this recent: a morning after a weekend has no session of its own.
MAX_AGE = timedelta(hours=24)
MAX_ALERT_LINES = 10
HEADLINE_CHARS = 90


def session_to_report(now: datetime) -> date | None:
    """The US session a summary sent at ``now`` is about, or None when there is none to tell
    of: it was a holiday, or it closed more than a day ago."""
    day = last_weekday_closed(now)
    if is_holiday(day):
        return None
    closed = datetime.combine(day, REGULAR_CLOSE, US_MARKET)
    return day if timedelta(0) <= now - closed < MAX_AGE else None


def due_now(user: User, now: datetime) -> bool:
    """Whether it is the user's morning for a summary: 08:00 to noon, local time."""
    local = now.astimezone(ZoneInfo(user.timezone)).time()
    return SEND_AT <= local < SEND_UNTIL


async def sweep(uow: UowFactory, *, now: datetime) -> int:
    """Queue a summary for each user due one. Returns how many were queued."""
    day = session_to_report(now)
    if day is None:
        return 0
    async with uow() as tx:
        user_ids = await tx.planning.users_to_notify()
    queued = 0
    for user_id in user_ids:
        async with uow() as tx:
            user = await tx.ledger.get_user(user_id)
            if user is None or not due_now(user, now):
                continue
            if not (await tx.planning.get_notifications(user_id)).market_summary:
                continue
            if not (
                await tx.investments.list_holdings(user_id)
                or await tx.investments.list_watch(user_id)
            ):
                continue
            local_date = now.astimezone(ZoneInfo(user.timezone)).date()
            queued += await tx.jobs.enqueue(
                USER_JOB,
                {"user_id": str(user_id), "day": day.isoformat(), "date": local_date.isoformat()},
                dedupe_key=f"{SWEEP_JOB}:{user_id}:{local_date.isoformat()}",
                run_at=now,
            )
            await tx.commit()
    return queued


async def send(
    uow: UowFactory, rates: RateSource, payload: dict[str, Any], *, now: datetime
) -> bool:
    """Build one user's summary and queue it (the job). True if a message was queued."""
    user_id = UserId(UUID(payload["user_id"]))
    day = date.fromisoformat(payload["day"])
    local_date = date.fromisoformat(payload["date"])
    async with uow() as tx:
        user = await tx.ledger.get_user(user_id)
        settings = await tx.planning.get_notifications(user_id)
    if user is None or user.telegram_chat_id is None or not settings.market_summary:
        return False
    valued_at = min(now, datetime.combine(day, VALUED_AT, US_MARKET))
    report = await moves.today(uow, rates, user, now=valued_at)
    async with uow() as tx:
        unsent = await tx.investments.unsent_alerts(user_id, day)
        text = describe(report, unsent, day, local_date)
        if text is None:
            return False
        sent = await tx.jobs.enqueue(
            TELEGRAM_SEND,
            {"user_id": str(user_id), "text": text, "anytime": True},
            dedupe_key=f"{USER_JOB}.send:{user_id}:{local_date.isoformat()}",
            run_at=now,
        )
        if sent:
            await tx.investments.mark_alerts_sent(user_id, [a.id for a in unsent], now)
        await tx.commit()
    return sent


def describe(
    report: moves.Today, unsent: list[MarketAlert], day: date, local_date: date
) -> str | None:
    """The message, or None when there is nothing to say. ``day`` is the session told of
    and ``local_date`` the user's date this morning."""
    when = "yesterday" if day == local_date - timedelta(days=1) else f"on {day:%a %-d %b}"
    lines: list[str] = []
    if report.change is not None and report.percent is not None:
        lines.append(f"📊 Portfolio {signed(report.percent)} {when} ({_amount(report.change)})")
    elif report.movers:
        lines.append(f"📊 Your stocks {when}")
    if report.movers:
        lines.append("Biggest movers:" if report.holds else "Your watchlist moved most:")
        for m in report.movers:
            line = f"• {m.symbol} {signed(m.percent)} to {m.price:,.2f}"
            if m.headline is not None:
                headline = clean_text(m.headline.headline, HEADLINE_CHARS)
                line += f": {headline} ({m.headline.source})"
            lines.append(line)
    closed = datetime.combine(day, REGULAR_CLOSE, US_MARKET)
    lines += _section("While the market was open:", [a for a in unsent if a.created_at < closed])
    lines += _section("Your plans after the close:", [a for a in unsent if a.created_at >= closed])
    return "\n".join(lines) if lines else None


def _section(heading: str, alerts: list[MarketAlert]) -> list[str]:
    if not alerts:
        return []
    lines = [heading, *(f"• {a.text}" for a in alerts[:MAX_ALERT_LINES])]
    if len(alerts) > MAX_ALERT_LINES:
        lines.append(f"and {len(alerts) - MAX_ALERT_LINES} more.")
    return lines


def _amount(change: Money) -> str:
    """ "SGD +312.40", with a real minus sign for a fall."""
    sign = MINUS if change.amount < 0 else "+"
    return f"{change.currency} {sign}{abs(change.amount):,.2f}"
