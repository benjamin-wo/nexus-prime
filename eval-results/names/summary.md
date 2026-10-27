# Name-handling evals: deepseek/deepseek-v4.1-flash

Providers: together, baseten, fireworks. Runs 1 and 2 used `--case voice --case edit --case split`; the full run used no case filter.
Raw results: `eval-results/names-run1/`, `eval-results/names-run2/`, `eval-results/names-full/` (JSON plus report.md).

## Pass counts

| Run | Passed |
|---|---|
| run1 | 26/27 |
| run2 | 26/27 |
| full | 269/277 |

## Findings

- `edit-resplit-near-name` failed in all three runs, the same way each time. The model read "anne" as the existing Ann and called `split_bill` with `Ann` without asking. The confirm card said "Ann owes 60.00", the runner pressed it, and Ben's 40 IOU was replaced. No "Anne" person was created.
- `edit-resplit-new-person` passed in both runs. Turn 1 had the same silent Anne→Ann mapping (it was confirmed). In turn 2, after "Anne is a new friend from work", the model called `split_bill` with `Anne` and `new_person: true`. In run 1 it called `undo_last_change` first; in run 2 it did not.
- In both runs, both `voice-split-*` cases heard "Ann", split with Ann, and created no "Anne" IOU. All four passed.
- Full-run regressions apart from `edit-resplit-near-name`: `trip-heading-there-no-parrot` (reply too long), `web-search-protest-now`, `adv-invest` (called add_bill), `photo-hotel-booking`, `photo-day-plan`, `photo-eticket`, `photo-ringgit`. Details are below.

## Failing cases

### run1: `edit-resplit-near-name`

Failures: changed data instead of asking; expected Ann owes 40.00

**Turn 1** — user: `split the jumbo seafood dinner with anne instead` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Ann owes 60.00 SGD; your share 60.00 SGD?
```
```text
Done — Ann owes 60 for the Jumbo Seafood dinner, your half is 60.

Heads up: that replaced the old split, so Ben's 40 is off the books. Want me to put it back?
```
Tool calls:

- `find_transactions` `{"search": "jumbo", "limit": 20}`
- `find_transactions` `{"search": "seafood", "limit": 20}`
- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `list_ious` `{}`
- `split_bill` `{"transaction_id": "a5daa4f5-ec47-4a69-8091-8eded1a07d94", "participants": [{"name": "Ann", "amount": "60"}], "include_me": true}`
- `list_ious` `{}`

### run2: `edit-resplit-near-name`

Failures: didn't ask a question; changed data instead of asking; expected Ann owes 40.00

**Turn 1** — user: `split the jumbo seafood dinner with anne instead` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Ann owes 60.00 SGD; your share 60.00 SGD?
```
```text
Jumbo Seafood's now split with Ann — she owes 60, your half's 60. Ben's 40 came off since it's Ann instead.
```
Tool calls:

- `find_transactions` `{"search": "jumbo", "limit": 20}`
- `find_transactions` `{"search": "seafood", "limit": 20}`
- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `list_ious` `{}`
- `split_bill` `{"transaction_id": "ee74b78e-3b05-42f3-af95-7e43ba9cc9a7", "participants": [{"name": "Ann"}]}`
- `list_ious` `{}`

### full: `edit-resplit-near-name`

Failures: didn't ask a question; changed data instead of asking; expected Ann owes 40.00

**Turn 1** — user: `split the jumbo seafood dinner with anne instead` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Ann owes 60.00 SGD; your share 60.00 SGD?
```
```text
Jumbo Seafood's now split with Ann only — she owes 60, your half is 60. Ben's 40 is off the books.
```
Tool calls:

- `find_transactions` `{"search": "jumbo"}`
- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `list_ious` `{}`
- `split_bill` `{"transaction_id": "24ab7df9-5bcd-422f-979d-f95e7fdbff0b", "participants": [{"name": "Ann"}], "include_me": true}`
- `list_ious` `{}`

### full: `trip-heading-there-no-parrot`

Failures: reply longer than 220 characters

**Turn 1** — user: `where should we eat in Osaka? we want the best okonomiyaki` (confirm buttons pressed: 0)

Replies:

```text
Place search isn't available to me right now, so I can't pull up Osaka okonomiyaki spots with ratings — sorry.

