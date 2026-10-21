"""A swing-trade plan's numbers, worked out in code from a stock's levels.

Days to weeks, not day trading. Every price in a plan comes from here, never
from a model, and every plan has a stop, targets and a review date:

- buy (or add more) in a zone at the nearest support below the close, a recent
  swing low or a moving average, up to half a typical day's move (ATR) above it;
- cut losses one ATR below that support, so ordinary daily noise doesn't hit it;
  with no support below, two ATRs under the close;
- take profit at the resistance levels above (and the 52-week high). For a new
  buy only those at least twice the risk away count; for a stock already held,
  the nearest ones are where to sell part. Where there's no resistance (a stock
  at its highs), targets are measured at 2 and 3 times the risk;
- once the first target is reached, raise the stop to today's price so the rest
  can't turn into a loss from here;
- review in two weeks, sooner on an earnings date inside that window.

Research only. It says what the levels imply and what would prove it wrong; it
never places or recommends a trade on the user's behalf.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.investments import Position
from nexus.domain.ledger import UserId
from nexus.domain.levels import Levels
from nexus.domain.market import US_MARKET, Bar, PriceKind
from nexus.domain.odds import Calibration, calibration

ZONE_ATR = Decimal("0.5")  # the buy zone's height
STOP_ATR = Decimal(1)  # how far below support the stop sits
NO_SUPPORT_STOP_ATR = Decimal(2)  # how far below the close, with no support below
MIN_REWARD_RISK = Decimal(2)
MEASURED = (Decimal(2), Decimal(3))  # targets as multiples of the risk, when needed
MAX_MEASURED = Decimal(10)  # the furthest multiple tried for a stock far above its zone
MAX_TARGETS = 2
VALID_DAYS = 14
_CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def pct(price: Decimal, base: Decimal) -> Decimal:
    """How far ``price`` is from ``base``, in percent (one decimal)."""
    return ((price - base) / base * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


class Verdict(StrEnum):
    IN_ZONE = "in_zone"  # the close is inside the buy zone
    WAIT = "wait"  # above the zone: wait for a dip
    NO_TRADE = "no_trade"  # falling with no support, or resistance too close
    # For a stock already held:
    HOLD = "hold"
    TRIM = "trim"  # reached the last plan's first target
    EXIT = "exit"  # closed below the last plan's stop


# The verdict in a word or two, for a short message.
VERDICT_SHORT = {
    Verdict.IN_ZONE: "Buy",
    Verdict.WAIT: "Wait",
    Verdict.NO_TRADE: "No trade",
    Verdict.HOLD: "Hold",
    Verdict.TRIM: "Take profit",
    Verdict.EXIT: "Cut it",
}

# The headline, in plain words.
VERDICT_TEXT = {
    Verdict.IN_ZONE: "A good price to buy",
    Verdict.WAIT: "Wait for a dip to buy",
    Verdict.NO_TRADE: "Not a good setup right now",
    Verdict.HOLD: "Keep holding",
    Verdict.TRIM: "Take some profit",
    Verdict.EXIT: "Time to cut it",
}


@dataclass(frozen=True, slots=True)
class Target:
    price: Decimal
    reward_risk: Decimal  # reward ÷ risk, from the reference price
    why: str  # "resistance", "52-week high" or "2 times the risk"


@dataclass(frozen=True, slots=True)
class PlanNumbers:
    symbol: str
    as_of: date
    close: Decimal
    verdict: Verdict
    reason: str  # one plain sentence on why
    entry_low: Decimal | None  # where to buy, or add more
    entry_high: Decimal | None
    entry_why: str | None  # "swing low" or "50-day average"
    stop: Decimal | None  # where to cut losses (on a daily close below)
    stop_why: str | None
    risk: Decimal | None  # per share, from the reference price to the stop
    targets: list[Target]  # where to take profit, nearest first
    trail_to: Decimal | None  # where to raise the stop once the first target is reached
    valid_until: date
    earnings_in_window: date | None
    trend: str | None
    held_gain_percent: Decimal | None  # for a held stock: the close against its average cost
    average_cost: Decimal | None = None
    capped_by: Decimal | None = None  # resistance too close above for a new buy

    def prices(self) -> set[Decimal]:
        """Every figure the plan may quote."""
        found = {self.close}
        for value in (
            self.entry_low,
            self.entry_high,
            self.stop,
            self.risk,
            self.trail_to,
            self.average_cost,
            self.capped_by,
        ):
            if value is not None:
                found.add(value)
        found.update(t.price for t in self.targets)
        return found


def _anchor(levels: Levels) -> tuple[Decimal, str] | None:
    """The nearest support below the close: a swing low or a moving average."""
    candidates = [(s, "swing low") for s in levels.support]
    candidates += [(v, f"{n}-day average") for n, v in levels.averages.items() if v < levels.close]
    below = [c for c in candidates if c[0] < levels.close]
    return max(below, key=lambda c: c[0]) if below else None


def _targets(
    levels: Levels, reference: Decimal, risk: Decimal, atr: Decimal, *, held: bool
) -> tuple[list[Target], Decimal | None]:
    """Where to take profit, and (for a new buy) resistance too close to be worth it.

    Overhead levels are the swing highs, the 52-week high and any moving average
    above the price (one it has fallen below tends to act as a ceiling). Every target
    is above today's close as well as the buy price: for a stock already above its
    buy zone, a level in between would be a "take profit" below where it trades now.
    Reward to risk is still measured from the buy price."""
    above = max(reference, levels.close)
    overhead = {(_q(r), "resistance") for r in levels.resistance}
    overhead.add((_q(levels.year_high), "52-week high"))
    overhead |= {(_q(v), f"{n}-day average") for n, v in levels.averages.items()}
    real: list[Target] = []
    capped_by = None
    for price, why in sorted(overhead, key=lambda o: o[0]):
        if price <= above or any(t.price == price for t in real):
            continue
        ratio = _q((price - reference) / risk)
        if held or ratio >= MIN_REWARD_RISK:
            real.append(Target(price, ratio, why))
        elif capped_by is None and not real:
            capped_by = price
        if len(real) == MAX_TARGETS:
            break
    targets = list(real)
    if len(real) < MAX_TARGETS:  # little overhead (a stock at its highs): measure from the risk
        # 2 and 3 times the risk; for a stock already above its buy zone, the next
        # multiples up when those are at or below today's close.
        k = MEASURED[0] - 1
        for _ in MEASURED:
            k += 1
            while _q(reference + risk * k) <= above and k < MAX_MEASURED:
                k += 1
            price = _q(reference + risk * k)
            if all(abs(price - t.price) > atr * ZONE_ATR for t in real):
                targets.append(Target(price, k, f"{k:g} times the risk"))
    return sorted(targets, key=lambda t: t.price)[:MAX_TARGETS], capped_by


def plan(
    levels: Levels,
    *,
    today: date,
    held: Position | None = None,
    earnings: date | None = None,
    previous_stop: Decimal | None = None,
    previous_target: Decimal | None = None,
) -> PlanNumbers:
    valid_until = today + timedelta(days=VALID_DAYS)
    in_window = earnings if earnings is not None and today <= earnings <= valid_until else None
    close = levels.close
    cost = held.average_cost.amount if held is not None else None
    gain = _q((close - cost) / cost * 100) if cost else None
    atr = levels.atr

    def numbers(verdict: Verdict, reason: str, **found: Any) -> PlanNumbers:
        return PlanNumbers(
            symbol=levels.symbol,
            as_of=levels.as_of,
            close=close,
            verdict=verdict,
            reason=reason,
            entry_low=found.get("entry_low"),
            entry_high=found.get("entry_high"),
            entry_why=found.get("entry_why"),
            stop=found.get("stop"),
            stop_why=found.get("stop_why"),
            risk=found.get("risk"),
            targets=found.get("targets", []),
            trail_to=found.get("trail_to"),
            valid_until=valid_until,
            earnings_in_window=in_window,
            trend=levels.trend,
            held_gain_percent=gain,
            average_cost=_q(cost) if cost else None,
            capped_by=found.get("capped_by"),
        )

    if atr is None or atr <= 0:
        return numbers(
            Verdict.HOLD if held else Verdict.NO_TRADE,
            "There isn't enough price history yet to work out a plan.",
        )
    anchor = _anchor(levels)
    found: dict[str, Any] = {}
    if anchor is not None:
        support, why = anchor
        found["entry_low"] = _q(support)
        found["entry_high"] = _q(min(support + atr * ZONE_ATR, max(close, support)))
        found["entry_why"] = why
        found["stop"] = _q(support - atr * STOP_ATR)
        found["stop_why"] = f"a typical day's move below the {why}"
        middle = (found["entry_low"] + found["entry_high"]) / 2
    else:
        found["stop"] = _q(close - atr * NO_SUPPORT_STOP_ATR)
        found["stop_why"] = "two typical days' moves below the close (there's no support below)"
        middle = close
    reference = close if held is not None else middle
    risk = _q(reference - found["stop"])
    found["risk"] = risk
    targets, capped_by = _targets(levels, reference, risk, atr, held=held is not None)
    found["targets"] = targets
    found["trail_to"] = _q(reference)
    found["capped_by"] = capped_by

    if held is not None:
        if previous_stop is not None and close < previous_stop:
            return numbers(
                Verdict.EXIT,
                f"It closed below the last plan's stop of {previous_stop}: the reason to hold "
                "has broken.",
                **found,
            )
        if previous_target is not None and close >= previous_target:
            return numbers(
                Verdict.TRIM,
                f"It reached the last plan's first target of {previous_target}.",
                **found,
            )
        where = (
            f"It's above support at the {anchor[1]}"
            if anchor
            else "It has fallen below its recent supports"
        )
        return numbers(Verdict.HOLD, f"{where}; hold while it stays above the stop.", **found)
    if anchor is None:
        return numbers(
            Verdict.NO_TRADE,
            "It's falling with no support below; wait for it to steady before buying.",
            **found,
        )
    if capped_by is not None:
        return numbers(
            Verdict.NO_TRADE,
            f"Resistance at {capped_by} is too close: not enough upside for the risk.",
            **found,
        )
    if close <= found["entry_high"]:
        return numbers(
            Verdict.IN_ZONE, f"It's at support (the {anchor[1]}): a good place to buy.", **found
        )
    return numbers(
        Verdict.WAIT,
        f"It's above the buy zone; support at the {anchor[1]} is a better price.",
        **found,
    )


class StepKind(StrEnum):
    BUY = "buy"
    TAKE_PROFIT = "take_profit"
    CUT_LOSS = "cut_loss"
    TRAIL = "trail"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class Step:
    """One line of the game plan: what to do, at what price, and why."""

    kind: StepKind
    title: str  # "Take profit"
    price: str | None  # "131.00" or "124.75 to 125.65"
    detail: str  # a plain sentence with how far it is from today
    change: list[str] = field(default_factory=list)  # "+4.1%" chips


def _chip(price: Decimal, base: Decimal) -> str:
    value = pct(price, base)
    return f"{'+' if value > 0 else ''}{value}%"


def _away(price: Decimal, base: Decimal) -> str:
    """ "4.1% above today", "3.9% below today"."""
    value = pct(price, base)
    return f"{abs(value)}% {'above' if value > 0 else 'below'} today"


def playbook(n: PlanNumbers) -> list[Step]:
    """The plan as steps, in the order someone would act on them. Each sentence
    carries its own prices, so it reads on its own in a chat message."""
    held = n.average_cost is not None
    steps: list[Step] = []
    buy: Step | None = None
    if n.entry_low is not None and n.entry_high is not None:
        zone = (
            f"{n.entry_low} to {n.entry_high}" if n.entry_low != n.entry_high else f"{n.entry_low}"
        )
        verb = "Add more" if held else "Buy"
        if n.close <= n.entry_high:
            detail = f"{verb} at {zone}: it's in that range now, at the {n.entry_why}."
            chips: list[str] = []
        else:
            detail = (
                f"{verb} at {zone}, on a dip to the {n.entry_why} ({_away(n.entry_high, n.close)})."
            )
            chips = [_chip(n.entry_high, n.close)]
        buy = Step(StepKind.BUY, verb, zone, detail, chips)
    elif not held:
        buy = Step(
            StepKind.BUY, "Buy", None, "Not yet: wait for it to stop falling and find support."
        )
    if not held and buy:
        steps.append(buy)
    if n.targets:
        first, *rest = n.targets
        later = (
            f", and the rest at {rest[0].price} ({_chip(rest[0].price, n.close)})" if rest else ""
        )
        vs_cost = (
            f" That's {_chip(first.price, n.average_cost)} on what you paid."
            if n.average_cost
            else ""
        )
        steps.append(
            Step(
                StepKind.TAKE_PROFIT,
                "Take profit",
                " / ".join(str(t.price) for t in n.targets),
                f"Sell part at {first.price} ({_chip(first.price, n.close)}, {first.why})"
                f"{later}.{vs_cost}",
                [_chip(t.price, n.close) for t in n.targets],
            )
        )
    if n.stop is not None:
        vs_cost = (
            f" Against what you paid that's {_chip(n.stop, n.average_cost)}."
            if n.average_cost
            else ""
        )
        steps.append(
            Step(
                StepKind.CUT_LOSS,
                "Cut losses",
                str(n.stop),
                f"Sell if a day closes below {n.stop} ({_chip(n.stop, n.close)}), "
                f"{n.stop_why}.{vs_cost}",
                [_chip(n.stop, n.close)],
            )
        )
    if n.trail_to is not None and n.targets:
        steps.append(
            Step(
                StepKind.TRAIL,
                "After the first target",
                str(n.trail_to),
                f"Once it closes above {n.targets[0].price}, raise your stop to {n.trail_to} so "
                "the rest can't turn into a loss from here.",
            )
        )
    if held and buy:
        steps.append(buy)
    review = f"Hold until {n.valid_until:%d %b}" if held else f"Valid until {n.valid_until:%d %b}"
    detail = "Then ask for a fresh plan; prices and news will have moved."
    if n.earnings_in_window:
        detail = (
            f"Earnings are on {n.earnings_in_window:%d %b}, inside this window: prices can jump "
            "either way, so check the plan before then."
        )
    steps.append(Step(StepKind.REVIEW, review, None, detail))
    return steps


_NUMBER = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w.])")
# Names and dates with numbers in them that aren't prices.
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_NAMES = re.compile(
    rf"S&P\s*500|\b(?:52|50|20|200)-(?:week|day)\b|\b(?:\d{{1,2}}\s+{_MONTH},?\s+|{_MONTH}\s+"
    rf"(?:\d{{1,2}},?\s+)?)(?:19|20)\d\d\b",
    re.I,
)


def unsupported(text: str, allowed: set[Decimal], *, tolerance: Decimal = _CENT) -> list[str]:
    """Price-like figures in a model's text that aren't among the plan's own. Small
    whole numbers (counts, days, percentages written as words around them) are
    allowed; anything with decimals, or 3+ digits, must match a plan figure."""
    found = []
    for match in _NUMBER.finditer(_NAMES.sub(" ", text)):
        whole, fraction = match.group(1).replace(",", ""), match.group(2)
        if fraction is None and len(whole) < 3:
            continue
        end = match.end()
        if match.string[end : end + 1] == "%":
            continue
        value = Decimal(f"{whole}.{fraction}" if fraction else whole)
        if not any(abs(value - a) <= tolerance for a in allowed):
            found.append(match.group(0))
    return found


_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def keep_supported(text: str, allowed: set[Decimal]) -> str:
    """The text without any sentence quoting a price the plan didn't work out."""
    kept = [s for s in _SENTENCE.split(text.strip()) if s and not unsupported(s, allowed)]
    return " ".join(kept)


