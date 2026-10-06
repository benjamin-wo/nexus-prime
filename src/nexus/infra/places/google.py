"""Places from Google Maps, through the Places API (New).

``POST https://places.googleapis.com/v1/places:searchText`` finds places from a
phrase ("ramen in Shinjuku"), and ``GET https://places.googleapis.com/v1/places/{id}``
gives one place's hours and reviews. The key goes in a header, never the URL, and
each request asks only for the fields shown (Google bills by the fields asked for).
Everything that comes back is someone else's text: it's cleaned, links must be plain
http(s), and anything that doesn't parse is dropped.
"""

import logging
from datetime import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from nexus.application.places import PlacesError
from nexus.domain.places import (
    MAX_ADDRESS,
    MAX_NAME,
    MAX_REVIEW,
    MAX_REVIEWS,
    MAX_SUMMARY,
    Period,
    Place,
    PlacePhoto,
    Review,
    link,
    photo_name,
    place_id,
    quoted,
    text,
)

log = logging.getLogger(__name__)

BASE_URL = "https://places.googleapis.com/v1"
_BASIC = (
    "id,displayName,formattedAddress,primaryTypeDisplayName,rating,userRatingCount,"
    "priceLevel,googleMapsUri,businessStatus"
)
SEARCH_FIELDS = ",".join(f"places.{f}" for f in _BASIC.split(","))
DETAIL_FIELDS = (
    f"{_BASIC},websiteUri,internationalPhoneNumber,editorialSummary,regularOpeningHours,reviews,"
    "photos"
)
PHOTO_WIDTH = 400  # a thumbnail; Google bills per photo, not by size
MAX_PHOTO_BYTES = 2_000_000
_PRICES = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}
_STATUSES = {"OPERATIONAL", "CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"}