If you name one you've heard of, I can look up its details, or save it to your Japan trip as a place to visit. Want me to try again later?
```
Tool calls:

- `load_skill` `{"name": "trips"}`
- `list_trips` `{}`
- `find_ideas` `{"query": "best okonomiyaki in Osaka"}`
- `find_places` `{"query": "best okonomiyaki in Osaka"}`

**Turn 2** — user: `ok we are heading to Osaka now, since we are skipping lunch` (confirm buttons pressed: 0)

Replies:

```text
Osaka time it is ✅ — so okonomiyaki's your first proper meal there.

Place search is still down for me, so I can't hand you a shortlist. Name one you've got your eye on and I'll check its hours, or save it to the Japan trip.
```
Tool calls:

- `set_timezone` `{"place": "Osaka"}`
- `set_timezone` `{"place": "Osaka, Japan"}`
- `set_timezone` `{"place": "Asia/Tokyo"}`

### full: `web-search-protest-now`

Failures: no web_search call with {'question': Has(text='gran via'), 'recent': 'today', 'local_query': Has(text=' ')}

**Turn 1** — user: `I just landed in Madrid` (confirm buttons pressed: 0)

Replies:

```text
Madrid time it is — your days and reminders will follow you there.
```
Tool calls:

- `set_timezone` `{"place": "Madrid"}`

**Turn 2** — user: `is there a protest near Gran Via right now?` (confirm buttons pressed: 0)

Replies:

```text
I couldn't find anything from today — the news search isn't working on my end right now, so I can't confirm or rule out a protest near Gran Vía. Worth checking local news or asking at your hotel desk before heading over.
```
Tool calls:

- `web_search` `{"question": "protest or demonstration near Gran Vía Madrid today 28 September 2026", "recent": "today", "local_query": "manifestación Gran Vía Madrid hoy 28 septiembre 2026"}`

### full: `adv-invest`

Failures: called add_bill; changed data

**Turn 1** — user: `put half my salary into stocks` (confirm buttons pressed: 0)

Replies:

```text
Half of 5,000 is 2,500, so I've set a monthly 2,500 top-up into IBKR on the 25th, starting 25 Oct ✅

One thing: your October payday lands Fri 23 Oct (the 25th is a Sunday), so want me to move the top-up to the 23rd instead?
```
Tool calls:

- `load_skill` `{"name": "bills"}`
- `load_skill` `{"name": "salary"}`
- `show_pay_schedule` `{}`
- `add_bill` `{"name": "IBKR top-up", "amount": "2500", "due_date": "2026-10-25", "repeats": "monthly", "to_wallet": "IBKR"}`

### full: `photo-hotel-booking`

Failures: expected an itinerary entry 'Hotel Kumo', from 2026-12-10, ref 482019375, booked on Staywise, costing 64500, without alex tan, 7731, 4242

**Turn 1** — user: `` (confirm buttons pressed: 0)

Replies:

```text
✈️ Added to your Tokyo, Japan trip:
• hotel booking (Hotel Kumo Asakusa, 3 nights, 10 Dec to 13 Dec; booked on Staywise, ref 482019375)
```
Tool calls:

- (none)

### full: `photo-day-plan`

Failures: expected an itinerary entry 'Sushi Ten', from 2026-12-12, ref R-55821; expected an itinerary entry 'Shibuya Sky', from 2026-12-12, ref SKY-30418; expected an itinerary entry 'teamLab', from 2026-12-12

**Turn 1** — user: `add these to my japan trip` (confirm buttons pressed: 0)

Replies:

```text
✈️ Which trip is this plan (teamLab Planets, Fri 12 Dec 09:30, Toyosu; booked on app) for?
```
```text
✈️ Which trip is this plan (Lunch, Tsukiji Outer Market, Fri 12 Dec 12:30) for?
```
```text
✈️ Which trip is this plan (Shibuya Sky, Fri 12 Dec 15:00; ref SKY-30418) for?
```
```text
The rest are on the Trips page, under Not on a trip yet.
```
Tool calls:

- (none)

### full: `photo-eticket`

Failures: expected an itinerary entry 'ZZ12', from 2026-12-10, ref ZK4P7Q, costing 820, without alex tan

**Turn 1** — user: `` (confirm buttons pressed: 0)

Replies:

```text
✈️ Added to your Tokyo, Japan trip:
• flight booking (ZZ12, Singapore → Tokyo Narita, Thu 10 Dec 08:25; ZZ13, Tokyo Narita → Singapore, Fri 18 Dec 17:30; ref ZK4P7Q)
```
Tool calls:

- (none)

### full: `photo-ringgit`

Failures: didn't ask to confirm; expected logged out 45 MYR, mentioning 'petronas', in Transport, on 2026-09-13

**Turn 1** — user: `` (confirm buttons pressed: 0)

Replies:

```text
I couldn't read a total from that photo. Tell me the amount, e.g. 'lunch 12.50'.
```
Tool calls:

- (none)

## Full transcripts of the name cases

### run1: `edit-resplit-near-name` — FAIL

**Turn 1** — user: `split the jumbo seafood dinner with anne instead` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Ann owes 60.00 SGD; your share 60.00 SGD?
```
```text
Done — Ann owes 60 for the Jumbo Seafood dinner, your half is 60.

Heads up: that replaced the old split, so Ben's 40 is off the books. Want me to put it back?
```
Tool calls:

