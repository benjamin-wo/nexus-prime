"""Trip research rules: which links are safe, which prices are kept, the dates
priced and the budget worked out. Every figure and address here is made up."""

from datetime import date
from decimal import Decimal

from nexus.domain.travel_research import (
    Per,
    PriceRange,
    estimate,
    keep_sourced,
    per_payday,
    price_range,
    round_budget,
    safe_url,
    sources_from,
    trip_window,
    unsourced,
)

D = Decimal
TODAY = date(2026, 9, 28)


def test_only_public_https_links_are_kept() -> None:
    assert (
        safe_url("https://travel.example.com/tokyo?x=1") == "https://travel.example.com/tokyo?x=1"
    )
    for bad in (
        "http://travel.example.com",
        "https://127.0.0.1/admin",
        "https://[::1]/",
        "https://10.0.0.8/",
        "https://user:pass@example.com/",
        "https://example.com:8443/",
        "https://intranet/",
        "https://printer.local/",
        "javascript:alert(1)",
        "file:///etc/passwd",
    ):
        assert safe_url(bad) is None, bad
    found = sources_from(
        [
            ("https://a.example.com/x", "A"),
            ("http://b.example.com", "B"),
            ("https://a.example.com/x", "A again"),
        ],
        TODAY,
    )
    assert [(s.id, s.title) for s in found] == [(1, "A")]


def test_a_price_is_kept_only_with_a_real_source_and_sane_figures() -> None:
    sources = sources_from([("https://a.example.com/hotels", "Hotels")], TODAY)
    kept = price_range("Hotels in Shinjuku", "12,000", "20000", "jpy", "night", 1, sources)
    assert kept == PriceRange(
        "Hotels in Shinjuku", D("12000.00"), D("20000.00"), "JPY", Per.NIGHT, 1
    )
    assert price_range("Hotels", "120", "220", "SGD", "night", 2, sources) is None  # no source 2
    assert price_range("Hotels", "-5", None, "SGD", "night", 1, sources) is None
    assert price_range("Hotels", "120", None, "dollars", "night", 1, sources) is None
    assert price_range("Hotels", "120", None, "SGD", "week", 1, sources) is None
    swapped = price_range("Food", "50", "20", "SGD", "day", "[1]", sources)
    assert swapped is not None and (swapped.low, swapped.high) == (D("20.00"), D("50.00"))


def test_sentences_quoting_unsourced_prices_are_dropped() -> None:
    allowed = [D("120"), D("220")]
    assert unsourced("Go in January 2027 for 7 days; hotels SGD 120 to 220.", allowed) == []
    assert unsourced("A pass is ¥50,000 and dinner 3,000 yen.", allowed) == ["¥50,000", "3,000 yen"]
    text = "It's dry and cold. Hotels run SGD 120 a night. A tour costs USD 99."
    assert keep_sourced(text, allowed) == "It's dry and cold. Hotels run SGD 120 a night."


def test_the_dates_priced() -> None:
    assert trip_window(
        start=date(2027, 1, 5), end=date(2027, 1, 9), month=None, nights=None, today=TODAY
    ) == (
        date(2027, 1, 5),
        date(2027, 1, 9),
    )
    # A month: a week from the 10th; a month already past means next year's.
    assert trip_window(start=None, end=None, month=date(2027, 1, 1), nights=None, today=TODAY) == (
        date(2027, 1, 10),
        date(2027, 1, 17),
    )
    assert trip_window(start=None, end=None, month=date(2026, 9, 1), nights=4, today=TODAY) == (
        date(2027, 9, 10),
        date(2027, 9, 14),
    )


def test_the_budget_is_worked_out_from_sourced_prices() -> None:
    prices = [
        PriceRange("Flights", D("1200"), D("1600"), "SGD", Per.PERSON, 1),
        PriceRange("Hotels", D("150"), D("200"), "SGD", Per.NIGHT, 2),
        PriceRange("Pricier hotels", D("300"), D("500"), "SGD", Per.NIGHT, 3),
        PriceRange("Daily", D("72"), D("135"), "SGD", Per.DAY, 4),
        PriceRange("Rail pass", D("400"), D("400"), "SGD", Per.TRIP, 5),
        PriceRange("Flights in USD", D("100"), D("200"), "USD", Per.PERSON, 6),  # other currency
    ]
    e = estimate(prices, nights=7, travellers=3, currency="SGD")
    assert e is not None
    # Flights x3, the cheaper hotel x7 nights x2 rooms, daily x8 days x3, the pass.
    assert (e.low, e.high) == (
        D("3600") + D("2100") + D("1728") + D("400"),
        D("4800") + D("2800") + D("3240") + D("400"),
    )
    assert (
        estimate([prices[3]], nights=7, travellers=1, currency="SGD") is None
    )  # no stay or flight
    assert per_payday(D("6800"), 3) == D("2267") and per_payday(D("100"), 0) is None
    assert round_budget(D("6760")) == D("6800") and round_budget(D("6800")) == D("6800")


def test_the_typical_range_is_used_when_sources_give_several() -> None:
    flights = [
        PriceRange("Budget airline", D("280"), D("500"), "SGD", Per.PERSON, 1),
        PriceRange("Mid-range", D("700"), D("1000"), "SGD", Per.PERSON, 1),
        PriceRange("Luxury", D("1000"), D("1900"), "SGD", Per.PERSON, 1),
    ]
    e = estimate(flights, nights=7, travellers=1, currency="SGD")
    assert e is not None and (e.low, e.high) == (D("700"), D("1000"))
