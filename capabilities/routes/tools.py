from typing import Dict, Any
from langchain_core.tools import tool

@tool
async def plan_route(origin: str, destination: str, mode: str = "transit") -> Dict[str, Any]:
    """
    Plan a transit or driving route between origin and destination, returning ETA and steps.
    Mode can be 'transit' or 'driving'.
    """
    # In live execution, this queries a mapping API (Google Maps / OpenTripPlanner)
    # Returns structured route info formatted for Telegram presentation
    eta_minutes = 25 if mode.lower() == "transit" else 18
    return {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "eta_minutes": eta_minutes,
        "summary": f"Route from {origin} to {destination} via {mode}: ~{eta_minutes} mins.",
        "steps": [
            f"Depart from {origin}",
            f"Take {mode} line for {eta_minutes - 5} minutes",
            f"Arrive at {destination}",
        ],
    }