class PlanStatus(StrEnum):
    OPEN = "open"
    TARGET = "target"  # reached a target (M13d)
    STOPPED = "stopped"  # closed below the stop (M13d)
    EXPIRED = "expired"  # ran past its valid-until date (M13d)
    # Replaced by a refresh of itself (Keep fresh). It never finished, so it isn't scored.
    REFRESHED = "refreshed"


@dataclass(frozen=True, slots=True)
class SavedPlan:
    """A finished plan as kept: its key numbers, and the full write-up in ``body``."""

    id: UUID
    user_id: UserId
    run_id: UUID | None
    symbol: str
    verdict: Verdict
    as_of: date
    valid_until: date
    close: Decimal
    entry_low: Decimal | None
    entry_high: Decimal | None
    stop: Decimal | None
    body: dict[str, Any]
    status: PlanStatus
    created_at: datetime
    # Following it after each close (M13d).
    entered_on: date | None = None  # the buy zone was reached (a held stock: from the start)
    checked_through: date | None = None  # the last trading day looked at
    outcome_price: Decimal | None = None
    outcome_day: date | None = None
    result_percent: Decimal | None = None  # from the buy price (or the close, if held)
    alerts: bool = True
    # Keep it fresh: refreshed by itself when it goes stale (see ``refresh_reason``).
    keep_fresh: bool = False
    refreshed_from: UUID | None = None  # the plan this one replaced, and when that was made
    refreshed_from_at: datetime | None = None
    last_refresh_check: datetime | None = None  # when it was last sent for an automatic refresh
    # The price it was written with (a live quote, a provisional close or a close).
    price: Decimal | None = None
    price_at: datetime | None = None
    price_kind: PriceKind | None = None

    @property
    def held(self) -> bool:
        return self.verdict in HELD_VERDICTS

    @property
    def first_target(self) -> Decimal | None:
        targets = self.body.get("targets") or []
        return Decimal(str(targets[0]["price"])) if targets else None

    @property
    def atr(self) -> Decimal | None:
        """A typical day's move when the plan was made (plans before Keep fresh don't
        have it)."""
        found = self.body.get("atr")
        return Decimal(str(found)) if found is not None else None

    @property
    def reference(self) -> Decimal | None:
        """What a result is measured from: the middle of the buy zone, or the close
        on the day of the plan for a stock already held."""
        if self.held:
            return self.close
        if self.entry_low is None or self.entry_high is None:
            return None
        return _q((self.entry_low + self.entry_high) / 2)


