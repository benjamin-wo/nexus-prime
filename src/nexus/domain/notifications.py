"""How often a user hears about their transactions on Telegram. Pure rules, no I/O.

Everyone gets an end-of-day summary unless they choose otherwise. Summaries are
due at fixed local times, all outside quiet hours (22:00-08:00), so they aren't
held back overnight.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from nexus.domain.ledger import UserId


class Frequency(StrEnum):
    INSTANT = "instant"  # each one as it happens
    HOURLY = "hourly"
    THRICE_DAILY = "thrice_daily"
    DAILY = "daily"  # the default: an end-of-day summary
    OFF = "off"


DEFAULT = Frequency.DAILY

# Local times summaries are sent at.
DAILY_AT = time(21)
THRICE_DAILY_AT = (time(9), time(14), time(20))
HOURLY_FROM, HOURLY_TO = 8, 21  # the first and last hourly summary of the day

LABELS = {
    Frequency.INSTANT: "as it happens",
    Frequency.HOURLY: "every hour (8am to 9pm)",
    Frequency.THRICE_DAILY: "3 times a day (9am, 2pm, 8pm)",
    Frequency.DAILY: "once a day at 9pm",
    Frequency.OFF: "off",
}


@dataclass(frozen=True, slots=True)
class NotificationSettings:
    user_id: UserId
    frequency: Frequency = DEFAULT
    # Everything logged before this has been told (or needn't be). None until the
    # first check, which starts counting from then rather than replaying history.
    notified_until: datetime | None = None


def last_slot(frequency: Frequency, now: datetime, tz: ZoneInfo) -> datetime | None:
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
        times = [DAILY_AT]
    for day in (today, today - timedelta(days=1)):
        for at in sorted(times, reverse=True):
            slot = datetime.combine(day, at, tzinfo=tz)
            if slot <= local:
                return slot
    raise AssertionError("a slot always exists within a day")  # pragma: no cover


def is_due(settings: NotificationSettings, now: datetime, tz: ZoneInfo) -> bool:
    slot = last_slot(settings.frequency, now, tz)
    if slot is None or settings.notified_until is None:
        return False
    return settings.notified_until < slot


def heading(frequency: Frequency, since: datetime, now: datetime, tz: ZoneInfo) -> str:
    """What a summary covers, e.g. "Today" or "Since 2pm"."""
    if frequency is Frequency.DAILY:
        return "Today"
    start, local = since.astimezone(tz), now.astimezone(tz)
    clock = start.strftime("%-I%p" if start.minute == 0 else "%-I:%M%p").lower()
    return f"Since {clock}" + (" yesterday" if start.date() < local.date() else "")
