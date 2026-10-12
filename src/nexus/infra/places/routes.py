"""Travel times from Google's Routes API.

``POST https://routes.googleapis.com/directions/v2:computeRoutes`` with two place ids
and a way of travelling, asking only for the duration and distance (Google bills by
the fields asked for; driving is asked without live traffic, the cheaper kind). The
key goes in a header, never the URL. Only the two place ids are sent.
"""

import re
from typing import Any

import httpx

from nexus.application.routes import Leg, RoutesError
from nexus.domain.places import place_id
from nexus.domain.routes import Mode

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELDS = "routes.duration,routes.distanceMeters"
_MODES = {Mode.WALK: "WALK", Mode.TRANSIT: "TRANSIT", Mode.DRIVE: "DRIVE"}
_SECONDS = re.compile(r"^(\d{1,7})(?:\.\d+)?s$")
# A day's hop is never this long; anything longer is an answer not worth showing.
MAX_SECONDS = 24 * 3600


class GoogleRoutes:
    def __init__(self, http: httpx.AsyncClient, api_key: str, *, url: str = URL) -> None:
        self._http = http
        self._key = api_key
        self._url = url

    async def route(self, origin: str, destination: str, mode: Mode) -> Leg | None:
        start, end = place_id(origin), place_id(destination)
        if start is None or end is None:
            raise RoutesError("not a place id")
        body: dict[str, Any] = {
            "origin": {"placeId": start},
            "destination": {"placeId": end},
            "travelMode": _MODES[mode],
            "languageCode": "en",
            "units": "METRIC",
        }
        if mode is Mode.DRIVE:
            body["routingPreference"] = "TRAFFIC_UNAWARE"
        try:
            response = await self._http.post(
                self._url,
                json=body,
                headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": FIELDS},
                timeout=15.0,
            )
        except httpx.HTTPError as exc:
            raise RoutesError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise RoutesError(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RoutesError("unexpected response") from exc
        return parse_leg(data)


def parse_leg(data: Any) -> Leg | None:
    """The first route's duration and distance; None when there's no route."""
    routes = data.get("routes") if isinstance(data, dict) else None
    first = routes[0] if isinstance(routes, list) and routes else None
    if not isinstance(first, dict):
        return None
    match = _SECONDS.match(str(first.get("duration") or ""))
    metres = first.get("distanceMeters", 0)
    if match is None or not isinstance(metres, int) or metres < 0:
        return None
    seconds = int(match.group(1))
    return Leg(seconds, metres) if seconds <= MAX_SECONDS else None
