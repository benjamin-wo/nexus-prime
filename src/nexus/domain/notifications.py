"""How often a user hears about their transactions on Telegram, and which of Nexus's
other messages are sent at once, held or folded into a digest. Pure rules, no I/O.

Everyone gets an end-of-day summary unless they choose otherwise. The preset
summaries are due at fixed local times outside quiet hours (the user's own, 23:00 to
08:00 unless changed); the daily one goes at a time the user can choose, quiet hours or
not, since they picked it.

Every other message has a level (``decide``): urgent goes at once, now goes unless it is
quiet hours or the day's cap is used up, and digest is never sent alone.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo

from nexus.domain.errors import InvalidInput
from nexus.domain.ledger import UserId
from nexus.domain.planning import quiet_until


class Frequency(StrEnum):
    INSTANT = "instant"  # each one as it happens
    HOURLY = "hourly"
    THRICE_DAILY = "thrice_daily"
    DAILY = "daily"  # the default: an end-of-day summary
    OFF = "off"


DEFAULT = Frequency.DAILY

# Local times summaries are sent at. The daily one is the user's to choose.
DAILY_AT = time(21)
THRICE_DAILY_AT = (time(9), time(14), time(20))
HOURLY_FROM, HOURLY_TO = 8, 21  # the first and last hourly summary of the day

# Quiet hours, local time: nothing is sent between the start and the end (a window may
# cross midnight) except what is urgent or timed by the user. Equal times mean none.
QUIET_START = time(23)
QUIET_END = time(8)
# A stock moving this much (%) in a day is a big move; the user may pick 1 to 20.
MOVE_PERCENT = Decimal("5.0")
MIN_MOVE_PERCENT = Decimal(1)
MAX_MOVE_PERCENT = Decimal(20)
# At most this many messages a day that are neither urgent nor timed by the user; the user
# may pick 3 to 20. A message with buttons still goes when the day's cap is used up.
DAILY_CAP = 6
MIN_DAILY_CAP = 3
MAX_DAILY_CAP = 20

LABELS = {
    Frequency.INSTANT: "as it happens",
    Frequency.HOURLY: "every hour (8am to 9pm)",
    Frequency.THRICE_DAILY: "3 times a day (9am, 2pm, 8pm)",
    Frequency.DAILY: "once a day",
    Frequency.OFF: "off",
}


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    user_id: UserId
    frequency: Frequency = DEFAULT
    # Everything logged before this has been told (or needn't be). None until the
    # first check, which starts counting from then rather than replaying history.
    notified_until: datetime | None = None
    daily_at: time = DAILY_AT  # when the daily summary goes, local time
    quiet_start: time = QUIET_START
    quiet_end: time = QUIET_END
    move_alert_percent: Decimal = MOVE_PERCENT  # a big move in a day, in %
    market_summary: bool = True  # the morning summary of the US market
    daily_cap: int = DAILY_CAP  # messages a day before the rest wait for a digest


def clock(at: time) -> str:
    """9pm, 11:59pm, noon, midnight."""
    if at == time(0):
        return "midnight"
    if at == time(12):
        return "noon"
    return at.strftime("%-I%p" if at.minute == 0 else "%-I:%M%p").lower()


def move_percent(raw: Decimal | float | int | str) -> Decimal:
    """A big-move threshold in percent, 1 to 20, to one decimal place."""
    try:
        value = Decimal(str(raw)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidInput("give the size of a big move as a percentage, such as 5") from exc
    if not value.is_finite() or not MIN_MOVE_PERCENT <= value <= MAX_MOVE_PERCENT:
        raise InvalidInput(
            f"a big move can be {MIN_MOVE_PERCENT}% to {MAX_MOVE_PERCENT}% in a day, not {raw}%"
        )
    return value


def daily_cap(raw: int | float | str) -> int:
    """A daily cap on messages, 3 to 20, as a whole number."""
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise InvalidInput("give the daily limit as a whole number, such as 6") from exc
    if not value.is_finite() or value != value.to_integral_value():
        raise InvalidInput("give the daily limit as a whole number, such as 6")
    if not MIN_DAILY_CAP <= value <= MAX_DAILY_CAP:
        raise InvalidInput(
            f"the daily limit can be {MIN_DAILY_CAP} to {MAX_DAILY_CAP} messages, not {raw}"
        )
    return int(value)


def describe_quiet(start: time, end: time) -> str:
    """ "11pm to 8am", or "none" when the two are the same."""
    return "none" if start == end else f"{clock(start)} to {clock(end)}"


def label(frequency: Frequency, daily_at: time = DAILY_AT) -> str:
    if frequency is Frequency.DAILY:
        return f"once a day at {clock(daily_at)}"
    return LABELS[frequency]


def last_slot(
    frequency: Frequency, now: datetime, tz: ZoneInfo, daily_at: time = DAILY_AT
) -> datetime | None:
    """The latest time at or before ``now`` a summary was due. None for off."""
    local = now.astimezone(tz)
    today = local.date()
    if frequency is Frequency.OFF:
        return None
    if frequency is Frequency.INSTANT:
        return now
    if frequency is Frequency.HOURLY:
        times = [time(h) for h in range(HOURLY_FROM, HOURLY_TO + 1)]
    elif frequency is Frequency.THRICE_DAILY:
        times = list(THRICE_DAILY_AT)
    else:
        times = [daily_at]
    for day in (today, today - timedelta(days=1)):
        for at in sorted(times, reverse=True):
            slot = datetime.combine(day, at, tzinfo=tz)
            if slot <= local:
                return slot
    raise AssertionError("a slot always exists within a day")  # pragma: no cover


def is_due(settings: NotificationSettings, now: datetime, tz: ZoneInfo) -> bool:
    slot = last_slot(settings.frequency, now, tz, settings.daily_at)
    if slot is None or settings.notified_until is None:
        return False
    return settings.notified_until < slot


def heading(
    frequency: Frequency, since: datetime, now: datetime, tz: ZoneInfo, daily_at: time = DAILY_AT
) -> str:
    """What a summary covers, e.g. "Today" or "Since 2pm". A daily summary set for
    late at night can go out just after midnight: it's still that day's."""
    if frequency is Frequency.DAILY:
        slot = last_slot(frequency, now, tz, daily_at)
        if slot is None or slot.date() == now.astimezone(tz).date():
            return "Today"
        return f"{slot:%A}"
    start, local = since.astimezone(tz), now.astimezone(tz)
    clock = start.strftime("%-I%p" if start.minute == 0 else "%-I:%M%p").lower()
    return f"Since {clock}" + (" yesterday" if start.date() < local.date() else "")


# --- the level of a message -----------------------------------------------------------


class Level(StrEnum):
    URGENT = "urgent"  # at once, quiet hours or not, and not counted toward the day's cap
    NOW = "now"  # something the user asked for or must act on
    DIGEST = "digest"  # worth knowing, never sent alone


class Kind(StrEnum):
    """What a message is about: short, stable, shown to the user's own records. New ones
    need no migration."""

    BUDGET_ALERT = "budget_alert"
    BILL_REMINDER = "bill_reminder"
    RECEIPT_QUESTION = "receipt_question"
    PAYDAY = "payday"
    SUBSCRIPTION_SPOTTED = "subscription_spotted"
    SUBSCRIPTION_PRICE = "subscription_price"
    PLAN_EVENT = "plan_event"
    PLAN_REFRESH = "plan_refresh"
    BIG_MOVE = "big_move"
    DIVIDEND = "dividend"
    MARKET_SUMMARY = "market_summary"
    TRIP_REMINDER = "trip_reminder"
    BOOKING = "booking"
    RESEARCH_DONE = "research_done"
    TRIP_ACTIVITY = "trip_activity"
    DAILY_SUMMARY = "daily_summary"
    TRANSACTION_UPDATE = "transaction_update"
    EMAIL_STATUS = "email_status"
    TIMEZONE = "timezone"
    DIGEST = "digest"  # the message that folds held ones together: never recorded itself
    MESSAGE = "message"  # a job queued before messages had a kind


# Summaries the user chose the frequency of, or timed, and the one-line note that their time
# zone changed: they never count toward the day's cap.
UNCAPPED = frozenset(
    {Kind.DAILY_SUMMARY, Kind.MARKET_SUMMARY, Kind.TRANSACTION_UPDATE, Kind.TIMEZONE}
)
# Where digests go besides the end of quiet hours (local time), for what was held outside them.
DIGEST_EVENING = time(19)
# A digest lists this many items, then says how many more are on the web.
DIGEST_LINES = 12
DIGEST_LINE_LENGTH = 200


class Status(StrEnum):
    SENT = "sent"
    HELD = "held"  # waiting for quiet hours to end or for the next digest
    DIGESTED = "digested"  # told in a digest
    DROPPED = "dropped"  # never told: the user has no Telegram chat to tell


@dataclass(frozen=True, slots=True)
class Notification:
    """One message Nexus meant to send a user, kept for 30 days."""

    id: UUID
    user_id: UserId
    kind: str
    level: Level
    text: str
    link: str | None  # a web path that opens what it is about
    has_buttons: bool
    created_at: datetime
    status: Status
    sent_at: datetime | None = None  # when it went, alone or in a digest
    held_until: datetime | None = None
    digest_id: UUID | None = None  # the digest it went in, shared by all its items


@dataclass(frozen=True, slots=True)
class Send:
    """Send it now."""


@dataclass(frozen=True, slots=True)
class HoldUntil:
    """Quiet hours: keep it until they end."""

    until: datetime


@dataclass(frozen=True, slots=True)
class Digest:
    """Keep it for the next digest, which goes at ``at``."""

    at: datetime


type Decision = Send | HoldUntil | Digest


def next_digest_at(local: datetime, quiet_start: time, quiet_end: time) -> datetime:
    """When the next digest goes after ``local``: when quiet hours end each day, and at
    19:00 unless that falls in quiet hours. With no quiet hours, 19:00 alone. ``local``
    must be timezone-aware, in the user's timezone."""
    times = [DIGEST_EVENING] if quiet_start == quiet_end else [quiet_end, DIGEST_EVENING]
    found = [
        at
        for days in (0, 1)
        for t in times
        if (at := datetime.combine(local.date() + timedelta(days=days), t, tzinfo=local.tzinfo))
        > local
        and quiet_until(at, quiet_start, quiet_end) is None
    ]
    return min(found)


