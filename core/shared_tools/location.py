from typing import Optional
from datetime import datetime
import httpx
from core.config import settings

# Quick lookup for major cities and travel hubs to support travel timezone detection
CITY_TIMEZONE_MAP = {
    "tokyo": "Asia/Tokyo",
    "new york": "America/New_York",
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong",
    "sydney": "Australia/Sydney",
    "los angeles": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "dubai": "Asia/Dubai",
}

def resolve_timezone_from_location(location_name: str) -> Optional[str]:
    """Resolve a city or country name to an IANA timezone string."""
    key = location_name.strip().lower()
    for city, tz in CITY_TIMEZONE_MAP.items():
        if city in key:
            return tz
    return None

def resolve_timezone_from_coordinates(lat: float, lon: float) -> str:
    """Simple coordinate heuristic for common zones; defaults to UTC if ambiguous."""
    if lat > 30 and 130 < lon < 145:
        return "Asia/Tokyo"
    if 40 < lat < 55 and -10 < lon < 15:
        return "Europe/Paris"
    if 24 < lat < 50 and -125 < lon < -65:
        return "America/New_York"
    return "UTC"


async def resolve_timezone_from_coordinates_api(lat: float, lon: float) -> Optional[str]:
    """Resolve an IANA timezone from coordinates via the Google Time Zone API."""
    api_key = settings.google_maps_api_key
    if not api_key or api_key.startswith("your_"):
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/timezone/json",
                params={
                    "location": f"{lat},{lon}",
                    "timestamp": int(datetime.now().timestamp()),
                    "key": api_key,
                },
            )
            data = resp.json()
        if data.get("status") == "OK" and data.get("timeZoneId"):
            return data["timeZoneId"]
        print(f"[LOCATION] timezone api status: {data.get('status')}")
    except Exception as exc:  # noqa: BLE001
        print(f"[LOCATION] timezone api error: {exc}")
    return None
