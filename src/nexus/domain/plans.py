"""A swing-trade plan's numbers, worked out in code from a stock's levels.

Days to weeks, not day trading. Every price in a plan comes from here, never
from a model:

- the entry zone is a pullback to the nearest support below the close, a recent
  swing low or a moving average, up to half a typical day's move (ATR) above it;
- the stop is one ATR below that support, so ordinary daily noise doesn't hit it;
- targets are the resistance levels above (and the 52-week high), kept only when
  the reward is at least twice the risk;
- the plan is valid for two weeks, then worked out again; an earnings date inside
  that window is flagged;
- for a stock already held: hold, trim at a target, or exit on a close below the
  last plan's stop, beside the user's own average cost.

Research only. It says what the levels imply and what would prove it wrong; it
never places or recommends a trade on the user's behalf.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from nexus.domain.investments import Position
from nexus.domain.ledger import UserId
from nexus.domain.levels import Levels

ZONE_ATR = Decimal("0.5")  # the entry zone's height
STOP_ATR = Decimal(1)  # how far below support the stop sits
MIN_REWARD_RISK = Decimal(2)
MAX_TARGETS = 2
VALID_DAYS = 14
_CENT = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


class Verdict(StrEnum):
    IN_ZONE = "in_zone"  # the close is inside the entry zone
    WAIT = "wait"  # above the zone: wait for a pullback
    NO_TRADE = "no_trade"  # no support below, or no target worth the risk
    # For a stock already held:
    HOLD = "hold"
    TRIM = "trim"  # at or above the first target
    EXIT = "exit"  # closed below the last plan's stop


VERDICT_TEXT = {
    Verdict.IN_ZONE: "In the entry zone",
    Verdict.WAIT: "Wait for a pullback to the entry zone",
    Verdict.NO_TRADE: "No trade: the levels don't offer enough reward for the risk",
    Verdict.HOLD: "Hold",
    Verdict.TRIM: "At a target: consider trimming",
    Verdict.EXIT: "Closed below the stop: the plan says exit",
}


@dataclass(frozen=True, slots=True)
class Target:
    price: Decimal
    reward_risk: Decimal  # reward ÷ risk from the middle of the entry zone
    why: str  # "resistance" or "52-week high"


@dataclass(frozen=True, slots=True)
class PlanNumbers:
    symbol: str
    as_of: date
    close: Decimal
    verdict: Verdict
    reason: str  # one line on why, from the rules above
    entry_low: Decimal | None
    entry_high: Decimal | None
    entry_why: str | None  # "swing low" or "50-day average"
    stop: Decimal | None
    risk: Decimal | None  # per share, from the middle of the zone to the stop
    targets: list[Target]
    valid_until: date
    earnings_in_window: date | None
    trend: str | None
    held_gain_percent: Decimal | None  # for a held stock: the close against its average cost

    def prices(self) -> set[Decimal]:
        """Every figure the plan may quote."""
        found = {self.close}
        for value in (self.entry_low, self.entry_high, self.stop, self.risk):
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


def plan(
    levels: Levels,
    *,
    today: date,
    held: Position | None = None,
    earnings: date | None = None,
    previous_stop: Decimal | None = None,
) -> PlanNumbers:
    valid_until = today + timedelta(days=VALID_DAYS)
    in_window = earnings if earnings is not None and today <= earnings <= valid_until else None
    gain = None
    if held is not None and held.average_cost.amount > 0:
        cost = held.average_cost.amount
        gain = _q((levels.close - cost) / cost * 100)

    def numbers(
        verdict: Verdict,
        reason: str,
        entry: tuple[Decimal, Decimal, str] | None = None,
        stop: Decimal | None = None,
        risk: Decimal | None = None,
        targets: list[Target] | None = None,
    ) -> PlanNumbers:
        return PlanNumbers(
            symbol=levels.symbol,
            as_of=levels.as_of,
            close=levels.close,
            verdict=verdict,
            reason=reason,
            entry_low=entry[0] if entry else None,
            entry_high=entry[1] if entry else None,
            entry_why=entry[2] if entry else None,
            stop=stop,
            risk=risk,
            targets=targets or [],
            valid_until=valid_until,
            earnings_in_window=in_window,
            trend=levels.trend,
            held_gain_percent=gain,
        )

    atr = levels.atr
    anchor = _anchor(levels)
    if atr is None or atr <= 0 or anchor is None:
        why = (
            "not enough history for the typical daily move"
            if atr is None
            else ("there's no support below the close")
        )
        return numbers(Verdict.HOLD if held else Verdict.NO_TRADE, f"No plan: {why}.")
    support, entry_why = anchor
    low = _q(support)
    high = _q(min(support + atr * ZONE_ATR, max(levels.close, support)))
    middle = (low + high) / 2
    stop = _q(support - atr * STOP_ATR)
    risk = _q(middle - stop)
    seen: set[Decimal] = set()
    targets: list[Target] = []
    options = [(r, "resistance") for r in levels.resistance]
    options.append((levels.year_high, "52-week high"))
    for price, why in sorted(options, key=lambda o: o[0]):
        price = _q(price)
        if price <= middle or price in seen or risk <= 0:
            continue
        seen.add(price)
        ratio = _q((price - middle) / risk)
        if ratio >= MIN_REWARD_RISK:
            targets.append(Target(price, ratio, why))
        if len(targets) == MAX_TARGETS:
            break
    entry = (low, high, entry_why)

    if held is not None:
        if previous_stop is not None and levels.close < previous_stop:
            return numbers(
                Verdict.EXIT,
                f"The close is below the last plan's stop of {previous_stop}.",
                entry,
                stop,
                risk,
                targets,
            )
        if targets and levels.close >= targets[0].price:
            return numbers(
                Verdict.TRIM, "The close has reached the first target.", entry, stop, risk, targets
            )
        return numbers(
            Verdict.HOLD,
            "The close is between the stop and the first target.",
            entry,
            stop,
            risk,
            targets,
        )
    if not targets:
        return numbers(
            Verdict.NO_TRADE,
            f"No resistance above is at least {MIN_REWARD_RISK} times the risk away.",
            entry,
            stop,
            risk,
        )
    if levels.close <= high:
        return numbers(
            Verdict.IN_ZONE, f"The close is in the entry zone, at the {entry_why}.", entry, stop,
            risk, targets,
        )  # fmt: skip
    return numbers(
        Verdict.WAIT,
        f"The close is above the entry zone; it starts at the {entry_why}.",
        entry,
        stop,
        risk,
        targets,
    )


_NUMBER = re.compile(r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w.])")


def unsupported(text: str, allowed: set[Decimal], *, tolerance: Decimal = _CENT) -> list[str]:
    """Price-like figures in a model's text that aren't among the plan's own. Small
    whole numbers (counts, days, percentages written as words around them) are
    allowed; anything with decimals, or 3+ digits, must match a plan figure."""
    found = []
    for match in _NUMBER.finditer(text):
        whole, fraction = match.group(1).replace(",", ""), match.group(2)
        if fraction is None and len(whole) < 3:
            continue
        end = match.end()
        if text[end : end + 1] == "%":
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
