import json
import re
from typing import Dict, Any, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from core.config import settings
from core.llm import ThinkingLevel, get_agent_llm
from capabilities.routes import lta


@tool
async def plan_route(origin: str, destination: str, mode: str = "transit") -> Dict[str, Any]:
    """
    Plan a route between origin and destination via the Google Maps Directions API.
    Mode can be transit, driving, walking, or bicycling.
    """
    mode = mode.lower() if mode.lower() in ("transit", "driving", "walking", "bicycling") else "transit"

    # No API key configured: honest error, no fabricated ETA or bus number.
    if not settings.google_maps_api_key or settings.google_maps_api_key.startswith("your_"):
        return {
            "error": "route_provider_not_configured",
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "summary": "Live routing is not configured (GOOGLE_MAPS_API_KEY missing); "
            "no ETA or bus number was fabricated.",
            "steps": [],
        }

    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": settings.google_maps_api_key,
        "alternatives": "false",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params=params,
            )
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[ROUTES] maps api error: {exc}")
        return {"error": "maps_unavailable", "origin": origin, "destination": destination, "mode": mode}

    if data.get("status") != "OK" or not data.get("routes"):
        detail = data.get("error_message") or data.get("status") or "unknown"
        print(f"[ROUTES] maps status: {detail}")
        return {"error": detail, "origin": origin, "destination": destination, "mode": mode}

    leg = data["routes"][0]["legs"][0]
    steps = []
    for step in leg.get("steps", []):
        text = re.sub("<[^>]+>", "", step.get("html_instructions", "")).strip()
        transit = step.get("transit_details") or {}
        line = transit.get("line") or {}
        line_name = line.get("short_name") or line.get("name") or ""
        if line_name:
            departure = (transit.get("departure_stop") or {}).get("name", "")
            arrival = (transit.get("arrival_stop") or {}).get("name", "")
            duration = (step.get("duration") or {}).get("text", "")
            text = f"Take {line_name} from {departure} to {arrival}"
            if duration:
                text += f" ({duration})"
        if text:
            steps.append(text)

    eta_minutes = round(leg["duration"]["value"] / 60)
    distance_km = round(leg["distance"]["value"] / 1000, 1)
    return {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "eta_minutes": eta_minutes,
        "distance_km": distance_km,
        "summary": f"Route from {origin} to {destination} via {mode}: ~{eta_minutes} mins ({distance_km} km).",
        "steps": steps[:8],
    }


