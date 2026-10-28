# Live eval summary — 2026-10-28

Flags: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`

## Focus run (`--case q- --case wallet --repeat 4`, `eval-results/save-focus`)

35 cases × 4 rounds: **35/35 every round** (140/140). No flaky or always-failing cases. Reply time per turn: median 1.5s, p90 2.3s. Cost $0.40.

| Case | Passed |
|---|---|
| q-saved-august | 4/4 |
| wallet-find-likely-moves | 4/4 |
| wallet-find-likely-moves-savings | 4/4 |
| wallet-find-likely-moves-topups | 4/4 |

Other cases under 4/4: **none**.

## Full run (all cases, once, `eval-results/save-full`)

**278/281 passed (99%)**. Reply time per turn: **median 1.8s, p90 3.9s**. Errors 0, model failures 0. Cost $1.50.
q-saved-august and all three wallet-find-likely-moves* cases passed here too.

## Failing cases (full run)

### edit-resplit-new-person (edit) — `expected Anne owes 60.00`
1. User: "split the jumbo seafood dinner with anne instead"
   - calls: `find_transactions {search: jumbo}`, `find_transactions {search: seafood}`, `load_skill {expenses}`, `list_split_habits`, `list_ious`, `split_bill {transaction_id: bc2acdb4…, participants: [{name: "Ann"}]}`, `list_ious` (1 confirmation)
   - reply: "Done — the 120 Jumbo Seafood dinner is now split with Ann: she owes 60, your half is 60. Ben's 40 for it is cleared off."
2. User: "no, Anne is a new friend from work"
   - calls: `undo_last_change`, `split_bill {transaction_id: bc2acdb4…, participants: [{name: "Anne"}, {name: "Ben"}], new_person: true}` (1 confirmation)
   - reply: "Fixed — Anne's a separate person now: she owes 40, Ben still owes 40, your share is 40."
   - Problem: Ben was put back into the split instead of Anne replacing him, so Anne owes 40 instead of 60.

### trip-find-in-stop (ask) — `no find_ideas call with {stop: has 'kyoto'}`
- User: "things to do in Kyoto for my japan trip"
- calls: `load_skill {trips}`, `list_trips`, `find_ideas {query: "things to do in Kyoto"}`, `find_places {query: "things to do in Kyoto"}`
- reply: "Couldn't pull Kyoto ideas just now — the guides and Maps lookups aren't available on my side at the moment. Your Japan trip is Tokyo, 10–18 Dec, so Kyoto would be a side trip … Want me to add Kyoto to the trip as a place to visit…?"
- Problem: Kyoto went into `query` and `find_ideas` got no `stop` argument.

### itinerary-gelato-after-the-castle (log) — `no add_to_itinerary call with {name: has 'gelato', after: has 'kuroshiro', day: has '2026-12-12'}`
1. User: "add Kuroshiro Castle to the 12th of my Japan trip"
   - calls: `load_skill {trips}`, `list_trips`, `add_to_itinerary {kind: activity, name: "Kuroshiro Castle", day: 2026-12-12, category: Sight, trip: Tokyo, minutes: 90}`
   - reply: "Kuroshiro Castle is on for Sat 12 Dec, 09:00–10:30 ✅"
2. User: "add a gelato stop after the castle"
   - calls: `find_places {query: gelato, day: "12", trip: Tokyo}`, `add_to_itinerary {kind: activity, name: "Gelato stop", day: 2026-12-12, category: Food, after: "castle", minutes: 20, trip: Tokyo}`
   - reply: "Gelato stop added for 10:45–11:05, right after the castle ✅ I couldn't pull up specific gelato places…"
   - Problem: `after` was "castle" rather than the entry's name ("Kuroshiro Castle").
