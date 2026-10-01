"""Per-user rate limits: sliding windows, refused requests not counted."""

from datetime import UTC, datetime, timedelta

from nexus.application.limits import RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_a_window_fills_then_frees_up() -> None:
    clock = Clock()
    limiter = RateLimiter({"message": ((3, timedelta(minutes=1)),)}, clock)
    assert [limiter.allow("message", "ann") for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("message", "ben")  # each user has their own count
    clock.now += timedelta(seconds=61)
    assert limiter.allow("message", "ann")


def test_every_window_must_have_room_and_refusals_dont_count() -> None:
    clock = Clock()
    limiter = RateLimiter({"message": ((2, timedelta(minutes=1)), (3, timedelta(hours=1)))}, clock)
    assert limiter.allow("message", 1) and limiter.allow("message", 1)
    assert not limiter.allow("message", 1)  # the minute is full
    clock.now += timedelta(minutes=2)
    assert limiter.allow("message", 1)  # the third of the hour
    assert not limiter.allow("message", 1)  # the hour is full now
    clock.now += timedelta(minutes=59)
    assert limiter.allow("message", 1)  # the first two have aged out


def test_unknown_kinds_are_not_limited() -> None:
    limiter = RateLimiter({})
    assert all(limiter.allow("anything", 1) for _ in range(100))
