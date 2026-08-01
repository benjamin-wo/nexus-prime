from datetime import datetime, timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo

def parse_iso_datetime(dt_str: str, default_tz: str = "UTC") -> datetime:
    """Parse ISO datetime string and ensure it has timezone awareness."""
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(default_tz))
        return dt
    except ValueError:
        return datetime.now(ZoneInfo(default_tz))

def convert_timezone(dt: datetime, target_tz: str) -> datetime:
    """Convert datetime to target IANA timezone."""
    tz = ZoneInfo(target_tz)
    return dt.astimezone(tz)
