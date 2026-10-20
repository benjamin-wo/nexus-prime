"""Live prices: which price to show, when the market is open, reading Finnhub's quote
and status, and the facts about a price against the levels. Every ticker and figure
here is made up. October 2026 is still daylight time in New York (UTC-4)."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest

from nexus.application.quotes import QuoteRateLimited, QuoteSourceError
from nexus.domain.investments import Position
from nexus.domain.levels import Levels, now_vs_levels
from nexus.domain.market import (
    Bar,
    MarketStatus,
    PriceKind,
    Quote,
    describe_price_time,
    just_closed,
    live_value,
    market_open,
    pick_price,
    trading_day,
    value,
)
from nexus.domain.money import Money
from nexus.infra.market.finnhub_quotes import FinnhubQuotes

D = Decimal
SINGAPORE = ZoneInfo("Asia/Singapore")
THU, FRI, SAT = date(2026, 10, 15), date(2026, 10, 16), date(2026, 10, 17)
MON, TUE = date(2026, 10, 19), date(2026, 10, 20)


def ny(text: str) -> datetime:
    """A New York wall-clock time such as "2026-10-19 10:42", as an instant."""
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("America/New_York"))


def bar(day: date, close: str) -> Bar:
    p = D(close)
    return Bar("NVDA", day, p, p, p, p, p, 1)


def quote(price: str, at: str, prev: str = "100") -> Quote:
    return Quote("NVDA", D(price), D(prev), None, None, None, ny(at))


def status(is_open: bool, session: str | None = None, holiday: str | None = None) -> MarketStatus:
    return MarketStatus(is_open, session, holiday, ny("2026-10-19 09:00"))


LATEST, BEFORE = bar(FRI, "100"), bar(THU, "98")
OPEN = status(True, "regular")


def test_the_regular_session_by_the_clock() -> None:
    assert not market_open(ny("2026-10-19 09:29:59"))
    assert market_open(ny("2026-10-19 09:30"))
    assert market_open(ny("2026-10-19 15:59:59"))
    assert not market_open(ny("2026-10-19 16:00"))
    assert not market_open(ny("2026-10-17 11:00"))  # a Saturday
    assert market_open(ny("2026-10-19 13:30").astimezone(UTC))  # in any timezone


def test_the_close_is_caught_once_in_the_twenty_minutes_after_it() -> None:
    assert just_closed(None, ny("2026-10-19 15:59")) is None
    assert just_closed(None, ny("2026-10-19 16:00")) == ny("2026-10-19 16:00")
    assert just_closed(None, ny("2026-10-19 16:19:59")) == ny("2026-10-19 16:00")
    assert just_closed(None, ny("2026-10-19 16:20")) is None
    assert just_closed(None, ny("2026-10-17 16:05")) is None  # a Saturday
    assert just_closed(status(False, None, "Made-up Day"), ny("2026-10-19 16:05")) is None
    assert just_closed(status(False, "post-market"), ny("2026-10-19 16:05")) is not None


def test_a_quotes_trading_day_is_its_new_york_date() -> None:
    late = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)  # 9pm on Monday in New York
    assert trading_day(late) == MON


def test_a_live_quote_while_the_market_is_open() -> None:
    q = quote("103", "2026-10-19 10:41")
    got = pick_price(LATEST, BEFORE, q, OPEN, ny("2026-10-19 10:42"))
    assert got is not None
    assert (got.price, got.previous, got.day, got.at, got.kind) == (
        D("103"),
        D("100"),  # the quote's own previous close, not the bar's
        MON,
        q.quoted_at,
        PriceKind.LIVE,
    )


def test_the_usual_hours_stand_in_when_the_status_is_unknown() -> None:
    q = quote("103", "2026-10-19 10:41")
    got = pick_price(LATEST, BEFORE, q, None, ny("2026-10-19 10:42"))
    assert got is not None and got.kind is PriceKind.LIVE
    # ...and say closed outside them, whatever the quote.
    late = pick_price(LATEST, BEFORE, q, None, ny("2026-10-19 07:00"))
    assert late is not None and late.kind is PriceKind.CLOSE


def test_a_quote_from_yesterday_is_not_live() -> None:
    # Monday's session, but the newest quote is Friday's (a bar for Friday exists).
    q = quote("101", "2026-10-16 15:59")
    got = pick_price(LATEST, BEFORE, q, OPEN, ny("2026-10-19 10:42"))
    assert got is not None and got.kind is PriceKind.CLOSE and got.price == D("100")
    # Even when it is newer than the bar (the bar is late), a past day's quote isn't live.
    newer = pick_price(BEFORE, None, q, OPEN, ny("2026-10-19 10:42"))
    assert newer is not None and newer.kind is PriceKind.CLOSE and newer.price == D("98")


def test_a_quote_older_than_the_latest_bar_is_ignored() -> None:
    monday = bar(MON, "105")
    q = quote("101", "2026-10-16 15:59")
    got = pick_price(monday, LATEST, q, status(False, "post-market"), ny("2026-10-19 18:30"))
    assert got is not None and (got.price, got.previous, got.day) == (D("105"), D("100"), MON)
    assert got.at is None and got.kind is PriceKind.CLOSE


def test_after_the_close_the_last_quote_is_a_provisional_close_until_the_bar_arrives() -> None:
    q = quote("104", "2026-10-19 16:00", prev="102")
    closed = status(False, "post-market")
    got = pick_price(LATEST, BEFORE, q, closed, ny("2026-10-19 16:30"))
    assert got is not None
    assert (got.price, got.previous, got.day, got.at) == (D("104"), D("102"), MON, q.quoted_at)
    assert got.kind is PriceKind.PROVISIONAL_CLOSE
    # Without the exchange's word, the clock says the same.
    assert pick_price(LATEST, BEFORE, q, None, ny("2026-10-19 21:00")) == got
    # Tiingo's bar for Monday arrives: the official close replaces it.
    official = pick_price(bar(MON, "103.8"), LATEST, q, closed, ny("2026-10-19 18:30"))
    assert official is not None and official.kind is PriceKind.CLOSE
    assert (official.price, official.previous, official.at) == (D("103.8"), D("100"), None)


def test_a_provisional_close_carries_over_a_weekend() -> None:
    q = quote("104", "2026-10-16 16:00", prev="102")
    got = pick_price(BEFORE, None, q, status(False), ny("2026-10-17 12:00"))
    assert got is not None and got.kind is PriceKind.PROVISIONAL_CLOSE and got.day == FRI
    # With Friday's bar stored, the bar wins.
    done = pick_price(LATEST, BEFORE, q, status(False), ny("2026-10-17 12:00"))
    assert done is not None and done.kind is PriceKind.CLOSE and done.day == FRI


def test_a_holiday_is_not_a_session_even_in_trading_hours() -> None:
    q = quote("104", "2026-10-16 16:00", prev="102")
    holiday = status(False, None, "Made-up Day")
    got = pick_price(BEFORE, None, q, holiday, ny("2026-10-19 10:42"))
    assert got is not None and got.kind is PriceKind.PROVISIONAL_CLOSE and got.day == FRI
    # The clock alone would call it open, but a quote from before today is never live.
    guess = pick_price(BEFORE, None, q, None, ny("2026-10-19 10:42"))
    assert guess is not None and guess.kind is PriceKind.CLOSE


def test_before_the_open_a_premarket_quote_is_not_a_price() -> None:
    q = quote("109", "2026-10-19 07:30")
    got = pick_price(LATEST, BEFORE, q, status(False, "pre-market"), ny("2026-10-19 08:00"))
    assert got is not None and got.kind is PriceKind.CLOSE and got.price == D("100")


def test_unusable_quotes_fall_back_to_the_bar() -> None:
    now = ny("2026-10-19 10:42")
    for bad in (quote("0", "2026-10-19 10:41"), quote("103", "2026-10-19 11:30")):  # future
        got = pick_price(LATEST, BEFORE, bad, OPEN, now)
        assert got is not None and got.kind is PriceKind.CLOSE
    no_previous = pick_price(LATEST, BEFORE, quote("103", "2026-10-19 10:41", "0"), OPEN, now)
    assert no_previous is not None and no_previous.kind is PriceKind.LIVE
    assert no_previous.previous is None  # no day change rather than a wrong one


def test_a_stock_with_only_a_quote_and_with_nothing() -> None:
    now = ny("2026-10-19 10:42")
    got = pick_price(None, None, quote("103", "2026-10-19 10:41"), OPEN, now)
    assert got is not None and got.kind is PriceKind.LIVE
    assert pick_price(None, None, None, OPEN, now) is None
    assert pick_price(None, None, quote("103", "2026-10-19 10:41"), status(False), now) is None


def test_a_position_at_a_live_price() -> None:
    position = Position("NVDA", D("10"), Money(D("90"), "USD"))
    q = quote("103.5", "2026-10-19 10:41", prev="100")
    picked = pick_price(LATEST, BEFORE, q, OPEN, ny("2026-10-19 10:42"))
    assert picked is not None
    v = live_value(position, picked)
    assert v.price == Money(D("103.5"), "USD") and v.price_day == MON
    assert v.price_kind is PriceKind.LIVE and v.price_at == q.quoted_at
    assert v.value == Money(D("1035.00"), "USD") and v.gain == Money(D("135.00"), "USD")
    assert v.day_change == Money(D("35.00"), "USD") and v.day_percent == D("3.50")
    # Without a quote nothing is different: a close, no time.
    closed = value(position, LATEST, BEFORE)
    assert closed.price_kind is PriceKind.CLOSE and closed.price_at is None
    assert closed.day_change == Money(D("20.00"), "USD")


def test_when_a_price_is_from_in_the_users_own_time() -> None:
    at = ny("2026-10-19 10:42")  # 10:42pm in Singapore
    assert describe_price_time(PriceKind.LIVE, at, MON, SINGAPORE) == "at 10:42pm (live)"
    morning = ny("2026-10-19 09:30").astimezone(UTC)  # 9:30pm there; 2:30pm in London
    assert describe_price_time(PriceKind.LIVE, morning, MON, SINGAPORE) == "at 9:30pm (live)"
    assert describe_price_time(PriceKind.LIVE, morning, MON, ZoneInfo("Europe/London")) == (
        "at 2:30pm (live)"
    )
    assert describe_price_time(PriceKind.PROVISIONAL_CLOSE, at, FRI, SINGAPORE) == (
        "at the close (provisional)"
    )
    assert (
        describe_price_time(PriceKind.CLOSE, None, FRI, SINGAPORE) == "at the close on Fri 16 Oct"
    )


# --- the price against the levels ---------------------------------------------------------


def levels(support: list[str], resistance: list[str], fifty: str | None = "170.00") -> Levels:
    averages = {20: D("175"), 200: D("160")}
    if fifty is not None:
        averages[50] = D(fifty)
    return Levels(
        "ACME", SAT, D("178"), averages, None, None, None,
        [D(s) for s in support], [D(r) for r in resistance], D("190"), D("140"), 250,
    )  # fmt: skip


def test_the_price_against_its_averages_and_nearest_levels() -> None:
    facts = now_vs_levels(D("179.70"), levels(["175.50", "168"], ["182", "190"]))
    assert facts == [
        "1.3% below resistance at 182.00",
        "2.3% above support at 175.50",
        "5.7% above its 50-day average (170.00)",
    ]


def test_levels_further_than_five_percent_are_left_out() -> None:
    facts = now_vs_levels(D("179.70"), levels(["150"], ["200"]))
    assert facts == [
        "5.7% above its 50-day average (170.00)",
        "12.3% above its 200-day average (160.00)",
    ]
    # Without the 50-day average (a young stock): only what exists.
    young = levels([], [], fifty=None)
    assert now_vs_levels(D("150"), young) == ["6.3% below its 200-day average (160.00)"]


def test_a_level_the_price_has_moved_through_keeps_its_name() -> None:
    facts = now_vs_levels(D("182.90"), levels(["175.50"], ["182", "190"]))
    assert facts[0] == "0.5% above resistance at 182.00"
    assert now_vs_levels(D("0"), levels([], [])) == []


# --- Finnhub's answers --------------------------------------------------------------------


def finnhub(handler: httpx.MockTransport) -> FinnhubQuotes:
    return FinnhubQuotes(
        httpx.AsyncClient(transport=handler), "test-key", base_url="https://f.test"
    )


async def test_a_quote_from_finnhub() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        symbol = request.url.params["symbol"]
        if symbol == "NONE":  # an unknown symbol answers with zeros
            return httpx.Response(
                200, json={"c": 0, "d": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
            )
        if symbol == "BUSY":
            return httpx.Response(429, json={"error": "API limit reached"})
        if symbol == "DOWN":
            return httpx.Response(503)
        if symbol == "ODD":
            return httpx.Response(200, json={"c": "abc", "t": 1})
        return httpx.Response(
            200,
            json={"c": 261.74, "d": 2.29, "dp": 0.88, "h": 263.31, "l": 260.68, "o": 261.07,
                  "pc": 259.45, "t": 1792420260},
        )  # fmt: skip

    quotes = finnhub(httpx.MockTransport(answer))
    got = await quotes.quote("ACME")
    assert got == Quote(
        "ACME", D("261.7400"), D("259.4500"), D("263.3100"), D("260.6800"), D("261.0700"),
        datetime(2026, 10, 19, 14, 31, tzinfo=UTC),
    )  # fmt: skip
    assert seen[0].url.path == "/quote" and seen[0].headers["X-Finnhub-Token"] == "test-key"
    assert "test-key" not in str(seen[0].url)
    assert await quotes.quote("NONE") is None  # c == 0 and t == 0: no quote
    with pytest.raises(QuoteRateLimited):
        await quotes.quote("BUSY")
    with pytest.raises(QuoteSourceError):
        await quotes.quote("DOWN")
    with pytest.raises(QuoteSourceError):
        await quotes.quote("ODD")


async def test_a_quote_with_a_price_but_no_time_is_no_quote() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"c": 10, "pc": 9, "h": 0, "l": 0, "o": 0, "t": 0})

    assert await finnhub(httpx.MockTransport(answer)).quote("ACME") is None


async def test_the_markets_status_from_finnhub() -> None:
    bodies = iter(
        [
            {"exchange": "US", "holiday": None, "isOpen": True, "session": "regular",
             "t": 1792420260, "timezone": "America/New_York"},
            {"exchange": "US", "holiday": "Made-up Day", "isOpen": False, "session": None,
             "t": 1792420260},
            {"exchange": "US", "holiday": None, "isOpen": False, "session": "post-market"},
            {"exchange": "US", "session": "regular"},
        ]
    )  # fmt: skip
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=next(bodies))

    quotes = finnhub(httpx.MockTransport(answer))
    first = await quotes.market_status()
    assert (first.is_open, first.session, first.holiday) == (True, "regular", None)
    assert first.checked_at == datetime(2026, 10, 19, 14, 31, tzinfo=UTC) and first.regular
    assert seen[0].url.path == "/stock/market-status" and seen[0].url.params["exchange"] == "US"
    assert seen[0].headers["X-Finnhub-Token"] == "test-key"
    holiday = await quotes.market_status()
    assert (holiday.is_open, holiday.holiday) == (False, "Made-up Day") and not holiday.regular
    after = await quotes.market_status()
    assert after.session == "post-market" and after.checked_at > datetime.now(UTC) - timedelta(
        minutes=1
    )
    with pytest.raises(QuoteSourceError):  # no isOpen
        await quotes.market_status()