class GooglePlaces:
    def __init__(
        self,
        http: httpx.AsyncClient,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        language: str = "en",
    ) -> None:
        self._http = http
        self._key = api_key
        self._base_url = base_url.rstrip("/")
        self._language = language

    async def _call(self, method: str, path: str, fields: str, body: Any = None) -> Any:
        headers = {"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": fields}
        try:
            response = await self._http.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                json=body,
                params=None if body is not None else {"languageCode": self._language},
                timeout=20.0,
            )
        except httpx.HTTPError as exc:
            raise PlacesError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise PlacesError(f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise PlacesError("unexpected response") from exc

    async def search(self, query: str, *, limit: int) -> list[Place]:
        data = await self._call(
            "POST",
            "/places:searchText",
            SEARCH_FIELDS,
            {"textQuery": query, "pageSize": limit, "languageCode": self._language},
        )
        rows = data.get("places") if isinstance(data, dict) else None
        found = [p for row in (rows or []) if (p := parse_place(row)) is not None]
        return found[:limit]

    async def photo(self, name: str) -> tuple[bytes, str]:
        """A photo's bytes and type. Google answers with a short-lived link to the
        image, which is fetched without the key."""
        if photo_name(name) is None:
            raise PlacesError("not a photo name")
        try:
            response = await self._http.get(
                f"{self._base_url}/{name}/media",
                params={"maxWidthPx": str(PHOTO_WIDTH), "skipHttpRedirect": "true"},
                headers={"X-Goog-Api-Key": self._key},
                timeout=20.0,
            )
            uri = response.json().get("photoUri") if response.status_code == 200 else None
            if not isinstance(uri, str) or not uri.startswith("https://"):
                raise PlacesError(f"no photo link (HTTP {response.status_code})")
            image = await self._http.get(uri, timeout=20.0, follow_redirects=True)
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            raise PlacesError(f"photo request failed: {type(exc).__name__}") from exc
        mime = image.headers.get("content-type", "").split(";")[0].strip()
        if image.status_code != 200 or mime not in ("image/jpeg", "image/png", "image/webp"):
            raise PlacesError(f"photo answered {image.status_code} {mime}")
        if len(image.content) > MAX_PHOTO_BYTES:
            raise PlacesError("photo too large")
        return image.content, mime

    async def details(self, wanted: str) -> Place | None:
        pid = place_id(wanted)
        if pid is None:
            return None
        data = await self._call("GET", f"/places/{pid}", DETAIL_FIELDS)
        return parse_place(data, detailed=True)


def _localized(value: Any, limit: int) -> str | None:
    if isinstance(value, dict):
        value = value.get("text")
    return text(value, limit) if isinstance(value, str) else None


def _decimal(value: Any) -> Decimal | None:
    try:
        found = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return found.quantize(Decimal("0.1")) if found.is_finite() and 0 < found <= 5 else None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _point(value: Any) -> tuple[int, time] | None:
    if not isinstance(value, dict):
        return None
    day, hour, minute = value.get("day"), value.get("hour", 0), value.get("minute", 0)
    if not (isinstance(day, int) and isinstance(hour, int) and isinstance(minute, int)):
        return None
    if not (0 <= day <= 6 and 0 <= hour <= 24 and 0 <= minute < 60):
        return None
    return day, time(min(hour, 23), minute if hour < 24 else 59)


def _periods(hours: Any) -> tuple[Period, ...]:
    if not isinstance(hours, dict):
        return ()
    found = []
    for row in hours.get("periods") or []:
        if not isinstance(row, dict) or (opens := _point(row.get("open"))) is None:
            continue
        closes = _point(row.get("close"))
        found.append(
            Period(opens[0], opens[1], closes[0] if closes else None, closes[1] if closes else None)
        )
    return tuple(found[:28])


def _weekdays(hours: Any) -> tuple[str, ...]:
    if not isinstance(hours, dict):
        return ()
    rows = hours.get("weekdayDescriptions") or []
    return tuple(t for r in rows[:7] if (t := text(r, 80)))


def _review(row: Any) -> Review | None:
    if not isinstance(row, dict):
        return None
    words = quoted(_localized(row.get("text"), MAX_REVIEW), MAX_REVIEW)
    if not words:
        return None
    attribution = row.get("authorAttribution")
    author: dict[str, Any] = attribution if isinstance(attribution, dict) else {}
    rating = row.get("rating")
    return Review(
        rating=rating if isinstance(rating, int) and 1 <= rating <= 5 else None,
        text=words,
        author=quoted(author.get("displayName"), 60),
        author_url=link(author.get("uri")),
        when=text(row.get("relativePublishTimeDescription"), 40),
    )


def _photo(rows: Any) -> PlacePhoto | None:
    """The place's first photo, with its first author for the credit."""
    first = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    name = photo_name(first.get("name")) if first else None
    if first is None or name is None:
        return None
    authors = first.get("authorAttributions")
    author = (
        authors[0] if isinstance(authors, list) and authors and isinstance(authors[0], dict) else {}
    )
    return PlacePhoto(name, quoted(author.get("displayName"), 60), link(author.get("uri")))


def parse_place(row: Any, *, detailed: bool = False) -> Place | None:
    """A place from Google's JSON; None when it lacks an id or a name."""
    if not isinstance(row, dict):
        return None
    pid = place_id(row.get("id"))
    name = quoted(_localized(row.get("displayName"), MAX_NAME), MAX_NAME)
    if pid is None or name is None:
        return None
    status = row.get("businessStatus")
    hours = row.get("regularOpeningHours")
    reviews = [r for raw in (row.get("reviews") or []) if (r := _review(raw)) is not None]
    return Place(
        id=pid,
        name=name,
        address=quoted(row.get("formattedAddress"), MAX_ADDRESS),
        kind=quoted(_localized(row.get("primaryTypeDisplayName"), 60), 60),
        rating=_decimal(row.get("rating")),
        ratings=_count(row.get("userRatingCount")),
        price_level=_PRICES.get(str(row.get("priceLevel"))),
        maps_url=link(row.get("googleMapsUri")),
        website=link(row.get("websiteUri")),
        phone=text(row.get("internationalPhoneNumber"), 30),
        summary=quoted(_localized(row.get("editorialSummary"), MAX_SUMMARY), MAX_SUMMARY),
        status=status if status in _STATUSES else None,
        periods=_periods(hours),
        hours=_weekdays(hours),
        reviews=tuple(reviews[:MAX_REVIEWS]),
        photo=_photo(row.get("photos")) if detailed else None,
        detailed=detailed,
    )
