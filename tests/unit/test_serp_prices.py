"""Live fares, product prices and flight status through SerpApi: what is asked of each
engine, how its answers are read, and what the chat tools tell the model. Every figure,
store and flight here is made up; the shapes follow SerpApi's documentation."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest

from nexus.agent import price_text
from nexus.agent.tools import (
    FlightPricesArgs,
    ToolContext,
    ToolResult,
    build_tools,
    run_tool,
    safe_for_images,
)
from nexus.application.serp_budget import SearchesPaused, Spend, first_of_next_month
from nexus.application.web_search import WebSearchError
from nexus.domain import airports
from nexus.domain.ledger import Role, User, UserId
from nexus.domain.live_prices import (
    CalendarQuery,
    FareCalendar,
    FlightFares,
    FlightQuery,
    FlightStatus,
    ProductPrices,
    ProductQuery,
    StatusQuery,
    currency_of,
    flight_number,
)
from nexus.domain.source_links import PREFIX
from nexus.evals.prices import CannedPrices
from nexus.infra.search.serpapi import (
    SerpApiClient,
    calendar_params,
    flights_params,
    parse_calendar,
    parse_flights,
    parse_shopping,
    parse_status,
    shopping_params,
    status_params,
)

NOW = datetime(2026, 11, 10, 8, 30, tzinfo=UTC)
TODAY = date(2026, 11, 10)
KEY = "sk-test-not-a-real-key-123"

FLIGHT = FlightQuery("SIN", "BKK", date(2026, 12, 10), date(2026, 12, 17), 2, "economy", "SGD")
ONE_WAY = FlightQuery("SIN", "BKK", date(2026, 12, 10), None, 1, "business", "SGD")


def _segment(
    airline: str, number: str, dep: str, depart: str, arr: str, arrive: str, minutes: int
) -> dict[str, Any]:
    return {
        "departure_airport": {"name": dep, "id": dep, "time": depart},
        "arrival_airport": {"name": arr, "id": arr, "time": arrive},
        "duration": minutes,
        "airline": airline,
        "flight_number": number,
    }


def _trip(price: int, *segments: dict[str, Any], layover: str | None = None) -> dict[str, Any]:
    trip: dict[str, Any] = {
        "flights": list(segments),
        "total_duration": sum(s["duration"] for s in segments) + (60 if layover else 0),
        "price": price,
        "type": "Round trip",
        "departure_token": "TOKEN-NOT-A-URL",
    }
    if layover:
        trip["layovers"] = [{"duration": 60, "name": "Kuala Lumpur", "id": layover}]
    return trip


def flights_response() -> dict[str, Any]:
    scoot = _segment("Scoot", "TR 868", "SIN", "2026-12-10 07:30", "BKK", "2026-12-10 09:00", 150)
    sia = _segment(
        "Singapore Airlines", "SQ 976", "SIN", "2026-12-10 10:15", "BKK", "2026-12-10 11:40", 145
    )
    leg1 = _segment("AirAsia", "AK 704", "SIN", "2026-12-10 06:10", "KUL", "2026-12-10 07:10", 60)
    leg2 = _segment("AirAsia", "AK 877", "KUL", "2026-12-10 08:10", "BKK", "2026-12-10 09:40", 120)
    return {
        "search_metadata": {
            "status": "Success",
            "google_flights_url": "https://www.google.com/travel/flights?hl=en&curr=SGD",
            "json_endpoint": "https://serpapi.com/searches/abc/def.json",
        },
        "best_flights": [_trip(620, sia), _trip(360, leg1, leg2, layover="KUL")],
        "other_flights": [
            _trip(380, scoot),
            _trip(520, leg1, leg2, layover="KUL"),
            _trip(700, sia),
            _trip(900, sia),
            {"flights": [], "price": 1},  # no flights: skipped
            {"flights": [scoot]},  # no price: skipped
        ],
        "price_insights": {
            "lowest_price": 360,
            "price_level": "Low",
            "typical_price_range": [420, 640],
            "price_history": [[1, 2]],
        },
    }


def calendar_response() -> dict[str, Any]:
    return {
        "search_metadata": {"google_flights_calendar_url": "https://www.google.com/travel/flights"},
        "prices": [
            {"outbound_date": "2026-12-03", "return_date": "2026-12-10", "price": 410},
            {"outbound_date": "2026-12-01", "return_date": "2026-12-08", "price": 380},
            {
                "outbound_date": "2026-12-02",
                "return_date": "2026-12-09",
                "price": 360,
                "low_price": True,
            },
            {
                "outbound_date": "2026-12-04",
                "return_date": "2026-12-11",
                "price": 365,
                "low_price": True,
            },
            {"outbound_date": "2026-12-05", "return_date": "2026-12-12", "price": 520},
            {"outbound_date": "2026-12-06", "return_date": "2026-12-13", "price": 495},
            {"outbound_date": "bad", "price": 1},
            {"outbound_date": "2026-12-07", "price": None},
        ],
    }


def shopping_response() -> dict[str, Any]:
    def item(
        title: str, price: float | None, store: str, link: str | None, **more: Any
    ) -> dict[str, Any]:
        found: dict[str, Any] = {"title": title, "source": store, "link": link, **more}
        if price is not None:
            found["extracted_price"] = price
            found["price"] = f"S${price:,.2f}"
        return found

    return {
        "search_metadata": {"google_shopping_url": "https://www.google.com/search?udm=28&q=x"},
        "shopping_results": [
            item(
                "Frobnicator 2 Console",
                529.9,
                "Demo Electronics",
                "https://electronicsdemo.com/a",
                rating=4.4,
            ),
            item(
                "Frobnicator 2 Console",
                499.0,
                "Example Mart",
                "https://martexample.com/a",
                rating=4.7,
            ),
            item("Frobnicator 2 Bundle", 559.0, "Sample Store", "http://samplestore.org/insecure"),
            item(
                "Frobnicator 2 Console", 499.0, "Example Mart", "https://martexample.com/a"
            ),  # again
            item(
                "Frobnicator 2 Console",
                515.0,
                "Nowhere Shop",
                None,
                product_link="https://www.google.com/x",
            ),
            item("Frobnicator 2 Carry Case", 19.9, "Case Shop", "https://casedemo.net/c"),
            item("No price", None, "Ghost", "https://ghostshop.com"),
        ],
        "inline_shopping_results": [
            item("Frobnicator 2 Console", 545.0, "Another Shop", "https://anothershop.com.sg/z"),
        ],
        "categorized_shopping_results": [
            {
                "title": "Consoles",
                "shopping_results": [
                    item("Frobnicator 2 Console", 539.0, "Deep Store", "https://deepstore.io/q"),
                    item("Frobnicator 2 Console", 551.0, "Local IP", "https://10.0.0.1/a"),
                ],
            }
        ],
    }


def status_response() -> dict[str, Any]:
    return {
        "flight_result": {
            "title": "Example Air XY 123",
            "flight_designator": "XY 123",
            "route": "Singapore to Bangkok",
            "airline": "Example Air",
            "dates": [
                {
                    "date": "2026-11-09",
                    "metadata": {"status": "ARRIVED", "departure_delay": 0, "arrival_delay": -5},
                },
                {
                    "date": "2026-11-10",
                    "metadata": {
                        "status": "DEPARTING_LATE",
                        "departure_delay": 25,
                        "arrival_delay": 20,
                    },
                    "departure_airport": {
                        "id": "SIN",
                        "city": "Singapore",
                        "time": "2026-11-10T09:05:00.000+08:00",
                        "scheduled_time": "2026-11-10T08:40:00.000+08:00",
                        "terminal": "3",
                        "gate": "B12",
                        "status": "Scheduled",
                    },
                    "arrival_airport": {
                        "id": "BKK",
                        "city": "Bangkok",
                        "time": "2026-11-10T10:30:00.000+07:00",
                        "scheduled_time": "2026-11-10T10:10:00.000+07:00",
                        "terminal": "1",
                        "gate": "-",
                    },
                    "source": "Example Tracker",
                    "source_url": "https://tracker.example.com/flight/XY123",
                    "updated_at": "2026-11-10T08:20:00.000Z",
                    "status": "Delayed",
                },
                {"date": "2026-11-12", "metadata": {"status": "SCHEDULED_STATUS"}},
            ],
        }
    }


# --- what is asked of each engine ------------------------------------------------------------


def test_a_return_search_asks_google_flights_for_both_days() -> None:
    assert flights_params(FLIGHT) == {
        "engine": "google_flights",
        "departure_id": "SIN",
        "arrival_id": "BKK",
        "outbound_date": "2026-12-10",
        "return_date": "2026-12-17",
        "type": "1",
        "currency": "SGD",
        "adults": "2",
        "travel_class": "1",
    }


def test_a_one_way_search_has_no_return_date_and_asks_for_its_cabin() -> None:
    params = flights_params(ONE_WAY)
    assert params["type"] == "2"
    assert params["travel_class"] == "3"
    assert "return_date" not in params


def test_the_calendar_asks_for_a_window_and_the_length_of_the_trip() -> None:
    q = CalendarQuery("SIN", "BKK", date(2026, 12, 1), date(2026, 12, 31), 7, 1, "economy", "SGD")
    assert calendar_params(q) == {
        "engine": "google_flights_calendar",
        "departure_id": "SIN",
        "arrival_id": "BKK",
        "type": "1",
        "date_range_start": "2026-12-01",
        "date_range_end": "2026-12-31",
        "currency": "SGD",
        "adults": "1",
        "travel_class": "1",
        "round_trip_days": "7",
    }
    one_way = calendar_params(
        CalendarQuery("SIN", "BKK", q.start, q.end, None, 1, "economy", "SGD")
    )
    assert one_way["type"] == "2"
    assert "round_trip_days" not in one_way


def test_shopping_is_asked_as_singapore_and_status_as_a_plain_search() -> None:
    assert shopping_params(ProductQuery("frobnicator 2")) == {
        "engine": "google_shopping",
        "q": "frobnicator 2",
        "gl": "sg",
    }
    assert status_params(StatusQuery("SQ12", None)) == {
        "engine": "google",
        "q": "SQ12 flight status",
    }


async def test_the_key_goes_in_the_request_and_never_in_what_is_raised() -> None:
    seen: list[httpx.Request] = []

    class Allow:
        async def reserve(self, spend: Spend) -> None:
            return None

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params["q"] == "boom":
            raise httpx.ConnectError(f"cannot reach {request.url}")
        if request.url.params["q"] == "down":
            return httpx.Response(503, text=str(request.url))
        if request.url.params["q"] == "html":
            return httpx.Response(200, text="<html>")
        if request.url.params["q"] == "nothing":
            return httpx.Response(200, json={"error": "Google hasn't returned any results."})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SerpApiClient(http, KEY, Allow())
        assert await client.get({"engine": "google", "q": "fine"}, Spend()) == {"ok": True}
        assert seen[0].url.params["api_key"] == KEY
        for q in ("boom", "down", "html", "nothing"):
            with pytest.raises(WebSearchError) as raised:
                await client.get({"engine": "google", "q": q}, Spend())
            assert KEY not in str(raised.value)
            assert "serpapi.com" not in str(raised.value)


async def test_no_request_is_made_when_the_budget_says_no() -> None:
    class Refuse:
        async def reserve(self, spend: Spend) -> None:
            raise SearchesPaused("month", date(2026, 12, 1))

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("a search was made")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SearchesPaused):
            await SerpApiClient(http, KEY, Refuse()).get({"engine": "google"}, Spend())


# --- how the answers are read ------------------------------------------------------------------


def test_fares_are_the_cheapest_few_and_the_cheapest_nonstop_with_google_s_price_insight() -> None:
    found = parse_flights(flights_response(), FLIGHT, NOW)
    assert [(o.airline, o.price) for o in found.options] == [
        ("AirAsia", Decimal(360)),
        ("Scoot", Decimal(380)),  # the cheapest nonstop is among the three cheapest
        ("AirAsia", Decimal(520)),
    ]
    first, second = found.options[0], found.options[1]
    assert (first.stops, first.via, first.minutes) == (1, ["KUL"], 60 + 120 + 60)
    assert (first.departs, first.arrives) == ("2026-12-10 06:10", "2026-12-10 09:40")
    assert first.flights == ["AK 704", "AK 877"]
    assert (second.stops, second.flights, second.departs) == (0, ["TR 868"], "2026-12-10 07:30")
    insight = found.insight
    assert insight is not None
    assert (insight.level, insight.lowest) == ("low", Decimal(360))
    assert (insight.typical_low, insight.typical_high) == (Decimal(420), Decimal(640))
    assert found.url == "https://www.google.com/travel/flights?hl=en&curr=SGD"
    assert found.checked_at == NOW


def test_the_cheapest_nonstop_is_shown_even_when_it_is_not_among_the_cheapest_three() -> None:
    data = flights_response()
    data["best_flights"] = []
    leg1 = _segment("AirAsia", "AK 704", "SIN", "2026-12-10 06:10", "KUL", "2026-12-10 07:10", 60)
    leg2 = _segment("AirAsia", "AK 877", "KUL", "2026-12-10 08:10", "BKK", "2026-12-10 09:40", 120)
    data["other_flights"] = [_trip(p, leg1, leg2, layover="KUL") for p in (400, 410, 420, 430)] + [
        _trip(
            620,
            _segment(
                "Singapore Airlines",
                "SQ 976",
                "SIN",
                "2026-12-10 10:15",
                "BKK",
                "2026-12-10 11:40",
                145,
            ),
        )
    ]
    found = parse_flights(data, FLIGHT, NOW)
    assert [(o.stops, o.price) for o in found.options] == [
        (1, Decimal(400)),
        (1, Decimal(410)),
        (1, Decimal(420)),
        (0, Decimal(620)),
    ]


def test_fares_without_an_insight_or_a_link_still_read() -> None:
    data = flights_response()
    del data["price_insights"]
    data["search_metadata"]["google_flights_url"] = "http://www.google.com/travel/flights"
    found = parse_flights(data, FLIGHT, NOW)
    assert found.insight is None
    assert found.url is None
    empty = parse_flights({"search_metadata": {}}, FLIGHT, NOW)
    assert empty.options == []


def test_the_calendar_is_in_date_order_and_skips_what_it_cannot_read() -> None:
    q = CalendarQuery("SIN", "BKK", date(2026, 12, 1), date(2026, 12, 7), 7, 1, "economy", "SGD")
    found = parse_calendar(calendar_response(), q, NOW)
    assert [d.outbound.day for d in found.days] == [1, 2, 3, 4, 5, 6]
    assert [d.cheap for d in found.days] == [False, True, False, True, False, False]
    assert found.days[1].back == date(2026, 12, 9)


def test_shopping_offers_are_sorted_capped_https_only_and_without_accessories() -> None:
    found = parse_shopping(shopping_response(), ProductQuery("frobnicator 2"), NOW)
    assert [(o.store, o.price) for o in found.offers] == [
        ("Example Mart", Decimal("499.0")),
        ("Nowhere Shop", Decimal("515.0")),
        ("Demo Electronics", Decimal("529.9")),
        ("Deep Store", Decimal("539.0")),
        ("Another Shop", Decimal("545.0")),
    ]  # five at most; the S$19.90 case is left out, "No price" has none, the repeat is one
    assert [o.link for o in found.offers] == [
        "https://martexample.com/a",
        "https://www.google.com/x",
        "https://electronicsdemo.com/a",
        "https://deepstore.io/q",
        "https://anothershop.com.sg/z",
    ]
    assert found.offers[0].currency == "SGD"
    assert found.offers[0].rating == 4.7
    assert found.offers[1].rating is None
    assert found.url == "https://www.google.com/search?udm=28&q=x"


def test_a_web_address_in_a_title_or_store_name_is_taken_out() -> None:
    found = parse_shopping(
        {
            "shopping_results": [
                {
                    "title": "Frobnicator 2 https://evil.example.net/x now www.evil.example.net",
                    "extracted_price": 5,
                    "source": "visit http://evil.example.net",
                }
            ]
        },
        ProductQuery("x"),
        NOW,
    )
    assert [(o.title, o.store) for o in found.offers] == [("Frobnicator 2 now", "visit")]


def test_an_insecure_or_private_link_is_not_kept_but_the_offer_is() -> None:
    found = parse_shopping(shopping_response(), ProductQuery("x"), NOW)
    everything = parse_shopping(
        {
            "shopping_results": [
                {"title": "A", "extracted_price": 5, "source": "S", "link": "http://a.example.com"},
                {"title": "B", "price": "S$6.50", "source": "T", "link": "https://127.0.0.1/x"},
            ]
        },
        ProductQuery("x"),
        NOW,
    )
    assert [(o.title, o.price, o.link) for o in everything.offers] == [
        ("A", Decimal(5), None),
        ("B", Decimal("6.50"), None),
    ]
    assert all(o.link is None or o.link.startswith("https://") for o in found.offers)


def test_a_status_is_read_for_the_day_asked_with_times_gate_and_terminal() -> None:
    found = parse_status(status_response(), StatusQuery("XY123", None), TODAY, NOW)
    assert found.found
    assert (found.day, found.status, found.airline) == (TODAY, "Delayed", "Example Air")
    out, arrive = found.departure, found.arrival
    assert out is not None
    assert arrive is not None
    assert (out.airport, out.scheduled, out.estimated) == (
        "SIN",
        "2026-11-10 08:40",
        "2026-11-10 09:05",
    )
    assert (out.terminal, out.gate, out.state) == ("3", "B12", "Scheduled")
    assert arrive.gate is None  # Google writes "-" for none
    assert (found.departure_delay, found.arrival_delay) == (25, 20)
    assert found.source_url == "https://tracker.example.com/flight/XY123"
    assert found.other_days == ["2026-11-09", "2026-11-10", "2026-11-12"]


def test_a_day_with_only_a_status_reads_without_times() -> None:
    found = parse_status(status_response(), StatusQuery("XY123", date(2026, 11, 12)), TODAY, NOW)
    assert found.found
    assert found.status == "scheduled"
    assert found.departure is None
    assert found.arrival is None


def test_a_day_google_has_no_status_for_says_which_days_it_has() -> None:
    found = parse_status(status_response(), StatusQuery("XY123", date(2026, 11, 30)), TODAY, NOW)
    assert not found.found
    assert found.other_days == ["2026-11-09", "2026-11-10", "2026-11-12"]
    nothing = parse_status({"organic_results": []}, StatusQuery("XY123", None), TODAY, NOW)
    assert not nothing.found
    assert nothing.other_days == []


def test_with_no_day_asked_and_none_today_the_next_one_it_has() -> None:
    later = date(2026, 11, 11)
    found = parse_status(status_response(), StatusQuery("XY123", None), later, NOW)
    assert found.day == date(2026, 11, 12)


# --- small rules ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("place", "codes"),
    [
        ("BKK", "BKK"),
        ("bkk", "BKK"),
        ("Bangkok", "BKK,DMK"),
        ("  tokyo ", "HND,NRT"),
        ("Tokyo (NRT)", "NRT"),
        ("Paris, France", "CDG,ORY"),
        ("NRT, HND", "NRT,HND"),
        ("Zürich", "ZRH"),
        ("Sao Paulo", "GRU,CGH"),
        ("São Paulo", "GRU,CGH"),
        ("rio", "GIG,SDU"),
        ("/m/0fn2g", "/m/0fn2g"),
        ("Atlantis", None),
        ("", None),
    ],
)
def test_places_become_airports(place: str, codes: str | None) -> None:
    assert airports.resolve(place) == codes


@pytest.mark.parametrize(
    ("raw", "number"),
    [("sq12", "SQ12"), ("SQ 012", "SQ12"), ("ba-285", "BA285"), ("9W 123", "9W123"), ("x", None),
     ("SQ", None), ("SQ12345", None), ("hello world", None)],
)  # fmt: skip
def test_flight_numbers(raw: str, number: str | None) -> None:
    assert flight_number(raw) == number


def test_a_store_s_currency_is_known_when_it_says_which() -> None:
    assert currency_of("S$499.00") == "SGD"
    assert currency_of("SGD 499") == "SGD"
    assert currency_of("US$10") == "USD"
    assert currency_of("$10") is None


def test_the_month_ends_on_the_first_of_the_next() -> None:
    assert first_of_next_month(datetime(2026, 11, 30, 23, 59, tzinfo=UTC)) == date(2026, 12, 1)
    assert first_of_next_month(datetime(2026, 12, 31, tzinfo=UTC)) == date(2027, 1, 1)


# --- what the tools tell the model --------------------------------------------------------------

SGT = ZoneInfo("Asia/Singapore")


def _user() -> User:
    return User(
        id=UserId(uuid4()),
        telegram_user_id=1,
        telegram_chat_id=1,
        timezone="Asia/Singapore",
        home_currency="SGD",
        role=Role.OWNER,
        created_at=NOW,
    )


def _ctx(prices: Any) -> ToolContext:
    def no_uow() -> Any:  # pragma: no cover - the price tools never open one
        raise AssertionError

    return ToolContext(_user(), no_uow, NOW, prices=prices)


class Scripted:
    """A price source with the answers given, or an error to raise."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.asked: list[Any] = []
        self.canned = CannedPrices(NOW)

    async def flights(self, user: UserId, q: FlightQuery, today: date) -> FlightFares:
        self.asked.append((q, today))
        if self.error:
            raise self.error
        return parse_flights(flights_response(), q, NOW)

    async def calendar(self, user: UserId, q: CalendarQuery, today: date) -> FareCalendar:
        self.asked.append((q, today))
        if self.error:
            raise self.error
        return parse_calendar(calendar_response(), q, NOW)

    async def products(self, user: UserId, q: ProductQuery, today: date) -> ProductPrices:
        self.asked.append((q, today))
        if self.error:
            raise self.error
        return parse_shopping(shopping_response(), q, NOW)

    async def status(self, user: UserId, q: StatusQuery, today: date) -> FlightStatus:
        self.asked.append((q, today))
        if self.error:
            raise self.error
        return parse_status(status_response(), q, today, NOW)