HELD_VERDICTS = frozenset({Verdict.HOLD, Verdict.TRIM, Verdict.EXIT})
# Plans that make a call worth following and scoring. "Not a good setup" and "time
# to cut it" don't: there's nothing to buy or keep.
FOLLOWED = frozenset({Verdict.IN_ZONE, Verdict.WAIT, Verdict.HOLD, Verdict.TRIM})


def price_notes(n: PlanNumbers, price: Decimal, kind: PriceKind) -> list[str]:
    """Plain notes for a price that has already gone past what the plan says. The plan's
    numbers come from daily closes; ``price`` is the live price (or the day's last, before
    the official close), so it may already sit in or under the buy zone, or under the
    stop. Nothing for a plan that makes no call, or when the price is the close itself."""
    if kind is PriceKind.CLOSE or n.verdict not in FOLLOWED:
        return []
    now = f"{price:,.2f}"
    check = "The plan is worked out from the last close, so check where things stand before acting."
    if n.stop is not None and price < n.stop:
        return [f"The price is already under the stop: {now} now, stop {n.stop}. {check}"]
    if n.entry_low is None or n.entry_high is None:
        return []
    zone = "add-more zone" if n.average_cost is not None else "buy zone"
    where = f"{n.entry_low} to {n.entry_high}" if n.entry_low != n.entry_high else f"{n.entry_low}"
    if price < n.entry_low:
        return [f"The price is already under the {zone}: {now} now, {zone} {where}. {check}"]
    if n.close > n.entry_high and price <= n.entry_high:
        return [f"The price is already in the {zone}: {now} now, {zone} {where}."]
    return []