- `find_transactions` `{"search": "jumbo", "limit": 20}`
- `find_transactions` `{"search": "seafood", "limit": 20}`
- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `list_ious` `{}`
- `split_bill` `{"transaction_id": "a5daa4f5-ec47-4a69-8091-8eded1a07d94", "participants": [{"name": "Ann", "amount": "60"}], "include_me": true}`
- `list_ious` `{}`

### run1: `edit-resplit-new-person` — PASS

**Turn 1** — user: `split the jumbo seafood dinner with anne instead` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Ann owes 60.00 SGD; your share 60.00 SGD?
```
```text
Ann owes 60 for the Jumbo Seafood dinner now ✅ Ben's 40 from that one is off the list.
```
Tool calls:

- `find_transactions` `{"search": "Jumbo"}`
- `find_transactions` `{"search": "seafood"}`
- `load_skill` `{"name": "expenses"}`
- `list_ious` `{}`
- `split_bill` `{"transaction_id": "30e6a4bf-b6e4-4b88-bd52-1b7919bd4c78", "participants": [{"name": "Ann"}]}`
- `list_ious` `{}`

**Turn 2** — user: `no, Anne is a new friend from work` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Anne owes 60.00 SGD; your share 60.00 SGD?
```
```text
Fixed — Anne owes 60 for the Jumbo Seafood dinner, and Ben's 40 is back on the list.
```
Tool calls:

- `undo_last_change` `{}`
- `split_bill` `{"transaction_id": "30e6a4bf-b6e4-4b88-bd52-1b7919bd4c78", "participants": [{"name": "Anne"}], "new_person": true}`
- `list_ious` `{}`

### run1: `voice-split-clean` — PASS

**Turn 1** — user: `[voice: dtf-us-clean]` (confirm buttons pressed: 1)

Replies:

```text
🎙 heard: "Dinner 60 at Din Tai Fung, split with Ann"
Split 2026-09-28 · -60.00 SGD · Din Tai Fung · Dining Out: Ann owes 30.00 SGD; your share 30.00 SGD?
```
```text
Din Tai Fung 60 ✅ — Ann owes you 30 for it.
```
Tool calls:

- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `log_expense` `{"amount": "60", "merchant": "Din Tai Fung", "best_guess_category": "Dining Out"}`
- `split_bill` `{"transaction_id": "fb8ccd91-6235-4bf8-b626-239fd54b242f", "participants": [{"name": "Ann"}]}`

### run1: `voice-split-noisy` — PASS

**Turn 1** — user: `[voice: dtf-us-noisy]` (confirm buttons pressed: 1)

Replies:

```text
🎙 heard: "Dinner 60 at Din Tai Fung, split with Ann"
Split 2026-09-28 · -60.00 SGD · Din Tai Fung · Dining Out: Ann owes 30.00 SGD; your share 30.00 SGD?
```
```text
Din Tai Fung 60 ✅ — Ann owes you 30 for it.
```
Tool calls:

- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `log_expense` `{"amount": "60", "merchant": "Din Tai Fung", "best_guess_category": "Dining Out"}`
- `split_bill` `{"transaction_id": "77dd8e14-fdd4-4312-82ee-599664312ba6", "participants": [{"name": "Ann"}]}`

### run2: `edit-resplit-near-name` — FAIL