async def _run(name: str, prices: Any, **args: Any) -> ToolResult:
    return await run_tool(build_tools(lambda _: "")[name], _ctx(prices), args)


def _no_addresses(text: str) -> None:
    assert "http" not in text.lower()
    assert "www." not in text.lower()


async def test_flight_prices_gives_fares_the_time_checked_and_a_source_button() -> None:
    source = Scripted()
    result = await _run(
        "flight_prices", source, origin="Singapore", destination="Bangkok",
        outbound_date="2026-12-10", return_date="2026-12-17", adults=2,
    )  # fmt: skip
    q, today = source.asked[0]
    assert (q.origin, q.destination, q.currency, q.adults) == ("SIN", "BKK,DMK", "SGD", 2)
    assert today == date(2026, 11, 10)
    text = result.text
    assert "10 Nov 16:30" in text  # checked, on the user's clock (Singapore)
    assert "SGD 360" in text
    assert "1 stop via KUL" in text
    assert "nonstop" in text
    assert "low for this route" in text
    assert "SGD 420 to SGD 640" in text
    assert "nothing is booked or bought" in text
    assert "Google Flights" in text
    _no_addresses(text)
    assert result.buttons == [
        [("Google Flights ↗", f"{PREFIX}https://www.google.com/travel/flights?hl=en&curr=SGD")]
    ]