class EventKind(StrEnum):
    ENTRY = "entry"  # dipped into the buy zone
    TARGET = "target"  # reached the first target
    STOPPED = "stopped"  # closed below the stop
    EXPIRED = "expired"  # ran past its date with neither


@dataclass(frozen=True, slots=True)
class PlanEvent:
    kind: EventKind
    day: date
    price: Decimal  # where it happened: the zone top, the target, the close


@dataclass(frozen=True, slots=True)
class Followed:
    """A plan after looking at the days since it was last checked."""

    status: PlanStatus
    entered_on: date | None
    checked_through: date | None
    outcome_price: Decimal | None
    outcome_day: date | None
    result_percent: Decimal | None
    events: list[PlanEvent]


def follow_day(plan: SavedPlan, today: date) -> date:
    """The day to follow a plan through. A plan kept fresh doesn't run out at once: the
    refresh replaces it once its date has passed, so for ``KEEP_FRESH_GRACE`` after that
    date it is followed only up to the date. If the refresh hasn't happened by then, it
    ends as any plan does."""
    if plan.keep_fresh and today <= plan.valid_until + KEEP_FRESH_GRACE:
        return min(today, plan.valid_until)
    return today


def follow(plan: SavedPlan, bars: Sequence[Bar], *, today: date) -> Followed:
    """Walk the trading days after the plan (and after the last check), oldest first.

    A buy plan counts from the first day whose low reaches the top of the buy zone.
    From then on, a day that closes below the stop ends it as stopped (checked
    first: the cautious reading of a day that touched both), and a day whose high
    reaches the first target ends it as a hit. A plan still open after its date
    expires. Results are measured from the middle of the zone, or for a stock
    already held from the close on the day of the plan."""
    entered = plan.entered_on or (plan.created_at.date() if plan.held else None)
    checked = plan.checked_through
    events: list[PlanEvent] = []
    status, price, day = plan.status, plan.outcome_price, plan.outcome_day
    target = plan.first_target
    start = max(d for d in (plan.as_of, checked) if d is not None)
    for bar in sorted((b for b in bars if b.day > start), key=lambda b: b.day):
        if status is not PlanStatus.OPEN or bar.day > plan.valid_until:
            break
        checked = bar.day
        if entered is None:
            if plan.entry_high is not None and bar.low <= plan.entry_high:
                entered = bar.day
                events.append(PlanEvent(EventKind.ENTRY, bar.day, plan.entry_high))
            else:
                continue
        if plan.stop is not None and bar.close < plan.stop:
            status, price, day = PlanStatus.STOPPED, _q(bar.close), bar.day
            events.append(PlanEvent(EventKind.STOPPED, bar.day, price))
        elif target is not None and bar.high >= target:
            status, price, day = PlanStatus.TARGET, target, bar.day
            events.append(PlanEvent(EventKind.TARGET, bar.day, target))
    if status is PlanStatus.OPEN and today > plan.valid_until:
        last = [b for b in bars if b.day <= plan.valid_until]
        status = PlanStatus.EXPIRED
        day = plan.valid_until
        price = _q(max(last, key=lambda b: b.day).close) if last and entered else None
        events.append(PlanEvent(EventKind.EXPIRED, plan.valid_until, price or plan.close))
    reference = plan.reference
    result = (
        pct(price, reference)
        if price is not None and reference and entered and status is not PlanStatus.OPEN
        else None
    )
    return Followed(status, entered, checked, price, day, result, events)


