---
name: transit
description: Live Singapore bus timings and transit journeys — "next bus from Tampines West CC", "bus timing at Fullerton Sq", "how do I get to Changi".
tags: [transit, bus, commute, travel]
side_effect: read
tools:
  - get_bus_timings
  - transit_journey
  - plan_route
  - extract_route_request
---

# Bus timings & routes

## Bus arrivals ("when is the next bus at X")
1. Call `get_bus_timings` with the user's stop phrasing (name, "bus 27 from X", or 5-digit code).
2. If the reply lists multiple stops, ask which one OR re-call with the 5-digit code the user picks. Never answer with a journey when the user asked for timings AT a stop.
3. Report exactly what LTA returned — bus numbers, minutes, "due". NEVER fabricate a bus number or time.

## Journeys ("how do I get from A to B")
- Call `transit_journey(origin, destination)` — it composes Maps + LIVE next-departures. Present the numbered steps, then the map link.
- Driving/walking asks → `plan_route` with the right mode.
- If the user replies with just a place name right after a route answer, treat it as the missing endpoint of THAT journey (fill from the previous origin/destination), unless they explicitly asked for stop timings.