async def test_flight_prices_in_calendar_mode_finds_the_cheapest_days() -> None:
    source = Scripted()
    result = await _run(
        "flight_prices", source, origin="SIN", destination="BKK",
        cheapest_from="2026-12-01", cheapest_to="2026-12-31", trip_days=7,
    )  # fmt: skip
    q, _ = source.asked[0]
    assert isinstance(q, CalendarQuery)
    assert (q.start, q.end, q.trip_days) == (date(2026, 12, 1), date(2026, 12, 31), 7)
    first = result.text.splitlines()[1]
    assert first.startswith("- Wed 2 Dec, back Wed 9 Dec: SGD 360")
    assert "dearest is Sat 5 Dec at SGD 520" in result.text
    assert "nothing is booked or bought" in result.text
    _no_addresses(result.text)
    assert result.buttons is None


async def test_a_window_in_the_past_starts_today_and_a_wide_one_is_refused() -> None:
    source = Scripted()
    await _run(
        "flight_prices", source, origin="SIN", destination="BKK",
        cheapest_from="2026-11-01", cheapest_to="2026-11-30",
    )  # fmt: skip
    assert source.asked[0][0].start == TODAY
    wide = await _run(
        "flight_prices", source, origin="SIN", destination="BKK",
        cheapest_from="2026-12-01", cheapest_to="2027-03-31",
    )  # fmt: skip
    assert wide.text.startswith("Error: ") and "narrower" in wide.text
    assert len(source.asked) == 1  # nothing asked for the refused one


