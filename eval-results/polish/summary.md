# Live evals — polish runs

Commit `7ebcba7` (tip of `claude/adoring-lamport-4a97mv`), run 2026-10-27, full set (277 cases), no `--case` filter.

Flags: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`

| Run | Passed | Median turn | p90 turn | Cost | Errors |
|---|---|---|---|---|---|
| run1 (`polish-run1/20261027-155753-*`) | **275/277** (99%) | 2.2s | 4.8s | $1.4525 | 0 |
| run2 (`polish-run2/20261027-160448-*`) | **275/277** (99%) | 2.2s | 4.4s | $1.4507 | 0 |

## Openers after a change

- run1 (143 replies): "grab transport's" 4%, "at maxwell" 3%, "dining out" 3%
- run2 (141 replies): "grab transport's" 4%, "at maxwell" 4%, "for the" 3%

## Failures

| Case | run1 | run2 |
|---|---|---|
| `wallet-find-likely-moves` | FAIL | FAIL |
| `trip-find-in-stop` | FAIL | pass |
| `web-search-protest-now` | pass | FAIL |

### `wallet-find-likely-moves` (wallets) — failed in both runs

Check: no `find_likely_moves` call with any arguments.

**run1** — "did I log any transfers to my own accounts as spending?" (5.24s)
- Calls: `find_transactions` ×8 — `{direction: move, limit: 50}`, then `search` = transfer, savings, IBKR, card, top up, invest, bill
- Reply: "No — nothing like that in your ledger. No moves between your own wallets at all, and no transfer, savings, IBKR or card-bill entries logged as spending. So your 460.03 spent this month is all real spending, and put away is still 0.00."

**run2** — same message (3.34s)
- Calls: `query_ledger {direction: move, start_date: 2026-01-01, end_date: 2026-09-28, top: 20}`, then `find_transactions` ×7 with `search` = transfer, savings, IBKR, card, top up, invest, bill
- Reply: "No — nothing like that in your ledger. Zero moves recorded all year, and no transfer, top-up or card-bill entries logged as spending either. If you did move money recently, tell me the amount and where it went and I'll log it properly as a move."

The model never reaches for `find_likely_moves`; it hand-searches by keyword instead. Consistent, so likely a tool-description or prompt issue rather than noise.

### `trip-find-in-stop` (ask) — failed in run1 only

Check: no `find_ideas` call with `{'stop': Has(text='kyoto')}`.

**run1** — "things to do in Kyoto for my japan trip" (6.16s)
- Calls: `load_skill {name: trips}`, `list_trips {}`, `find_ideas {query: "things to do in Kyoto"}`, `find_places {query: "things to do in Kyoto"}`
- Reply: "Ideas search isn't available right now, so I can't pull Kyoto suggestions — sorry. Two things I can do: • Add Kyoto as a day (or two) on your Tokyo trip, 10–18 Dec, so it's in the plan • Save any Kyoto spots you name (Fushimi Inari, Nishiki Market, Arashiyama) as places to visit. Want me to put Kyoto in as a day trip?"

It called `find_ideas` but put Kyoto in `query` with no `stop` argument.

### `web-search-protest-now` (ask) — failed in run2 only

Check: no `web_search` call with `{'question': Has(text='gran via'), 'recent': 'today', 'local_query': Has(text=' ')}`.

**run2**
- Turn 1 — "I just landed in Madrid" (1.94s): `set_timezone {place: Madrid}` → "Madrid time it is — your days and reminders will follow you there."
- Turn 2 — "is there a protest near Gran Via right now?" (1.67s): `web_search {question: "protest or demonstration near Gran Vía Madrid today 28 September 2026", recent: today, local_query: "manifestación Gran Vía Madrid hoy 28 septiembre 2026"}` → "I couldn't find anything from today — the news search isn't working on my end right now, so I can't tell you either way. Worth checking local news or asking at your hotel desk before heading over."

The behaviour is right; the model wrote "Gran Vía" (accented) and the check's `Has(text='gran via')` doesn't fold accents. This is a strict check, not a model fault.

## Notes

- The run logs show the trip-screenshot reader (run1) and the memory writer (run2) each hit a reply that didn't parse and retried. Neither caused a case failure or an error.
