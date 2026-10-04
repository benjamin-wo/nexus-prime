"""Levels from daily prices, checked against hand-worked figures, and news
cleaning. Every ticker, price and headline here is made up."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from nexus.application.research import NewsRateLimited, NewsSourceError
from nexus.domain.levels import atr, compute, describe, rsi, sma, swings
from nexus.domain.market import Bar
from nexus.domain.news import NewsItem, clean_text, dedupe, safe_url
from nexus.infra.market.finnhub import FinnhubNews

D = Decimal
START = date(2026, 1, 1)


def bar(i: int, close: str, high: str | None = None, low: str | None = None) -> Bar:
    c = D(close)
    return Bar("ACME", START + timedelta(days=i), c, D(high or close), D(low or close), c, c, 1)


def test_moving_average_and_rsi() -> None:
    closes = [D(n) for n in range(1, 31)]
    assert sma(closes, 20) == D("20.5")
    assert sma(closes, 50) is None
    assert rsi(closes) == 100  # only rises
    assert rsi([D(n) for n in range(30, 0, -1)]) == 0  # only falls
    flat_then = [D(10), D(11)] * 10
    value = rsi(flat_then)
    assert value is not None and D(45) < value < D(55)  # even ups and downs: about 50
    assert rsi(closes[:14]) is None


def test_atr_is_the_typical_daily_range() -> None:
    # Every day ranges 2 around a flat close: the true range is 2.
    days = [bar(i, "100", "101", "99") for i in range(20)]
    from nexus.domain.levels import adjust

    assert atr(adjust(days)) == D(2)
    assert atr(adjust(days[:14])) is None


def test_swing_highs_and_lows() -> None:
    from nexus.domain.levels import adjust

    prices = ["10", "11", "12", "13", "14", "15", "14", "13", "12", "11", "10", "11", "12", "13"]
    days = [bar(i, p) for i, p in enumerate(prices)]
    highs, lows = swings(adjust(days), side=3)
    assert highs == [D(15)]
    assert lows == [D(10)]


def test_levels_from_a_made_up_history() -> None:
    # A rise to 120, a dip to 105, a rally to 130, then a pullback to 118.
    path = (
        [100] * 5  # flat
        + [100 + i for i in range(21)]  # 100 → 120
        + [120 - i * 1.5 for i in range(1, 11)]  # → 105
        + [105 + i * 2.5 for i in range(1, 11)]  # → 130
        + [130 - i * 2 for i in range(1, 7)]  # → 118
    )
    bars = [bar(i, f"{p:.2f}", f"{p + 1:.2f}", f"{p - 1:.2f}") for i, p in enumerate(path)]
    levels = compute(bars)
    assert levels is not None
    assert levels.close == D("118.00")
    assert set(levels.averages) == {20, 50}
    assert levels.trend is None  # no 200-day average yet
    assert levels.resistance == [D("121.00"), D("131.00")]  # the first top, then the rally
    assert levels.support == [D("104.00"), D("99.00")]  # the dip, then the flat start
    assert levels.year_high == D("131.00") and levels.year_low == D("99.00")
    assert levels.rsi is not None and levels.atr is not None
    text = describe(levels)
    assert text[0] == f"Close 118.00 on {bars[-1].day:%d %b %Y}"
    assert "Support (recent swing lows): 104.00, 99.00" in text
    assert compute(bars[:10]) is None


def test_a_split_doesnt_look_like_a_crash() -> None:
    # 2-for-1 halfway: raw prices halve, adjusted ones don't.
    bars = []
    for i in range(40):
        raw = D(200) if i < 20 else D(100)
        bars.append(Bar("ACME", START + timedelta(days=i), raw, raw, raw, raw, D(100), 1))
    levels = compute(bars)
    assert levels is not None and levels.year_high == D(100) and levels.year_low == D(100)


def test_news_text_is_cleaned() -> None:
    assert clean_text("  Acme​ beats\n\testimates\x07 ", 100) == "Acme beats estimates"
    assert clean_text("x" * 10, 5) == "xxxx…"
    assert safe_url("https://news.example/acme") == "https://news.example/acme"
    for bad in ("javascript:alert(1)", "ftp://x/y", "https://", "https://a b/c", None):
        assert safe_url(bad) is None


def item(i: int, headline: str, hours: int) -> NewsItem:
    at = datetime(2026, 9, 25, tzinfo=UTC) + timedelta(hours=hours)
    return NewsItem("ACME", str(i), headline, "Wire", f"https://n.example/{i}", "", at)


def test_the_same_story_is_kept_once() -> None:
    items = [
        item(1, "Acme beats estimates", 2),
        item(2, "ACME beats estimates!", 1),
        item(3, "Other", 3),
    ]
    kept = dedupe(items)
    assert [i.external_id for i in kept] == ["3", "2"]


async def test_finnhub_news_and_earnings() -> None:
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params.get("symbol") == "BUSY":
            return httpx.Response(429)
        if request.url.params.get("symbol") == "DOWN":
            return httpx.Response(500)
        if request.url.path.endswith("/company-news"):
            return httpx.Response(
                200,
                json=[
                    {"id": 7, "datetime": 1790000000, "headline": "Acme opens a plant",
                     "source": "Wire", "url": "https://n.example/7", "summary": "Made up."},
                    {"id": 8, "datetime": 1790000100, "headline": "Bad link",
                     "source": "Wire", "url": "javascript:alert(1)"},
                    {"id": 9, "headline": "No date", "url": "https://n.example/9"},
                ],
            )  # fmt: skip
        return httpx.Response(
            200,
            json={
                "earningsCalendar": [
                    {"date": "2026-10-29", "hour": "amc", "symbol": "ACME"},
                    {"date": "2026-10-30", "hour": "", "symbol": "OTHER"},
                    {"date": "not a date", "symbol": "ACME"},
                ]
            },
        )

    news = FinnhubNews(
        httpx.AsyncClient(transport=httpx.MockTransport(answer)), "k", base_url="https://f.test"
    )
    items = await news.news("ACME", date(2026, 9, 18), date(2026, 9, 25))
    assert [(i.external_id, i.headline) for i in items] == [("7", "Acme opens a plant")]
    assert seen[0].headers["X-Finnhub-Token"] == "k" and "k" not in seen[0].url.params.values()
    dates = await news.earnings("ACME", date(2026, 9, 25), date(2026, 12, 24))
    assert [(d.day, d.timing) for d in dates] == [(date(2026, 10, 29), "after close")]
    with pytest.raises(NewsRateLimited):
        await news.news("BUSY", date(2026, 9, 18), date(2026, 9, 25))
    with pytest.raises(NewsSourceError):
        await news.earnings("DOWN", date(2026, 9, 25), date(2026, 12, 24))