@pytest.mark.parametrize(
    ("args", "says"),
    [
        (
            {"origin": "Atlantis", "destination": "BKK", "outbound_date": "2026-12-10"},
            "which airport",
        ),
        ({"origin": "SIN", "destination": "SIN", "outbound_date": "2026-12-10"}, "same place"),
        ({"origin": "SIN", "destination": "BKK", "outbound_date": "2026-11-01"}, "in the past"),
        ({"origin": "SIN", "destination": "BKK", "outbound_date": "2028-11-01"}, "too far ahead"),
        (
            {
                "origin": "SIN",
                "destination": "BKK",
                "outbound_date": "2026-12-10",
                "return_date": "2026-12-01",
            },
            "before the outbound",
        ),
        ({"origin": "SIN", "destination": "BKK"}, "outbound date is needed"),
    ],
)
async def test_flight_prices_refuses_what_it_cannot_search_without_spending_a_search(
    args: dict[str, str], says: str
) -> None:
    source = Scripted()
    result = await _run("flight_prices", source, **args)
    assert result.text.startswith("Error: ")
    assert says in result.text
    assert source.asked == []


async def test_product_prices_lists_offers_with_store_price_and_up_to_three_https_buttons() -> None:
    source = Scripted()
    result = await _run("product_prices", source, query="  Frobnicator   2 Console ")
    assert source.asked[0][0].query == "frobnicator 2 console"  # normalised, so a repeat is kept
    lines = result.text.splitlines()
    assert lines[1].startswith(
        "1. Frobnicator 2 Console: S$499.00 (SGD) at Example Mart, rated 4.7/5"
    )
    assert "cheapest first" in lines[0]
    assert "nothing is booked or bought" in result.text
    assert "Google Shopping" in result.text
    _no_addresses(result.text)
    assert result.buttons is not None
    buttons = [b for row in result.buttons for b in row]
    assert len(buttons) == 3
    assert all(data.startswith(f"{PREFIX}https://") for _, data in buttons)


