"""Transit journey composer: Google Maps Directions + LTA live arrivals.

This is the two-tool orchestration recipe behind route answers:
1. Google Maps Directions (transit mode) gives the journey: lines, stops,
   walking legs, total time, and a map link.
2. LTA DataMall gives live next-departure minutes for each bus line at the
   departure stop found by Maps, so the answer is "Bus 27: next 4 min" rather
   than a static schedule.
Neither tool's data is fabricated; when live data is unavailable, the step is
shown with the scheduled departure time (or no time) instead.
"""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from capabilities.routes import lta
from core.config import settings

DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
MAPS_LINK = "https://www.google.com/maps/dir/?api=1&travelmode=transit&origin={origin}&destination={destination}"


async def _directions(origin: str, destination: str) -> dict[str, Any]:
    if not settings.google_maps_api_key or settings.google_maps_api_key.startswith("your_"):
        return {"error": "route_provider_not_configured"}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                DIRECTIONS_URL,
                params={
                    "origin": origin,
                    "destination": destination,
                    "mode": "transit",
                    "key": settings.google_maps_api_key,
                    # Regression: this was hard-coded to "false", so a user
                    # asking for "other bus"/"a different route" always got
                    # back the exact same single journey -- there was no
                    # second option to even offer. plan_transit_journey()
                    # now picks among data["routes"] via route_index.
                    "alternatives": "true",
                },
            )
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"maps_unavailable: {exc}"}
    if data.get("status") != "OK" or not data.get("routes"):
        return {"error": data.get("error_message") or data.get("status") or "unknown"}
    return data


def _sgt_time(epoch_seconds: Optional[int]) -> Optional[str]:
    if not epoch_seconds:
        return None
    try:
        return datetime.fromtimestamp(
            int(epoch_seconds), ZoneInfo("Asia/Singapore")
        ).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return None


async def _live_minutes_for_stop(
    stop_name: str,
    line: str,
) -> Optional[int]:
    """LTA live arrival minutes for a line at a Maps-named stop, if resolvable."""
    if not settings.lta_account_key or settings.lta_account_key.startswith("your_"):
        return None
    catalog = await lta.ensure_stop_catalog()
    if not catalog:
        return None
    matches = lta.fuzzy_search_stops(catalog, stop_name, limit=1, min_fraction=0.5)
    if not matches:
        return None
    arrivals = await lta.get_bus_arrivals(matches[0]["code"], line)
    if not arrivals:
        return None
    minutes = arrivals[0]["arrivals_min"]
    return minutes[0] if minutes else None


async def plan_transit_journey(
    origin: str, destination: str, route_index: int = 0
) -> dict[str, Any]:
    """Full journey: ordered steps, total time, live departures, map link.

    route_index selects among Google's alternative routes (0 = the default
    best route). If route_index is out of range -- the caller asked for
    "another one" but Maps didn't offer one -- this returns
    {"error": "no_alternative_available", "route_count": N} rather than
    silently re-returning route 0, so the caller can be honest about it
    instead of looking like it ignored the request.
    """
    data = await _directions(origin, destination)
    if data.get("error"):
        return data
    routes = data["routes"]
    if route_index >= len(routes):
        return {"error": "no_alternative_available", "route_count": len(routes)}
    leg = routes[route_index]["legs"][0]
    steps: list[dict[str, Any]] = []
    for step in leg.get("steps", []):
        transit = step.get("transit_details") or {}
        line_info = transit.get("line") or {}
        line = str(line_info.get("short_name") or line_info.get("name") or "")
        departure_stop = (transit.get("departure_stop") or {}).get("name", "")
        arrival_stop = (transit.get("arrival_stop") or {}).get("name", "")
        duration_text = (step.get("duration") or {}).get("text", "")
        if line:
            live_minutes = await _live_minutes_for_stop(departure_stop, line)
            scheduled = _sgt_time(
                (transit.get("departure_time") or {}).get("value")
            )
            steps.append(
                {
                    "kind": "transit",
                    "line": line,
                    "departure_stop": departure_stop,
                    "arrival_stop": arrival_stop,
                    "duration_text": duration_text,
                    "live_minutes": live_minutes,
                    "scheduled_time": scheduled,
                }
            )
        else:
            text = (
                (step.get("html_instructions") or "")
                .replace("<b>", "")
                .replace("</b>", "")
                .replace("<div", "; <div")
                .replace("</div>", "")
            )
            text = re.sub(r"<[^>]+>", "", text).strip()
            steps.append(
                {
                    "kind": "walk",
                    "text": text or "Walk",
                    "duration_text": duration_text,
                }
            )

    return {
        "origin": origin,
        "destination": destination,
        "total": leg.get("duration", {}).get("text", ""),
        "distance": leg.get("distance", {}).get("text", ""),
        "steps": steps,
        "map_url": MAPS_LINK.format(
            origin=quote(origin), destination=quote(destination)
        ),
        "route_index": route_index,
        "route_count": len(routes),
    }


def format_journey(journey: dict[str, Any]) -> str:
    lines = [
        f"🚇 *{journey['origin']}* → *{journey['destination']}* "
        f"(~{journey['total']})"
    ]
    for idx, step in enumerate(journey["steps"], 1):
        if step["kind"] == "transit":
            timing = ""
            if step.get("live_minutes") is not None:
                minutes = step["live_minutes"]
                timing = (
                    "due"
                    if minutes == 0
                    else f"next in ~{minutes} min"
                )
            elif step.get("scheduled_time"):
                timing = f"departs {step['scheduled_time']}"
            suffix = f" · {timing}" if timing else ""
            lines.append(
                f"{idx}. {step['line']}: {step['departure_stop']} → "
                f"{step['arrival_stop']} ({step['duration_text']}){suffix}"
            )
        else:
            lines.append(
                f"{idx}. 🚶 {step['text']} ({step['duration_text']})"
            )
    lines.append(f"🗺️ Open in Maps: {journey['map_url']}")
    return "\n".join(lines)
