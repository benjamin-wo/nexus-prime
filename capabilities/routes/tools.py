import json
import re
from typing import Dict, Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from core.config import settings
from core.llm import ThinkingLevel, get_agent_llm


@tool
async def plan_route(origin: str, destination: str, mode: str = "transit") -> Dict[str, Any]:
    """
    Plan a route between origin and destination via the Google Maps Directions API.
    Mode can be transit, driving, walking, or bicycling.
    """
    mode = mode.lower() if mode.lower() in ("transit", "driving", "walking", "bicycling") else "transit"

    # No API key configured (local tests/dev): structured fallback.
    if not settings.google_maps_api_key or settings.google_maps_api_key.startswith("your_"):
        eta_minutes = 25 if mode == "transit" else 18
        return {
            "origin": origin,
            "destination": destination,
            "mode": mode,
            "eta_minutes": eta_minutes,
            "distance_km": 20.0,
            "summary": f"Route from {origin} to {destination} via {mode}: ~{eta_minutes} mins.",
            "steps": [f"Depart from {origin}", f"Arrive at {destination}"],
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
    if not settings.deepseek_api_key or settings.deepseek_api_key == "test_deepseek_key":
        return {"origin": None, "destination": None, "mode": "transit"}

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
    try:
        parsed = json.loads(raw)
        return {
            "origin": parsed.get("origin"),
            "destination": parsed.get("destination"),
            "mode": parsed.get("mode") or "transit",
        }
    except Exception as exc:  # noqa: BLE001
        print(f"[ROUTES] extraction parse failed: {exc}")
        return {"origin": None, "destination": None, "mode": "transit"}