def decide(
    level: Level,
    now_local: datetime,
    quiet_start: time,
    quiet_end: time,
    sent_today: int,
    cap: int,
    has_buttons: bool,
) -> Decision:
    """What to do with a message. ``sent_today`` counts what went today (the user's day)
    that was neither urgent nor timed by the user.

    - urgent: sent, always.
    - now: held until quiet hours end if it is quiet hours; else sent, unless the cap is
      used up, when it goes in a digest (with buttons it is sent anyway: they must work).
    - digest: in the next digest, always.
    A held or digested message with buttons is sent on its own when its time comes; one
    without joins the digest.
    """
    if level is Level.URGENT:
        return Send()
    if level is Level.NOW:
        quiet = quiet_until(now_local, quiet_start, quiet_end)
        if quiet is not None:
            return HoldUntil(quiet)
        if sent_today < cap or has_buttons:
            return Send()
    return Digest(next_digest_at(now_local, quiet_start, quiet_end))


def local_day(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The user's day around ``now``: from its first moment up to the next day's."""
    day = now.astimezone(tz).date()
    start = datetime.combine(day, time(0), tzinfo=tz)
    return start, datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz)


def digest_text(items: Sequence[Notification]) -> str:
    """The message that folds held items together, oldest first."""
    lines = ["While you were away:"]
    for item in items[:DIGEST_LINES]:
        line = " ".join(item.text.split())
        if len(line) > DIGEST_LINE_LENGTH:
            line = line[: DIGEST_LINE_LENGTH - 1].rstrip() + "…"
        lines.append(f"• {line}")
    if len(items) > DIGEST_LINES:
        lines.append(f"and {len(items) - DIGEST_LINES} more — see Notifications on the web")
    return "\n".join(lines)
