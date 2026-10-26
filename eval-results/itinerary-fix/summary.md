# Itinerary/trip live evals — deepseek/deepseek-v4.1-flash

Providers: together,baseten,fireworks. Cases: `--case itinerary --case trip` (32 cases). Run on branch `claude/adoring-lamport-4a97mv`, no code changes.

## Pass counts

| Run | Passed |
|---|---|
| run1 | 31/32 |
| run2 | 30/32 |

## Failing cases

### run1: `trip-find-in-stop`

- Failure: no find_ideas call with {'stop': Has(text='kyoto')}

- **User:** things to do in Kyoto for my japan trip
  - call `load_skill` `{"name": "trips"}`
  - call `list_trips` `{}`
  - call `find_ideas` `{"query": "things to do in Kyoto", "trip": "Tokyo"}`
  - call `find_places` `{"query": "things to do in Kyoto", "trip": "Tokyo"}`
  - call `find_places` `{"query": "things to do in Kyoto"}`
  - **Reply:** "Place search isn't set up right now, so I can't pull Kyoto ideas with ratings — sorry.\n\nTwo things I can do:\n• Add any Kyoto spots you name to your Japan trip (10–18 Dec, with Ann) as places to visit\n• Research Kyoto properly — areas, costs, what to do — and you can add its ideas to the trip\n\nWant me to start the Kyoto research?"

### run2: `trip-find-in-stop`

- Failure: no find_ideas call with {'stop': Has(text='kyoto')}

- **User:** things to do in Kyoto for my japan trip
  - call `load_skill` `{"name": "trips"}`
  - call `list_trips` `{}`
  - call `find_ideas` `{"query": "things to do in Kyoto"}`
  - call `find_places` `{"query": "things to do in Kyoto"}`
  - **Reply:** "Couldn't pull ideas or places just now — both lookups are down on my side, so I won't guess at a list.\n\nYour Japan trip is Tokyo, 10 to 18 Dec, so Kyoto isn't on it yet. Want me to add a Kyoto day or two to the plan, or run a proper research pass on Kyoto?"

### run2: `trip-heading-there-no-parrot`

- Failure: reply longer than 220 characters

- **User:** where should we eat in Osaka? we want the best okonomiyaki
  - call `load_skill` `{"name": "trips"}`
  - call `list_trips` `{}`
  - call `find_ideas` `{"query": "best okonomiyaki in Osaka"}`
  - call `find_places` `{"query": "best okonomiyaki in Osaka"}`
  - call `web_search` `{"question": "best okonomiyaki restaurants in Osaka"}`
  - **Reply:** "I can't pull up place suggestions right now — the maps and web lookups aren't working on my end, so I'd only be guessing at names.\n\nTwo things I can do meanwhile:\n• If you already have a shortlist (Mizuno, Chibo, Fukutaro...), tell me and I'll save them to your trip as places to visit\n• Your saved trip is Tokyo, 10–18 Dec — want me to add Osaka as a stop, or is this a separate trip?"
- **User:** ok we are heading to Osaka now, since we are skipping lunch
  - call `set_timezone` `{"place": "Osaka, Japan"}`
  - call `find_places` `{"query": "okonomiyaki in Osaka"}`
  - call `set_timezone` `{"place": "Japan"}`
  - call `set_timezone` `{"place": "Asia/Tokyo"}`
  - **Reply:** "Clocks are on Japan time now ✅\n\nPlace lookups are still down, so I can't hand you a shortlist — I won't guess at names. If you've got one in mind (Mizuno, Chibo, Fukutaro), say it and I'll save it to a trip. Want me to set up an Osaka trip so I can plan around it?"

## `itinerary-change-length` (full transcript)

### run1: PASS

- **User:** add Shop visit to my Japan trip on 11 Dec from 10:45 to 11:45
  - call `load_skill` `{"name": "trips"}`
  - call `add_to_itinerary` `{"kind": "activity", "name": "Shop visit", "day": "2026-12-11", "time": "10:45", "ends": "11:45", "trip": "Japan"}`
  - **Reply:** 'Shop visit is on for Fri 11 Dec, 10:45 to 11:45 ✅'
- **User:** make the shop visit 20 min instead
  - call `change_itinerary_entry` `{"item": "Shop visit", "minutes": 20, "trip": "Japan"}`
  - **Reply:** 'Shop visit now runs 10:45 to 11:05 ✅'

### run2: PASS

- **User:** add Shop visit to my Japan trip on 11 Dec from 10:45 to 11:45
  - call `load_skill` `{"name": "trips"}`
  - call `add_to_itinerary` `{"kind": "activity", "name": "Shop visit", "day": "2026-12-11", "time": "10:45", "ends": "11:45", "trip": "Japan"}`
  - **Reply:** 'Shop visit is on for Fri 11 Dec, 10:45 to 11:45 ✅'
- **User:** make the shop visit 20 min instead
  - call `change_itinerary_entry` `{"item": "Shop visit", "minutes": 20, "trip": "Japan"}`
  - **Reply:** 'Shop visit now runs 10:45 to 11:05 ✅'

## "too many steps" / "stopped partway"

None: no reply in either run contains either phrase.

## Notes

- The memory writer hit its 1500-token limit (`LengthFinishReasonError`, retried) twice in run1 and once in run2; the harness reported 0 errors and 0 model failures, so scoring was unaffected.