@tool
async def extract_route_request(user_text: str) -> Dict[str, Any]:
    """
    Extract origin, destination, and travel mode from a natural-language route request.
    Returns {"origin", "destination", "mode"} where mode is one of
    transit/driving/walking/bicycling.
    """
    def _regex_route(text: str) -> Dict[str, Any]:
        mode = "transit"
        lowered = text.lower()
        if "driving" in lowered or "drive" in lowered or "car" in lowered:
            mode = "driving"
        elif "walking" in lowered or "walk" in lowered:
            mode = "walking"
        elif "bicycling" in lowered or "cycle" in lowered or "bike" in lowered:
            mode = "bicycling"

        m = re.search(r"from\s+([A-Za-z0-9\s&'-]+?)\s+to\s+([A-Za-z0-9\s&'-]+?)(?:\s+by|\s+tomorrow|\s*$)", text, re.IGNORECASE)
        if m:
            return {"origin": m.group(1).strip(), "destination": m.group(2).strip(), "mode": mode}
        to_m = re.search(r"to\s+([A-Za-z0-9\s&'-]+?)(?:\s+by|\s+from|\s*$)", text, re.IGNORECASE)
        if to_m:
            return {"origin": None, "destination": to_m.group(1).strip(), "mode": mode}
        return {"origin": None, "destination": None, "mode": mode}

    if not settings.has_llm_key:
        return _regex_route(user_text)

    try:
        llm = get_agent_llm(complexity=ThinkingLevel.LOW, temperature=0.1)
        ai_message = await llm.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Extract a route request from the user's text. Reply with ONLY a JSON object "
                        '{"origin": string, "destination": string, "mode": "transit"|"driving"|"walking"|"bicycling"}. '
                        "If a place is missing, use null for that field. Default mode: transit."
                    )
                ),
                HumanMessage(content=user_text),
            ]
        )
        raw = str(getattr(ai_message, "content", "") or "").strip()
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        return {
            "origin": parsed.get("origin"),
            "destination": parsed.get("destination"),
            "mode": parsed.get("mode") or "transit",
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[ROUTES] extraction failed: {exc}, using fallback")
        return _regex_route(user_text)


def _bus_query_parts(last_text: str) -> Dict[str, Any]:
    """Extract stop code / stop name / service number from a bus query."""
    lowered = last_text.lower()
    service = None
    service_match = re.search(r"\bbus\s+(\d+[a-z]?)\b", lowered)
    if service_match:
        service = service_match.group(1)
    stop_code = None
    code_match = re.search(r"\b(\d{5})\b", last_text)
    if code_match:
        stop_code = code_match.group(1)
    stop_name = None
    name_match = re.search(
        r"(?:at|from|near)\s+([a-z0-9 ,'-]+?)(?=\s*(?:bus|\d{5}|please|for|$))",
        lowered,
    )
    if name_match and not stop_code:
        stop_name = re.sub(r"\s+", " ", name_match.group(1)).strip(" ,'-")
    if not stop_name and not stop_code:
        # No preposition: take whatever follows the bus mention, e.g. "next bus tampines west cc".
        bus_match = re.search(r"\bbus\b", lowered)
        trailing = (
            lowered[bus_match.end():].strip(" ,'-")
            if bus_match
            else ""
        )
        if (
            trailing
            and any(ch.isalnum() for ch in trailing)
            and trailing not in ("please", "today", "now", "soon")
        ):
            stop_name = trailing or None
    return {
        "service": service,
        "stop_code": stop_code,
        "stop_name": stop_name or None,
    }


def is_bus_arrival_query(last_text: str) -> bool:
    """True when the message asks for bus times AT a stop, not for directions.

    A destination ("to <place>") means the user wants a journey, so it must go
    through the Maps+LTA journey path instead of the arrival handler.
    """
    lowered = last_text.lower()
    if "bus" not in lowered:
        return False
    if re.search(r"\bto\s+[a-z0-9]", lowered):
        return False
    return any(
        marker in lowered
        for marker in ("next", "arriv", "when", " at ", " from ", "bus stop", "stop code")
    )


def is_bare_place_fragment(text: str) -> bool:
    """A short place-name-only message (e.g. 'tembusu grand')."""
    value = text.strip()
    lowered = value.lower()
    if not 2 <= len(value) <= 40 or any(ch.isdigit() for ch in value):
        return False
    if not re.fullmatch(r"[a-z0-9 ,'\-\.]+", lowered):
        return False
    if re.search(
        r"\b(please|me|my|the|what|when|how|which|route|bus|remind|expense|"
        r"email|grocery|recipe|bill|to|from|at|near|next|arriv)\b",
        lowered,
    ):
        return False
    return True


def _selection_intent(text: str) -> Optional[int]:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    mapping = {
        "the first one": 0, "first": 0, "1": 0, "1st": 0, "option 1": 0,
        "the second one": 1, "second": 1, "2": 1, "2nd": 1, "option 2": 1,
        "the third one": 2, "third": 2, "3": 2, "3rd": 2, "option 3": 2,
    }
    return mapping.get(normalized)


async def handle_bus_query(
    last_text: str,
    pending_stops: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Live bus arrivals via LTA DataMall. Never fabricates a bus number."""
    parts = _bus_query_parts(last_text)
    if not settings.lta_account_key or settings.lta_account_key.startswith("your_"):
        return {
            "kind": "no_live_feed",
            "message": (
                "I don't have a live bus feed configured (LTA_ACCOUNT_KEY missing), "
                "so I won't guess a bus number. Set LTA_ACCOUNT_KEY and I can tell "
                "you the actual next bus."
            ),
        }

    selection = _selection_intent(last_text)
    if selection is not None and pending_stops:
        stop = pending_stops[selection]
        arrivals = await lta.get_bus_arrivals(stop["code"], parts["service"])
        if not arrivals:
            return {"kind": "no_arrivals", "message": "No live arrivals returned for that stop."}
        return {
            "kind": "arrivals",
            "message": (
                f"{stop['description']} ({stop['code']}, {stop['road_name']}):\n"
                + lta.format_arrivals(arrivals)
            ),
        }

    if parts["stop_code"]:
        arrivals = await lta.get_bus_arrivals(parts["stop_code"], parts["service"])
        if not arrivals:
            return {"kind": "no_arrivals", "message": "No live arrivals returned for that stop."}
        return {"kind": "arrivals", "message": lta.format_arrivals(arrivals)}

    if parts["stop_name"]:
        stops = await lta.search_bus_stops(parts["stop_name"])
        if not stops:
            if lta.last_search_error == "unreachable":
                return {
                    "kind": "feed_unreachable",
                    "message": "I couldn't reach the live bus-stop feed right now — try again in a minute.",
                }
            return {
                "kind": "stop_not_found",
                "message": f"I couldn't find a bus stop matching {parts['stop_name']!r}.",
            }
        if len(stops) == 1:
            stop = stops[0]
            arrivals = await lta.get_bus_arrivals(stop["code"], parts["service"])
            if not arrivals:
                return {"kind": "no_arrivals", "message": "No live arrivals returned for that stop."}
            return {
                "kind": "arrivals",
                "message": (
                    f"{stop['description']} ({stop['code']}, {stop['road_name']}):\n"
                    + lta.format_arrivals(arrivals)
                ),
            }
        options = "\n".join(
            f"- {stop['description']} ({stop['code']}, {stop['road_name']})"
            for stop in stops[:3]
        )
        return {
            "kind": "stop_ambiguous",
            "message": f"Which stop did you mean?\n{options}",
            "pending_stops": stops[:3],
        }

    return {
        "kind": "stop_required",
        "message": (
            "Which bus stop? Say like 'next bus from Tampines West CC' or "
            "send a 5-digit stop code."
        ),
    }