**Turn 1** — user: `split the jumbo seafood dinner with anne instead` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Ann owes 60.00 SGD; your share 60.00 SGD?
```
```text
Jumbo Seafood's now split with Ann — she owes 60, your half's 60. Ben's 40 came off since it's Ann instead.
```
Tool calls:

- `find_transactions` `{"search": "jumbo", "limit": 20}`
- `find_transactions` `{"search": "seafood", "limit": 20}`
- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `list_ious` `{}`
- `split_bill` `{"transaction_id": "ee74b78e-3b05-42f3-af95-7e43ba9cc9a7", "participants": [{"name": "Ann"}]}`
- `list_ious` `{}`

### run2: `edit-resplit-new-person` — PASS

**Turn 1** — user: `split the jumbo seafood dinner with anne instead` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Ann owes 60.00 SGD; your share 60.00 SGD?
```
```text
Done — Ann owes 60 for the Jumbo Seafood dinner now, your half is 60.

That took Ben's 40 off it, since the split was replaced. Want him back on?
```
Tool calls:

- `find_transactions` `{"search": "jumbo", "limit": 20}`
- `find_transactions` `{"search": "seafood", "limit": 20}`
- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `list_ious` `{}`
- `split_bill` `{"transaction_id": "ce24750f-5f58-4050-94b8-1bcebfb93c1a", "participants": [{"name": "Ann"}]}`
- `list_ious` `{}`

**Turn 2** — user: `no, Anne is a new friend from work` (confirm buttons pressed: 1)

Replies:

```text
Split 2026-09-19 · -120.00 SGD · Jumbo Seafood · Dining Out: Anne owes 60.00 SGD; your share 60.00 SGD?
```
```text
Anne owes 60 for the Jumbo dinner, your half 60. Ben's off it.
```
Tool calls:

- `split_bill` `{"transaction_id": "ce24750f-5f58-4050-94b8-1bcebfb93c1a", "participants": [{"name": "Anne"}], "new_person": true}`
- `list_ious` `{}`

### run2: `voice-split-clean` — PASS

**Turn 1** — user: `[voice: dtf-us-clean]` (confirm buttons pressed: 1)

Replies:

```text
🎙 heard: "Dinner 60 at Din Tai Fung, split with Ann"
Split 2026-09-28 · -60.00 SGD · Din Tai Fung · Dining Out: Ann owes 30.00 SGD; your share 30.00 SGD?
```
```text
Dinner's in — 60 at Din Tai Fung, Ann owes you 30 for her half ✅
```
Tool calls:

- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `log_expense` `{"amount": "60", "merchant": "Din Tai Fung", "best_guess_category": "Dining Out"}`
- `split_bill` `{"transaction_id": "759fe46c-7d55-4cb0-b34e-4178d3d44ab1", "participants": [{"name": "Ann"}]}`

### run2: `voice-split-noisy` — PASS

**Turn 1** — user: `[voice: dtf-us-noisy]` (confirm buttons pressed: 1)

Replies:

```text
🎙 heard: "Dinner 60 at Din Tai Fung, split with Ann"
Split 2026-09-28 · -60.00 SGD · Din Tai Fung · Dining Out: Ann owes 30.00 SGD; your share 30.00 SGD?
```
```text
Din Tai Fung's in at 60, split down the middle — Ann owes you 30 ✅
```
Tool calls:

- `load_skill` `{"name": "expenses"}`
- `list_split_habits` `{}`
- `log_expense` `{"amount": "60", "merchant": "Din Tai Fung", "best_guess_category": "Dining Out", "use_split_habit": false}`
- `split_bill` `{"transaction_id": "2e621eeb-a1ec-43e8-8ebc-0ac1d55c2071", "participants": [{"name": "Ann"}]}`

## Voice split cases: Ann or Anne?

| Run | Case | Transcript heard | "Anne" IOU created? |
|---|---|---|---|
| run1 | `voice-split-clean` | Ann ("Dinner 60 at Din Tai Fung, split with Ann") | no |
| run1 | `voice-split-noisy` | Ann ("Dinner 60 at Din Tai Fung, split with Ann") | no |
| run2 | `voice-split-clean` | Ann ("Dinner 60 at Din Tai Fung, split with Ann") | no |
| run2 | `voice-split-noisy` | Ann ("Dinner 60 at Din Tai Fung, split with Ann") | no |
