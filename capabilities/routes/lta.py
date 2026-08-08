"""LTA DataMall client for live Singapore bus arrivals and stop search.

Requires LTA_ACCOUNT_KEY. All calls are read-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from core.config import settings

LTA_BASE = "https://datamall.mytransport.sg/ltaodataservice/"
TIMEOUT_SECONDS = 15.0


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
    """Search LTA bus stops by name/road. Returns [{code, description, road_name, lat, lng}]."""
    data = await _lta_get(
        "BusStops",
        {"$skip": 0, "SearchText": search_text},
    )
    if not data:
        return []
    stops = []
    for stop in data.get("value", [])[:limit]:
        stops.append(
            {
                "code": str(stop.get("BusStopCode", "")),
                "description": stop.get("Description", ""),
                "road_name": stop.get("RoadName", ""),
                "lat": stop.get("Latitude"),
                "lng": stop.get("Longitude"),
            }
        )
    return stops


async def get_bus_arrivals(
    stop_code: str,
    service_no: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Live arrivals for a stop. Returns [{service, arrivals_min: [int|None, ...]}]."""
    params: dict[str, Any] = {"BusStopCode": stop_code}
    if service_no:
        params["ServiceNo"] = service_no
    data = await _lta_get("BusArrivalv2", params)
    if not data:
        return []
    now = datetime.now(timezone.utc)
    arrivals = []
    for item in data.get("value", []):
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
