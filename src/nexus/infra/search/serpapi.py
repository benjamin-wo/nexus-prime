"""Live prices from Google, through SerpApi (free tier: 250 searches a month).

``GET https://serpapi.com/search?engine=…``: ``google_flights`` and ``google_hotels`` for the
Travel researcher (``SerpApiTravel``), and for the chat's live prices (``SerpApiPrices``)
``google_flights``, ``google_flights_calendar`` (the cheapest days in a window),
``google_shopping`` (``gl=sg``) and ``google`` (its "Flight details" block, for a flight's
status). Every search goes through ``SerpApiClient``, which counts it against the monthly
budget first (``application.serp_budget``) and makes none once the budget is used up.

SerpApi takes its key only as a query parameter, so request URLs are never logged (httpx
logs at WARNING) and errors name only the exception type. Each search links to the Google
page with the live prices; nothing is booked.
"""

import logging
import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from nexus.application.serp_budget import Budget, Spend
from nexus.application.travel_research import FlightQuote, HotelQuote, HotelSearch
from nexus.application.web_search import WebSearchError
from nexus.domain.live_prices import (
    OFFERS_SHOWN,
    TRAVEL_CLASS,
    CalendarQuery,
    FareCalendar,
    FareDay,
    FlightFares,
    FlightOption,
    FlightQuery,
    FlightStatus,
    PriceInsight,
    ProductOffer,
    ProductPrices,
    ProductQuery,
    StatusLeg,
    StatusQuery,
    cheapest_options,
    currency_of,
)
from nexus.domain.news import clean_text
from nexus.domain.travel_research import safe_url

log = logging.getLogger(__name__)

URL = "https://serpapi.com/search"
MAX_HOTELS = 8
# A product priced under this share of the median is most likely an accessory or a part.
ACCESSORY_SHARE = Decimal("0.4")
MIN_FOR_MEDIAN = 5


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        found = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return found if found.is_finite() and found > 0 else None


_ADDRESS = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)


def _text(value: Any, limit: int) -> str | None:
    """Someone else's text on one line, with any web address taken out: what the model is
    told never carries one (the links are buttons)."""
    if not isinstance(value, str | int | float):
        return None
    found = clean_text(_ADDRESS.sub(" ", str(value)), limit)
    return found or None