async def test_flight_status_gives_times_gate_and_terminal_and_when_it_was_checked() -> None:
    source = Scripted()
    result = await _run("flight_status", source, flight="xy 123")
    assert source.asked[0][0] == StatusQuery("XY123", None)
    text = result.text
    assert "Status: Delayed (Example Air, Singapore to Bangkok)" in text
    assert "Departure SIN (Singapore), terminal 3, gate B12: scheduled 2026-11-10 08:40;" in text
    assert "now 2026-11-10 09:05, 25 min late" in text
    assert "Arrival BKK (Bangkok), terminal 1: scheduled" in text
    assert "checked 10 Nov 16:30" in text
    assert "it can change" in text
    _no_addresses(text)
    assert result.buttons == [
        [("Example Tracker ↗", f"{PREFIX}https://tracker.example.com/flight/XY123")]
    ]


async def test_flight_status_says_plainly_when_google_has_none_and_refuses_a_bad_number() -> None:
    source = Scripted()
    none = await _run("flight_status", source, flight="XY123", day="2026-11-30")
    assert "no status for XY123 on 2026-11-30" in none.text
    assert "2026-11-12" in none.text  # the days Google has
    assert none.buttons is None
    bad = await _run("flight_status", source, flight="tomorrow morning")
    assert bad.text.startswith("Error: ")
    assert len(source.asked) == 1


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("flight_prices", {"origin": "SIN", "destination": "BKK", "outbound_date": "2026-12-10"}),
        ("product_prices", {"query": "frobnicator"}),
        ("flight_status", {"flight": "SQ12"}),
    ],
)
async def test_a_used_up_month_tells_the_model_when_prices_are_back_and_to_use_web_search(
    name: str, args: dict[str, str]
) -> None:
    result = await _run(name, Scripted(SearchesPaused("month", date(2026, 12, 1))), **args)
    assert "paused until 1 Dec" in result.text
    assert "web_search" in result.text
    assert "Don't call this tool again" in result.text
    assert result.buttons is None


