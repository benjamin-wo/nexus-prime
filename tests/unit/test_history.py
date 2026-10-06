"""A stock's last year in numbers, from made-up prices. Every ticker and figure here is
made up."""

from datetime import date, timedelta
from decimal import Decimal

from nexus.domain.history import describe, history
from nexus.domain.market import Bar
from nexus.domain.news import EarningsDate

D = Decimal
LAST = date(2026, 9, 25)  # a Friday


def weekdays(n: int) -> list[date]:
    """The last ``n`` weekdays up to LAST, oldest first."""
    days: list[date] = []
    day = LAST
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days[::-1]


def bars(symbol: str, closes: list[float], volumes: list[int] | None = None) -> list[Bar]:
    found = []
    for i, (day, close) in enumerate(zip(weekdays(len(closes)), closes, strict=True)):
        price = D(f"{close:.2f}")
        volume = volumes[i] if volumes else 1_000
        found.append(Bar(symbol, day, price, price, price, price, price, volume))
    return found


def test_too_little_history_says_nothing() -> None:
    assert history(bars("ACME", [100.0] * 20)) is None


def test_returns_falls_and_the_high() -> None:
    # Up 50% over the year to a high, then down 10% in the last 21 days.
    closes = [100 + 50 * i / 231 for i in range(232)] + [150 - 15 * i / 21 for i in range(1, 22)]
    h = history(bars("ACME", closes))
    assert h is not None
    changes = {c.label: c.percent for c in h.changes}
    assert list(changes) == ["1 week", "1 month", "3 months", "6 months", "1 year", "this year"]
    assert changes["1 month"] == D("-10.0")  # 150 to 135
    assert changes["1 year"] == D("35.0")  # 100 to 135
    assert h.from_high == D("-10.0") and h.worst_drop == D("-10.0")
    assert h.high_day == weekdays(253)[231] and h.worst_to == LAST
    lines = describe(h)
    assert lines[0].startswith("Change in price: 1 week ")
    assert "1 year +35.0%" in lines[0]
    assert lines[1].startswith("10.0% below its highest close of the last year (")
    assert lines[2].startswith("Its deepest fall in the last year: -10.0% (")


def test_busier_than_usual_and_more_shares_traded() -> None:
    # Calm for a year (0.5% a day either way), then 3% a day either way.
    calm = [100 * (1.005 if i % 2 else 0.995) for i in range(232)]
    rough = [100 * (1.03 if i % 2 else 0.97) for i in range(21)]
    volumes = [1_000] * 232 + [2_000] * 21
    h = history(bars("ACME", calm + rough, volumes))
    assert h is not None and h.move_now is not None and h.move_normal is not None
    assert h.move_now > 2 * h.move_normal
    assert h.volume_change is not None and h.volume_change > D("50")
    lines = describe(h)
    assert any("(busier than usual)" in line for line in lines)
    assert any(
        line.startswith("Shares traded over the last month: ") and "% above the year's" in line
        for line in lines
    )


def test_volume_near_its_average_says_so() -> None:
    h = history(bars("ACME", [100.0 + i % 3 for i in range(100)]))
    assert h is not None and h.volume_change == 0
    assert "Shares traded over the last month: about the year's average" in describe(h)


def test_against_the_market() -> None:
    stock = bars("ACME", [100 + i * 0.2 for i in range(253)])  # 100 to 150.4
    market = bars("SPY", [400 + i * 0.4 for i in range(253)])  # 400 to 500.8
    h = history(stock, market)
    assert h is not None
    year = next(v for v in h.versus if v.label == "1 year")
    assert (year.stock, year.market) == (D("50.4"), D("25.2"))
    line = next(x for x in describe(h) if x.startswith("Against the US market"))
    assert "1 year +50.4% against +25.2%" in line
    # Without the market's prices there's nothing to compare.
    assert history(stock).versus == []  # type: ignore[union-attr]


def test_moves_on_past_earnings() -> None:
    days = weekdays(60)
    closes = [100.0] * 60
    # After the close on day 20: up 8% the next day. Before the open on day 40: down 5%.
    for i in range(21, 60):
        closes[i] = 108.0
    for i in range(40, 60):
        closes[i] = 102.6
    h = history(
        bars("ACME", closes),
        earnings=[
            EarningsDate("ACME", days[20], "after close"),
            EarningsDate("ACME", days[40], "before open"),
            EarningsDate("ACME", LAST + timedelta(days=30), None),  # still to come
        ],
    )
    assert h is not None
    assert [(r.day, r.percent) for r in h.earnings] == [(days[40], D("-5.0")), (days[20], D("8.0"))]
    line = describe(h)[-1]
    assert line.startswith(f"Moves on its last earnings: {days[40]:%d %b} -5.0%, ")
    assert line.endswith("(about 6.5% either way on average)")


def test_the_history_never_reads_as_a_price() -> None:
    from nexus.domain.plans import unsupported

    closes = [100 + i * 0.2 for i in range(253)]
    h = history(bars("ACME", closes), bars("SPY", [400 + i * 0.4 for i in range(253)]))
    assert h is not None
    for line in describe(h):
        assert unsupported(line, set()) == [], line
