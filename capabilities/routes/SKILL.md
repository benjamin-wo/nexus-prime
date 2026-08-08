# Transit Journey Skill — Google Maps + LTA orchestration

## Goal

Answer route and next-bus questions with a complete, live picture instead of a
static ETA.

## Tools

1. **Google Maps Directions API** (`capabilities/routes/journey.py`): plans the
   transit journey — lines, stops, walking legs, total time, and a map link.
2. **LTA DataMall** (`capabilities/routes/lta.py`): live next-departure minutes
   for each bus line at the exact departure stop.

## Orchestration recipe

1. Parse origin/destination/mode from the user message.
2. For transit requests, call Google Maps Directions first to get the journey
   structure.
3. For every transit step, resolve the Maps stop name against the cached LTA
   stop catalog (fuzzy match), then fetch live arrivals for that line at that
   stop.
4. Compose the reply: journey steps with line numbers, live minutes when
   available (scheduled departure time as fallback), total time, and a Google
   Maps link as the picture.
5. Never fabricate an ETA or bus number: if neither live nor scheduled time is
   available, show the step without a time.

## Boundaries

- Bus queries that name only a stop (no destination) use the LTA-only flow
  (stop search → arrivals), with ambiguous stops resolved by follow-up
  ("the first one").
- Driving/walking requests stay on Google Maps Directions only.
- Live LTA data requires `LTA_ACCOUNT_KEY`; directions require
  `GOOGLE_MAPS_API_KEY`; without them the reply says so instead of guessing.
