"""LTA DataMall client for live Singapore bus arrivals and stop search.

Requires LTA_ACCOUNT_KEY. All calls are read-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Optional

import httpx

from core.config import settings

LTA_BASE = "https://datamall2.mytransport.sg/ltaodataservice/"
TIMEOUT_SECONDS = 15.0

last_search_error: Optional[str] = None
_catalog_loaded: Optional[bool] = None


async def _lta_get(endpoint: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
    api_key = settings.lta_account_key
    if not api_key or api_key.startswith("your_"):
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.get(
                LTA_BASE + endpoint,
                params=params,
                headers={"AccountKey": api_key},
            )
        if resp.status_code != 200:
            print(f"[LTA] {endpoint} status {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[LTA] {endpoint} error: {exc}")
        return None


async def search_bus_stops(search_text: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search bus stops via the local catalog, fuzzy-matched against the query.

    Regression (#57): this used to try a "live SearchText" call against LTA's
    BusStops endpoint first. That endpoint has no free-text search parameter
    of its own -- per LTA's own API docs it supports only $skip/$top
    pagination -- so passing SearchText was silently ignored and the call
    returned an arbitrary, unfiltered page of the full catalog (in practice,
    always the same handful of stops from the very start of the listing).
    Because that page was non-empty, it was trusted as the "match" and
    returned directly, so a query like "fullerton sq hotel" got back
    completely unrelated stops from Victoria St -- confidently wrong instead
    of a real match. fuzzy_search_stops() against the real local catalog
    finds the correct stop; this never had a live-search advantage to give up.
    """
    global last_search_error
    last_search_error = None
    catalog = await ensure_stop_catalog()
    if catalog is None:
        last_search_error = "unreachable"
        return []
    return fuzzy_search_stops(catalog, search_text, limit)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def fuzzy_search_stops(
    stops: list[dict[str, Any]],
    query: str,
    limit: int = 5,
    min_fraction: float = 0.0,
) -> list[dict[str, Any]]:
    """Token-overlap fuzzy search over a stop catalog (works offline)."""
    query_tokens = set(_normalize(query).split())
    if not query_tokens:
        return []
    scored = []
    for stop in stops:
        haystack = _normalize(
            f"{stop.get('description', '')} {stop.get('road_name', '')}"
        )
        hay_tokens = haystack.split()
        hits = sum(
            1
            for token in query_tokens
            if token in hay_tokens or any(token in word for word in hay_tokens)
        )
        fraction = hits / len(query_tokens)
        if hits and fraction >= min_fraction:
            scored.append((fraction, hits, stop))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].get("code", "")))
    return [item[2] for item in scored[:limit]]


async def ensure_stop_catalog() -> Optional[list[dict[str, Any]]]:
    """Fetch the full LTA bus-stop catalog into the DB once; return cached rows."""
    global _catalog_loaded
    from sqlmodel import select

    from core.db import async_session_factory
    from core.models import BusStop

    async with async_session_factory() as session:
        exists = (await session.execute(select(BusStop).limit(1))).scalar_one_or_none()
        if exists is not None:
            _catalog_loaded = True
            rows = (await session.execute(select(BusStop))).scalars().all()
            return [
                {
                    "code": row.code,
                    "description": row.description,
                    "road_name": row.road_name,
                    "lat": row.lat,
                    "lng": row.lng,
                }
                for row in rows
            ]

    stops: list[dict[str, Any]] = []
    skip = 0
    page_size = 500
    while skip < 7000:
        data = await _lta_get("BusStops", {"$skip": skip, "$top": page_size})
        if data is None:
            _catalog_loaded = False
            return None
        page = data.get("value", [])
        stops.extend(
            {
                "code": str(stop.get("BusStopCode", "")),
                "description": stop.get("Description", ""),
                "road_name": stop.get("RoadName", ""),
                "lat": stop.get("Latitude"),
                "lng": stop.get("Longitude"),
            }
            for stop in page
        )
        if len(page) < page_size:
            break
        skip += page_size

    async with async_session_factory() as session:
        for stop in stops:
            session.add(BusStop(**stop))
        await session.commit()
    _catalog_loaded = True
    return stops


async def get_bus_arrivals(
    stop_code: str,
    service_no: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Live arrivals for a stop. Returns [{service, arrivals_min: [int|None, ...]}]."""
    params: dict[str, Any] = {"BusStopCode": stop_code}
    if service_no:
        params["ServiceNo"] = service_no
    data = await _lta_get("v3/BusArrival", params)
    if not data:
        return []
    now = datetime.now(timezone.utc)
    arrivals = []
    for item in data.get("Services") or data.get("value") or []:
        minutes = []
        for key in ("NextBus", "NextBus2", "NextBus3"):
            bus = item.get(key) or {}
            eta = bus.get("EstimatedArrival") or ""
            try:
                eta_dt = datetime.fromisoformat(eta.replace("Z", "+00:00"))
                mins = int((eta_dt - now).total_seconds() // 60)
                minutes.append(max(0, mins))
            except Exception:  # noqa: BLE001
                minutes.append(None)
        arrivals.append(
            {
                "service": str(item.get("ServiceNo", "")),
                "destination_code": item.get("DestinationCode", ""),
                "arrivals_min": minutes,
            }
        )
    return arrivals


def format_arrivals(arrivals: list[dict[str, Any]]) -> str:
    if not arrivals:
        return "No live arrivals returned for that stop."
    lines = []
    for item in arrivals:
        service = item["service"]
        slots = []
        for minutes in item["arrivals_min"]:
            if minutes is None:
                continue
            slots.append("due" if minutes == 0 else f"{minutes} min")
        if not slots:
            slots = ["no estimate"]
        lines.append(
            f"Bus {service}: next {slots[0]}"
            + (f", then {slots[1]}" if len(slots) > 1 else "")
        )
    return "\n".join(lines)