async def test_a_used_up_day_says_tomorrow() -> None:
    result = await _run(
        "product_prices", Scripted(SearchesPaused("day", date(2026, 11, 11))), query="frobnicator"
    )
    assert "until tomorrow" in result.text
    assert "web_search" in result.text


async def test_a_failed_search_is_reported_not_raised() -> None:
    result = await _run("product_prices", Scripted(WebSearchError("HTTP 503")), query="frobnicator")
    assert "couldn't be fetched" in result.text
    assert "503" not in result.text


async def test_without_a_key_the_tools_say_they_are_not_set_up() -> None:
    for name, args in (
        ("flight_prices", {"origin": "SIN", "destination": "BKK", "outbound_date": "2026-12-10"}),
        ("product_prices", {"query": "frobnicator"}),
        ("flight_status", {"flight": "SQ12"}),
    ):
        result = await _run(name, None, **args)
        assert "aren't set up" in result.text


def test_the_pause_message_names_what_was_paused() -> None:
    text = price_text.paused(SearchesPaused("month", date(2027, 1, 1)), what="flight status")
    assert "Live flight status are paused until 1 Jan" in text


def test_the_tools_and_their_arguments_are_what_the_model_is_told() -> None:
    tools = build_tools(lambda _: "")
    for name in ("flight_prices", "product_prices", "flight_status"):
        assert "web_search" in tools[name].description
        assert tools[name].confirm is None
        assert not safe_for_images(
            tools[name]
        )  # withheld on a turn about an image, like web_search
    props = tools["flight_prices"].schema()["function"]["parameters"]["properties"]
    assert {"origin", "destination", "outbound_date", "return_date", "adults", "cabin"} <= set(
        props
    )
    assert {"cheapest_from", "cheapest_to", "trip_days"} <= set(props)
    assert FlightPricesArgs.model_fields["adults"].default == 1
    assert FlightPricesArgs.model_fields["cabin"].default == "economy"
    json.dumps(tools["flight_prices"].schema())  # the schema is plain JSON
