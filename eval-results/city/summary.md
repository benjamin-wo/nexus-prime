# City eval results

Model `deepseek/deepseek-v4.1-flash` (providers together, baseten, fireworks), vision `qwen/qwen3.8-flash`, reasoning low.

- Branch: `claude/adoring-lamport-4a97mv` at `3624e35` (origin tip)
- Main: `origin/main` at `5c8cbe3`, rerun today with the same subset
- Subset: `--case trip --case itinerary --case timezone --case messy --repeat 4`

## Key cases, branch vs main (subset, 4 rounds)

| Case | Branch | Main |
|---|---|---|
| trip-heading-there-no-parrot | 4/4 | 3/4 |
| itinerary-label-days | 4/4 | 3/4 |
| trip-find-in-stop | 4/4 | 4/4 |
| messy-yen | 4/4 | 4/4 |
| timezone-landed-tokyo | 4/4 | — (not in main) |

## Cases 2+ worse than main

None.

Overall subset: branch **203/204** (51 cases), main **197/200** (50 cases; `timezone-landed-tokyo` is new on the branch).
Other differences (1 run each): `trip-spent` branch 3/4 vs main 4/4; `trip-heading-there-no-parrot`, `itinerary-label-days`, `messy-euro` branch 4/4 vs main 3/4.

## Full set on the branch (1 round)

- Passed: **280/282**
- Reply time per turn: median **1.8s**, p90 **4.4s**
- Errors: 0, model failures: 0

## Failures

### Branch subset

#### `trip-spent` (round 4)

- Failure: no trip_status call with any arguments
- Turn 1 user: "how much have I spent in Japan?"
  - Calls: `query_ledger({"merchant": "Japan", "start_date": "2026-01-01", "end_date": "2026-09-28", "top": 31})`, `find_transactions({"search": "Japan", "limit": 50})`, `load_skill({"name": "trips"})`, `find_transactions({"search": "Tokyo", "limit": 50})`, `find_transactions({"search": "JPY", "limit": 50})`, `list_trips({})`
  - Reply: "Nothing yet — your Tokyo trip (10–18 Dec) hasn't started, so there's no Japan spending on the books.\n\nBudget's 3,000.00 SGD, and you're going with Ann. Want me to check what's set aside for it so far?"

### Branch full set

#### `trip-heading-there-no-parrot`

- Failure: reply longer than 220 characters
- Turn 1 user: "where should we eat in Osaka? we want the best okonomiyaki"
  - Calls: `load_skill({"name": "trips"})`, `find_ideas({"query": "best okonomiyaki", "stop": "Osaka"})`, `find_places({"query": "best okonomiyaki", "stop": "Osaka"})`, `web_search({"question": "best okonomiyaki in Osaka"})`, `list_trips({})`
  - Reply: "I can't pull place suggestions right now — the maps and web lookups aren't set up on my side, so I'd only be guessing at names.\n\nOne thing though: your Japan trip is Tokyo, 10–18 Dec. Is Osaka part of that trip, or a separate one? Tell me and I'll keep the okonomiyaki hunt pointed at the right place once search is back."
- Turn 2 user: "ok we are heading to Osaka now, since we are skipping lunch"
  - Calls: `set_timezone({"place": "Osaka"})`, `set_timezone({"place": "Asia/Tokyo"})`
  - Reply: "On Osaka time now ✅\n\nSearch is still down, so I can't name okonomiyaki spots yet — but skipping lunch means you'll be properly hungry by dinner, which is the right way to do it. Want me to try the search again later, or save Osaka as a trip so it's all in one place?"

#### `photo-ringgit`

- Failure: didn't ask to confirm
- Failure: expected logged out 45 MYR, mentioning 'petronas', in Transport, on 2026-09-13
- Turn 1 user: ""
  - Calls: none
  - Reply: "I couldn't read a total from that photo. Tell me the amount, e.g. 'lunch 12.50'."

### Main subset (for reference)

#### `trip-heading-there-no-parrot` (round 2)

- Failure: reply longer than 220 characters
- Turn 1 user: "where should we eat in Osaka? we want the best okonomiyaki"
  - Calls: `load_skill({"name": "trips"})`, `find_ideas({"query": "best okonomiyaki", "stop": "Osaka"})`, `list_trips({})`, `find_places({"query": "best okonomiyaki in Osaka"})`
  - Reply: "Place search isn't working for me right now, so I can't pull ratings or reviews for Osaka okonomiyaki spots — I'd rather not guess names at you.\n\nOne thing though: your saved trip is Tokyo, 10–18 Dec, no Osaka on it. Want me to try the search again in a bit, or add Osaka as a stop first?"
- Turn 2 user: "ok we are heading to Osaka now, since we are skipping lunch"
  - Calls: `set_timezone({"place": "Osaka, Japan"})`, `web_search({"question": "best okonomiyaki restaurants in Osaka"})`, `set_timezone({"place": "Asia/Tokyo"})`
  - Reply: "On Tokyo time now ✅\n\nPlace and web search are both down for me at the moment, so I can't pull okonomiyaki spots for you — sorry. Google Maps on your phone will do better than me right now; try \"お好み焼き\" near wherever you land."

#### `itinerary-label-days` (round 2)

- Failure: no label_trip_day call with {'day': Has(text='2026-12-15'), 'label': Has(text='kyoto')}
- Turn 1 user: "we're in Kyoto on 15 Dec"
  - Calls: none
  - Reply: "Kyoto on 15 Dec — nice. Want me to set it up as a trip, so we can track the dates, a budget and what you spend in yen?"

#### `messy-euro` (round 3)

- Failure: expected logged out 3.50 EUR, mentioning 'coffee'
- Turn 1 user: "€3.50 coffee in paris"
  - Calls: `set_timezone({"place": "Paris"})`, `log_expense({"amount": "3.50", "currency": "EUR", "best_guess_category": "Dining Out"})`, `set_timezone({"place": "Europe/Paris"})`
  - Reply: "3.50 EUR coffee ✅ and I've switched you to Paris time."