def _rows(value: Any) -> list[dict[str, Any]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _page(data: dict[str, Any], name: str) -> str | None:
    """A page SerpApi says the search is on, if it is a public https address."""
    return safe_url(_dict(data.get("search_metadata")).get(name))


class SerpApiClient:
    """One search: the budget first, then the request. The key is in the query string and
    goes nowhere else."""

    def __init__(self, http: httpx.AsyncClient, api_key: str, budget: Budget) -> None:
        self._http = http
        self._key = api_key
        self._budget = budget

    async def get(self, params: dict[str, str], spend: Spend) -> dict[str, Any]:
        await self._budget.reserve(spend)
        try:
            response = await self._http.get(
                URL, params={**params, "hl": "en", "api_key": self._key}, timeout=40.0
            )
        except httpx.HTTPError as exc:
            raise WebSearchError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise WebSearchError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise WebSearchError("unexpected response") from exc
        if not isinstance(data, dict) or data.get("error"):
            raise WebSearchError("no results")
        return data


# --- the Travel researcher's prices --------------------------------------------------


class SerpApiTravel:
    def __init__(self, client: SerpApiClient) -> None:
        self._client = client

    async def _get(self, params: dict[str, str]) -> dict[str, Any]:
        # For no one in particular: counted against the month, not a user's day.
        return await self._client.get(params, Spend())

    async def flights(
        self, origin: str, destination: str, outbound: date, back: date, currency: str, adults: int
    ) -> FlightQuote | None:
        data = await self._get(
            {
                "engine": "google_flights",
                "departure_id": origin,
                "arrival_id": destination,
                "outbound_date": outbound.isoformat(),
                "return_date": back.isoformat(),
                "currency": currency,
                "adults": str(adults),
                "type": "1",  # return
            }
        )
        insights = data.get("price_insights") or {}
        prices = [
            p
            for f in [*(data.get("best_flights") or []), *(data.get("other_flights") or [])]
            if isinstance(f, dict) and (p := _decimal(f.get("price"))) is not None
        ]
        typical = insights.get("typical_price_range") or []
        low = _decimal(insights.get("lowest_price")) or (min(prices) if prices else None)
        if low is None:
            return None
        high = _decimal(typical[1]) if len(typical) == 2 else (max(prices) if prices else low)
        url = (data.get("search_metadata") or {}).get("google_flights_url")
        # Prices are for all the adults together: per person for the estimate.
        n = Decimal(max(adults, 1))
        return FlightQuote(
            low / n, (high or low) / n, currency, url if isinstance(url, str) else None
        )

    async def hotels(
        self, query: str, check_in: date, check_out: date, currency: str, adults: int
    ) -> HotelSearch | None:
        data = await self._get(
            {
                "engine": "google_hotels",
                "q": query,
                "check_in_date": check_in.isoformat(),
                "check_out_date": check_out.isoformat(),
                "currency": currency,
                "adults": str(min(adults, 2)),  # one room
            }
        )
        rates: list[HotelQuote] = []
        for prop in data.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            nightly = _decimal((prop.get("rate_per_night") or {}).get("extracted_lowest"))
            if nightly is not None and isinstance(prop.get("name"), str):
                rates.append(HotelQuote(prop["name"][:80], nightly, currency))
            if len(rates) >= MAX_HOTELS:
                break
        if not rates:
            return None
        url = (data.get("search_metadata") or {}).get("google_hotels_url")
        return HotelSearch(rates, url if isinstance(url, str) else None)


# --- the chat's live prices: what is asked of each engine ------------------------------


def flights_params(q: FlightQuery) -> dict[str, str]:
    """Google Flights, round trip (``type`` 1, with a ``return_date``) or one way (2)."""
    params = {
        "engine": "google_flights",
        "departure_id": q.origin,
        "arrival_id": q.destination,
        "outbound_date": q.outbound.isoformat(),
        "type": "1" if q.back else "2",
        "currency": q.currency,
        "adults": str(q.adults),
        "travel_class": TRAVEL_CLASS[q.cabin],
    }
    if q.back:
        params["return_date"] = q.back.isoformat()
    return params


def calendar_params(q: CalendarQuery) -> dict[str, str]:
    """Google Flights Calendar: a price for each day in the window (a return trip of
    ``round_trip_days`` leaving that day, or one way)."""
    params = {
        "engine": "google_flights_calendar",
        "departure_id": q.origin,
        "arrival_id": q.destination,
        "type": "1" if q.trip_days else "2",
        "date_range_start": q.start.isoformat(),
        "date_range_end": q.end.isoformat(),
        "currency": q.currency,
        "adults": str(q.adults),
        "travel_class": TRAVEL_CLASS[q.cabin],
    }
    if q.trip_days:
        params["round_trip_days"] = str(q.trip_days)
    return params


def shopping_params(q: ProductQuery) -> dict[str, str]:
    """Google Shopping as seen from Singapore."""
    return {"engine": "google_shopping", "q": q.query, "gl": "sg"}


def status_params(q: StatusQuery) -> dict[str, str]:
    """A plain Google search for the flight: for a flight number Google shows a "Flight
    details" block, which SerpApi returns as ``flight_result``."""
    return {"engine": "google", "q": f"{q.flight} flight status"}


# --- ... and how the answers are read ------------------------------------------------------


def _local(raw: Any) -> str | None:
    """A time as the airport's clock reads it, "2026-12-10 08:25", from SerpApi's
    "2026-12-10 08:25" or "2026-04-27T12:25:00.000+02:00"."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.strip()).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _option(item: dict[str, Any]) -> FlightOption | None:
    price = _decimal(item.get("price"))
    legs = _rows(item.get("flights"))
    if price is None or not legs:
        return None
    airlines = list(dict.fromkeys(a for leg in legs if (a := _text(leg.get("airline"), 40))))
    minutes = item.get("total_duration")
    if not isinstance(minutes, int):
        parts = [leg.get("duration") for leg in legs]
        minutes = sum(p for p in parts if isinstance(p, int)) or None
    via = [
        v
        for lay in _rows(item.get("layovers"))
        if (v := _text(lay.get("id") or lay.get("name"), 40))
    ]
    first = _dict(legs[0].get("departure_airport"))
    last = _dict(legs[-1].get("arrival_airport"))
    return FlightOption(
        airline=", ".join(airlines) or "?",
        stops=len(legs) - 1,
        via=via,
        minutes=minutes,
        price=price,
        departs=_local(first.get("time")),
        arrives=_local(last.get("time")),
        flights=[n for leg in legs if (n := _text(leg.get("flight_number"), 12))],
    )


def parse_flights(data: dict[str, Any], query: FlightQuery, now: datetime) -> FlightFares:
    options = [
        o
        for item in [*_rows(data.get("best_flights")), *_rows(data.get("other_flights"))]
        if (o := _option(item)) is not None
    ]
    raw = _dict(data.get("price_insights"))
    typical = raw.get("typical_price_range")
    spread = typical if isinstance(typical, list) and len(typical) == 2 else [None, None]
    level = raw.get("price_level")
    insight = PriceInsight(
        level=level.strip().lower() if isinstance(level, str) and level.strip() else None,
        lowest=_decimal(raw.get("lowest_price")),
        typical_low=_decimal(spread[0]),
        typical_high=_decimal(spread[1]),
    )
    has_insight = any((insight.level, insight.lowest, insight.typical_low, insight.typical_high))
    return FlightFares(
        query=query,
        options=cheapest_options(options),
        insight=insight if has_insight else None,
        url=_page(data, "google_flights_url"),
        checked_at=now,
    )


def _day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def parse_calendar(data: dict[str, Any], query: CalendarQuery, now: datetime) -> FareCalendar:
    days: list[FareDay] = []
    for item in _rows(data.get("prices")):
        outbound, price = _day(item.get("outbound_date")), _decimal(item.get("price"))
        if outbound is None or price is None:
            continue
        days.append(
            FareDay(outbound, _day(item.get("return_date")), price, item.get("low_price") is True)
        )
    days.sort(key=lambda d: d.outbound)
    return FareCalendar(query, days, now)


def _offer(item: dict[str, Any]) -> ProductOffer | None:
    title = _text(item.get("title"), 120)
    shown = _text(item.get("price"), 30)
    price = _decimal(item.get("extracted_price"))
    if price is None and shown:
        price = _decimal("".join(c for c in shown if c.isdigit() or c == "."))
    if title is None or price is None:
        return None
    rating = item.get("rating")
    return ProductOffer(
        title=title,
        price=price,
        price_text=shown or f"{price}",
        currency=currency_of(shown) if shown else None,
        store=_text(item.get("source"), 40),
        rating=float(rating) if isinstance(rating, int | float) and 0 < rating <= 5 else None,
        link=safe_url(item.get("link")) or safe_url(item.get("product_link")),
    )


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def parse_shopping(data: dict[str, Any], query: ProductQuery, now: datetime) -> ProductPrices:
    """Offers from every list of results on the page, the same one only once, the very cheap
    ones left out (an accessory costs a fraction of the product), cheapest first."""
    items = [*_rows(data.get("shopping_results")), *_rows(data.get("inline_shopping_results"))]
    for group in _rows(data.get("categorized_shopping_results")):
        items.extend(_rows(group.get("shopping_results")))
    offers: dict[tuple[str, str | None, Decimal], ProductOffer] = {}
    for item in items:
        offer = _offer(item)
        if offer is not None:
            offers.setdefault((offer.title.casefold(), offer.store, offer.price), offer)
    found = list(offers.values())
    if len(found) >= MIN_FOR_MEDIAN:
        floor = _median([o.price for o in found]) * ACCESSORY_SHARE
        found = [o for o in found if o.price >= floor]
    found.sort(key=lambda o: o.price)
    return ProductPrices(
        query=query,
        offers=found[:OFFERS_SHOWN],
        url=_page(data, "google_shopping_url"),
        checked_at=now,
    )


def _humanise(code: Any) -> str | None:
    """ "ARRIVED_DELAYED" as "arrived delayed"; Google's own label is used when it has one."""
    if not isinstance(code, str) or not code.strip():
        return None
    return code.strip().replace("_STATUS", "").replace("_", " ").lower()


def _gate(value: Any) -> str | None:
    return _text(value, 12) if value not in ("-", "") else None


def _leg(raw: Any) -> StatusLeg | None:
    leg = _dict(raw)
    if not leg:
        return None
    return StatusLeg(
        airport=_text(leg.get("id"), 8),
        city=_text(leg.get("city"), 40),
        scheduled=_local(leg.get("scheduled_time")),
        estimated=_local(leg.get("time")),
        terminal=_gate(leg.get("terminal")),
        gate=_gate(leg.get("gate")),
        state=_text(leg.get("status"), 30),
    )


def _minutes(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_status(
    data: dict[str, Any], query: StatusQuery, today: date, now: datetime
) -> FlightStatus:
    """The "Flight details" block Google shows for a flight number (``flight_result``): a
    status for each of a few days, the detail (times, gate, terminal) for the days it has
    it. The day asked for, else today, else the next one it has."""
    block = _dict(data.get("flight_result"))
    entries = [e for e in _rows(block.get("dates")) if _day(e.get("date")) is not None]
    if not entries:
        return FlightStatus(query, found=False, checked_at=now)
    days = [str(e["date"]) for e in entries]
    wanted = (query.day or today).isoformat()
    entry = next((e for e in entries if e["date"] == wanted), None)
    if entry is None and query.day is None:
        entry = next((e for e in entries if str(e["date"]) >= wanted), None)
    if entry is None:
        return FlightStatus(query, found=False, other_days=days[:7], checked_at=now)
    meta = _dict(entry.get("metadata"))
    route = _text(block.get("route"), 80)
    return FlightStatus(
        query=query,
        found=True,
        day=_day(entry["date"]),
        status=_text(entry.get("status"), 40) or _humanise(meta.get("status")),
        airline=_text(block.get("airline"), 40),
        route=route,
        departure=_leg(entry.get("departure_airport")),
        arrival=_leg(entry.get("arrival_airport")),
        departure_delay=_minutes(meta.get("departure_delay")),
        arrival_delay=_minutes(meta.get("arrival_delay")),
        updated=_local(entry.get("updated_at")),
        source=_text(entry.get("source"), 30),
        source_url=safe_url(entry.get("source_url")),
        other_days=days[:7],
        checked_at=now,
    )


class SerpApiPrices:
    """The chat's live prices, each search made for a user (counted on their day too)."""

    def __init__(self, client: SerpApiClient, now: Callable[[], datetime]) -> None:
        self._client = client
        self._now = now

    async def flights(self, q: FlightQuery, spend: Spend) -> FlightFares:
        data = await self._client.get(flights_params(q), spend)
        return parse_flights(data, q, self._now())

    async def calendar(self, q: CalendarQuery, spend: Spend) -> FareCalendar:
        data = await self._client.get(calendar_params(q), spend)
        return parse_calendar(data, q, self._now())

    async def products(self, q: ProductQuery, spend: Spend) -> ProductPrices:
        data = await self._client.get(shopping_params(q), spend)
        return parse_shopping(data, q, self._now())

    async def status(self, q: StatusQuery, spend: Spend) -> FlightStatus:
        data = await self._client.get(status_params(q), spend)
        today = spend.day or self._now().date()
        return parse_status(data, q, today, self._now())
