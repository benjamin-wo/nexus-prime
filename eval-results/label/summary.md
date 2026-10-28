# Label evals: branch vs main

Branch `claude/adoring-lamport-4a97mv` @ 161dc45 vs `main` @ 5c8cbe3.
Flags: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low --case itinerary --case timezone --case messy --case trip --repeat 4`

Overall: branch **201/204**, main **197/200** (main has 50 cases; `timezone-landed-tokyo` exists only on the branch).

## Key cases

| Case | Branch | Main |
|---|---|---|
| itinerary-label-days | 4/4 | 4/4 |
| messy-yen | 4/4 | 4/4 |
| timezone-landed-tokyo | 4/4 | – (not on main) |
| timezone-arrived | 4/4 | 4/4 |
| trip-find-in-stop | 3/4 | 3/4 |

## Branch 2+ runs worse than main

- `trip-heading-there-no-parrot`: branch 2/4 vs main 4/4

Other differences (under 2 runs): see `compare.txt`.

## Branch failures

### `trip-heading-there-no-parrot` (round 2)

- Failed check: reply longer than 220 characters

**User:** where should we eat in Osaka? we want the best okonomiyaki

Tool calls:

- `load_skill` `{"name": "trips"}`
- `list_trips` `{}`
- `find_ideas` `{"query": "best okonomiyaki", "stop": "Osaka"}`
- `find_places` `{"query": "best okonomiyaki in Osaka"}`

Replies:

> I can't pull up place suggestions right now — the maps and guide search aren't available on my side at the moment.
> 
> If you name a spot you're eyeing, I can still save it to your Japan trip (10–18 Dec, with Ann) as a place to visit.


**User:** ok we are heading to Osaka now, since we are skipping lunch

Tool calls:

- `set_timezone` `{"place": "Osaka"}`
- `find_places` `{"query": "okonomiyaki in Osaka"}`
- `set_timezone` `{"place": "Asia/Tokyo"}`

Replies:

> On Japan time now ✅
> 
> Maps search is still down, so I can't hand you okonomiyaki picks — Dotonbori and Shinsekai are the classic okonomiyaki areas if you're deciding on the ground. Want me to save anywhere you land on to the Japan trip?


### `trip-heading-there-no-parrot` (round 3)

- Failed check: reply longer than 220 characters

**User:** where should we eat in Osaka? we want the best okonomiyaki

Tool calls:

- `load_skill` `{"name": "trips"}`
- `list_trips` `{}`
- `find_ideas` `{"query": "best okonomiyaki", "stop": "Osaka"}`
- `find_places` `{"query": "best okonomiyaki in Osaka"}`

Replies:

> I can't pull place ideas or ratings right now — both the guides and Google Maps lookups are down on my side, so I'd only be guessing.
> 
> Osaka isn't on your trip yet either (you've got Tokyo, 10–18 Dec, with Ann). Want me to add Osaka as a stop, or try the search again in a bit?


**User:** ok we are heading to Osaka now, since we are skipping lunch

Tool calls:

- `set_timezone` `{"place": "Osaka, Japan"}`
- `find_places` `{"query": "okonomiyaki in Osaka"}`
- `set_timezone` `{"place": "Japan"}`
- `set_timezone` `{"place": "Asia/Tokyo"}`

Replies:

> On Osaka time now ✅
> 
> Places search is still down, so I can't give you a proper okonomiyaki pick — I won't guess at names. If you want, I can try again once it's back, or add Osaka as a stop on the trip so it's ready when it is.


### `trip-find-in-stop` (round 4)

- Failed check: no find_ideas call with {'stop': Has(text='kyoto')}

**User:** things to do in Kyoto for my japan trip

Tool calls:

- `load_skill` `{"name": "trips"}`
- `list_trips` `{}`
- `find_ideas` `{"query": "things to do in Kyoto"}`
- `find_places` `{"query": "things to do", "stop": "Kyoto"}`

Replies:

> I can't pull ideas or places right now — both lookups are down on my side, so no ratings or suggestions to give you.
> 
> Your Japan trip is Tokyo, 10–18 Dec, so Kyoto isn't on it yet. Want me to add Kyoto as a stop (say which days) so it's ready when the search is back?


## Main failures

### `trip-find-in-stop` (round 4)

- Failed check: no find_ideas call with {'stop': Has(text='kyoto')}

**User:** things to do in Kyoto for my japan trip

Tool calls:

- `load_skill` `{"name": "trips"}`
- `list_trips` `{}`
- `find_ideas` `{"query": "things to do in Kyoto"}`
- `find_places` `{"query": "things to do in Kyoto"}`

Replies:

> Ideas and place search aren't set up right now, so I can't pull Kyoto suggestions — and I won't make them up.
> 
> Your Japan trip is Tokyo only (10–18 Dec, with Ann). Want me to add Kyoto as a stop, or research Kyoto so you get areas, costs and things to do?


### `itinerary-gelato-after-the-castle` (round 4)

- Failed check: no add_to_itinerary call with {'name': Has(text='gelato'), 'after': Has(text='kuroshiro'), 'day': Has(text='2026-12-12')}

**User:** add Kuroshiro Castle to the 12th of my Japan trip

Tool calls:

- `load_skill` `{"name": "trips"}`
- `list_trips` `{}`
- `add_to_itinerary` `{"kind": "activity", "name": "Kuroshiro Castle", "day": "2026-12-12", "category": "Sight", "minutes": 90, "trip": "Tokyo"}`

Replies:

> Kuroshiro Castle is on for Sat 12 Dec, 09:00–10:30 ✅


**User:** add a gelato stop after the castle

Tool calls:

- `find_places` `{"query": "gelato", "day": "12", "trip": "Tokyo"}`
- `add_to_itinerary` `{"after": "Kuroshiro Castle", "category": "Food", "kind": "activity", "minutes": 20, "name": "Gelato stop", "trip": "Tokyo"}`
- `trip_status` `{"trip": "Tokyo"}`
- `change_itinerary_entry` `{"item": "Gelato stop", "day": "2026-12-12", "after": "Kuroshiro Castle", "trip": "Tokyo"}`
- `trip_status` `{"trip": "Tokyo"}`
- `change_itinerary_entry` `{"item": "Gelato stop", "time": "10:30", "minutes": 20, "trip": "Tokyo"}`

Replies:

> Gelato stop is right after the castle, 10:30–10:50 ✅


### `messy-euro` (round 4)

- Failed check: expected logged out 3.50 EUR, mentioning 'coffee'

**User:** €3.50 coffee in paris

Tool calls:

- `set_timezone` `{"place": "Paris"}`
- `log_expense` `{"amount": "3.50", "currency": "EUR", "best_guess_category": "Dining Out"}`
- `set_timezone` `{"place": "Europe/Paris"}`

Replies:

> €3.50 coffee logged ✅ And I've switched your days to Paris time.