@dataclass(frozen=True, slots=True)
class Record:
    """How the plans that finished turned out, misses included."""

    finished: int
    targets: int
    stopped: int
    expired: int
    never_entered: int  # buy plans that never reached their zone
    average_result: Decimal | None  # over plans that were entered
    open: int
    # Whether the odds given to first targets held up, over finished plans that had them.
    calibration: Calibration | None = None


def record(plans: Sequence[SavedPlan]) -> Record:
    """Plans replaced by their own refresh are left out: they were closed before they
    finished, and the plan that replaced them is the one that gets scored."""
    followed = [p for p in plans if p.verdict in FOLLOWED and p.status is not PlanStatus.REFRESHED]
    done = [p for p in followed if p.status is not PlanStatus.OPEN]
    results = [p.result_percent for p in done if p.result_percent is not None]
    average = (
        (sum(results, Decimal(0)) / len(results)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if results
        else None
    )
    return Record(
        finished=len(done),
        targets=sum(p.status is PlanStatus.TARGET for p in done),
        stopped=sum(p.status is PlanStatus.STOPPED for p in done),
        expired=sum(p.status is PlanStatus.EXPIRED for p in done),
        never_entered=sum(p.entered_on is None and not p.held for p in done),
        average_result=average,
        open=sum(p.status is PlanStatus.OPEN for p in followed),
        calibration=calibration(
            [
                (chance, p.status is PlanStatus.TARGET)
                for p in done
                if (p.entered_on is not None or p.held)
                and (chance := _first_chance(p.body)) is not None
            ]
        ),
    )


def _first_chance(body: dict[str, Any]) -> int | None:
    odds = body.get("odds") or {}
    targets = odds.get("targets") or []
    return int(targets[0]["chance"]) if targets else None


# --- keeping a plan fresh -----------------------------------------------------------

# A plan with Keep fresh on is made again when the price has moved this many typical days'
# moves (ATR) from the one it was written with, when it is this old, when its date has
# passed, or when the stock reported earnings since. At most once a day for a plan, and
# this many times a day for a user.
REFRESH_MOVE_ATR = Decimal(1)
REFRESH_AGE = timedelta(days=7)
REFRESH_EVERY = timedelta(hours=24)
REFRESH_PER_USER = 10
# A plan with Keep fresh on isn't run out by the follow for this long after its date, to
# give the refresh a chance; after that it ends as any plan does.
KEEP_FRESH_GRACE = timedelta(days=3)
# The user is told of a refresh when the verdict changed or the entry, stop or first target
# moved by more than this many ATR. Otherwise it is made quietly.
NOTIFY_MOVE_ATR = Decimal("0.5")


class RefreshKind(StrEnum):
    EXPIRED = "expired"  # its valid-until date has passed
    MOVED = "moved"  # the price is over an ATR from the plan's
    EARNINGS = "earnings"  # the stock reported since the plan was made
    AGE = "age"  # a week old


@dataclass(frozen=True, slots=True)
class RefreshReason:
    kind: RefreshKind
    atrs: Decimal | None = None  # how far the price moved, for MOVED

    @property
    def text(self) -> str:
        """Why, for the message: "price moved 2.3 ATR"."""
        if self.kind is RefreshKind.MOVED and self.atrs is not None:
            return f"price moved {self.atrs} ATR"
        return {
            RefreshKind.EXPIRED: "it had run out",
            RefreshKind.MOVED: "price moved",
            RefreshKind.EARNINGS: "earnings are out",
            RefreshKind.AGE: "it was a week old",
        }[self.kind]


def refresh_reason(
    plan: SavedPlan,
    *,
    now: datetime,
    price: Decimal | None,
    atr: Decimal | None,
    earnings: Sequence[date],
) -> RefreshReason | None:
    """Why an open plan should be made again, or None. In this order: its date has passed
    (a New York date, as the market's days are); the live or last price is over one ATR
    from the price the plan was written with (its close, for a plan made before prices were
    kept); the stock reported earnings (any of ``earnings``) after the plan was made and
    that day is now past; or it is a week old. ``atr`` is the plan's own, else today's."""
    today = now.astimezone(US_MARKET).date()
    if plan.valid_until < today:
        return RefreshReason(RefreshKind.EXPIRED)
    if price is not None and atr is not None and atr > 0:
        away = abs(price - (plan.price if plan.price is not None else plan.close)) / atr
        if away > REFRESH_MOVE_ATR:
            return RefreshReason(RefreshKind.MOVED, away.quantize(Decimal("0.1"), ROUND_HALF_UP))
    made = plan.created_at.astimezone(US_MARKET).date()
    if any(made < day < today for day in earnings):
        return RefreshReason(RefreshKind.EARNINGS)
    if now - plan.created_at >= REFRESH_AGE:
        return RefreshReason(RefreshKind.AGE)
    return None


def _entry_middle(plan: SavedPlan) -> Decimal | None:
    if plan.entry_low is None or plan.entry_high is None:
        return None
    return (plan.entry_low + plan.entry_high) / 2


def _moved(before: Decimal | None, after: Decimal | None, atr: Decimal | None) -> bool:
    """Whether a price moved by more than half an ATR, or appeared or went."""
    if before is None or after is None:
        return before is not after
    return atr is not None and atr > 0 and abs(after - before) > atr * NOTIFY_MOVE_ATR


EN_DASH = "\N{EN DASH}"


def _price_text(value: Decimal) -> str:
    text = f"{value:,.2f}"
    return text.removesuffix(".00")


def refresh_message(old: SavedPlan, new: SavedPlan, why: str) -> str | None:
    """What to tell the user about a refresh, or None when nothing worth a message
    changed: "NVDA plan refreshed (price moved 2.3 ATR): now Wait, was Buy. Entry
    170 to 174, stop 165." (with an en dash between the two prices). Plain text, no link."""
    atr = new.atr or old.atr
    if (
        old.verdict is new.verdict
        and not _moved(_entry_middle(old), _entry_middle(new), atr)
        and not _moved(old.stop, new.stop, atr)
        and not _moved(old.first_target, new.first_target, atr)
    ):
        return None
    verdict = (
        f"now {VERDICT_SHORT[new.verdict]}, was {VERDICT_SHORT[old.verdict]}."
        if old.verdict is not new.verdict
        else f"still {VERDICT_SHORT[new.verdict]}."
    )
    if new.entry_low is None or new.entry_high is None:
        entry = "No entry zone"
    elif new.entry_low == new.entry_high:
        entry = f"Entry {_price_text(new.entry_low)}"
    else:
        entry = f"Entry {_price_text(new.entry_low)}{EN_DASH}{_price_text(new.entry_high)}"
    stop = f"stop {_price_text(new.stop)}" if new.stop is not None else "no stop"
    target = new.first_target
    first = f" First target {_price_text(target)}." if target is not None else ""
    return f"{new.symbol} plan refreshed ({why}): {verdict} {entry}, {stop}.{first}"
