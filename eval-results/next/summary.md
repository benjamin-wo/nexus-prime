# Live evals: branch vs main (28 October 2026)

- Branch: `claude/adoring-lamport-4a97mv` at `e940332` (origin's tip; the local branch was stale, 1 ahead / 8 behind, so the origin tip was used).
- main: `b35a353`.
- Flags on every run: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`; default speech model.
- Focus selection: `--case wallet --case voice --case mem`. Branch ran it with `--repeat 3` (44 cases). main has no `--repeat`, so it ran 3 separate times (40 cases; the 4 new branch cases don't exist there).
- `python -m nexus.evals compare` was not run: main's files are the old single-run format, so the rates below were counted from the JSON directly.

## Focus runs

| | Rounds | Cases |
|---|---|---|
| Branch | 43, 43, 43 | 44 |
| main | 40, 39, 39 | 40 |

### Wallet cases

| Case | Branch | main |
|---|---|---|
| `wallet-move-ibkr` | 3/3 | 3/3 |
| `wallet-card-bill` | 3/3 | 3/3 |
| `wallet-top-up-savings` | 3/3 | 3/3 |
| `wallet-out-of-savings` | 3/3 | 3/3 |
| `wallet-to-wallet` | 3/3 | 3/3 |
| `wallet-person-is-not-a-move` | 3/3 | 3/3 |
| `wallet-unknown-asks` | 3/3 | 3/3 |
| `wallet-instruction-refused` | 3/3 | 3/3 |
| `wallet-scheduled-move` | 3/3 | 3/3 |
| `wallet-find-likely-moves` | 3/3 | 1/3 |
| `wallet-find-likely-moves-savings` | 3/3 | — |
| `wallet-find-likely-moves-topups` | 3/3 | — |

`wallet-find-likely-moves` goes from 1/3 on main to 3/3; both new variants pass 3/3. On main the two failures never called `find_likely_moves` (they searched with `query_ledger` and seven `find_transactions` calls, then said nothing was logged as spending).

### Voice cases

| Case | Branch | main |
|---|---|---|
| `voice-direct` | 3/3 | 3/3 |
| `voice-cheeky` | 3/3 | 3/3 |
| `voice-shorter-from-now-on` | 3/3 | — |
| `voice-one-off-short` | 3/3 | — |
| `voice-default-no-stock` | 3/3 | 3/3 |
| `voice-grab` | 3/3 | 3/3 |
| `voice-grab-noisy` | 3/3 | 3/3 |
| `voice-lunch-maxwell` | 3/3 | 3/3 |
| `voice-lunch-maxwell-noisy` | 3/3 | 3/3 |
| `voice-taxi-last-friday` | 3/3 | 3/3 |
| `voice-netflix` | 3/3 | 3/3 |
| `voice-laptop` | 3/3 | 3/3 |
| `voice-rent-paid` | 3/3 | 3/3 |
| `voice-bill-savings` | 3/3 | 3/3 |
| `voice-split-clean` | 3/3 | 3/3 |
| `voice-split-noisy` | 3/3 | 3/3 |
| `voice-question` | 3/3 | 3/3 |
| `voice-question-noisy` | 3/3 | 3/3 |

All 21 voice cases pass 3/3 on the branch (19/19 shared cases 3/3 on main).

### Memory cases

| Case | Branch | main |
|---|---|---|
| `mem-person` | 3/3 | 3/3 |
| `mem-the-usual` | 3/3 | 3/3 |
| `mem-split-habit` | 3/3 | 3/3 |
| `mem-split-habit-mum` | 3/3 | 3/3 |
| `mem-split-habit-treat` | 3/3 | 3/3 |
| `mem-split-habit-other-category` | 3/3 | 3/3 |
| `mem-short-replies` | 0/3 | 3/3 |
| `mem-episode` | 3/3 | 3/3 |
| `mem-employer` | 3/3 | 3/3 |
| `mem-goal` | 3/3 | 3/3 |
| `mem-name` | 3/3 | 3/3 |
| `mem-forget` | 3/3 | 3/3 |
| `mem-changed-job` | 3/3 | 3/3 |
| `mem-not-a-rule` | 3/3 | 3/3 |

**Regression:** `mem-short-replies` is 0/3 on the branch, 3/3 on main. After "please keep your replies short" (stored via `set_voice` `{"length": "short"}`), the spending reply adds "Dining Out's at 143.90 of your 300 budget, so plenty of room." and goes over 160 characters. main's reply is the same without that line.

Not a case failure: in the branch focus run (and main runs 1 and 2) the memory writer once hit its 1,500-token cap on reasoning alone (`LengthFinishReasonError`), logged a traceback and retried; errors reported 0.

## Full run (branch, once)

**278/281** (99%). Median reply 1.9s, p90 4.1s; $0.00526 a case ($1.48 total); errors 0.

## Failing cases

### Focus run, branch

### `mem-short-replies` (round 1) — 20261028-001551-deepseek_deepseek-v4.1-flash.json
Failures: reply longer than 160 characters | error: None
- user: 'please keep your replies short'
  - call `set_voice` {"length": "short"}
  - reply: 'Short it is.'
- user: 'how much did i spend this month'
  - call `spending_summary` {}
  - reply: "460.03 this month, across 15 transactions.\n\n• Dining Out 143.90\n• Transport 96.30\n• Groceries 88.45\n\nDining Out's at 143.90 of your 300 budget, so plenty of room."

### `mem-short-replies` (round 2) — 20261028-001551-deepseek_deepseek-v4.1-flash.json
Failures: reply longer than 160 characters | error: None
- user: 'please keep your replies short'
  - call `set_voice` {"length": "short"}
  - reply: 'Short it is.'
- user: 'how much did i spend this month'
  - call `spending_summary` {}
  - reply: "460.03 this month, across 15 transactions.\n\n• Dining Out 143.90\n• Transport 96.30\n• Groceries 88.45\n\nDining Out's at 143.90 of your 300 budget, so plenty of room."

### `mem-short-replies` (round 3) — 20261028-001551-deepseek_deepseek-v4.1-flash.json
Failures: reply longer than 160 characters | error: None
- user: 'please keep your replies short'
  - call `set_voice` {"length": "short"}
  - reply: 'Done — short from now on.'
- user: 'how much did i spend this month'
  - call `spending_summary` {}
  - reply: "460.03 this month, across 15 transactions.\n\n• Dining Out 143.90\n• Transport 96.30\n• Groceries 88.45\n\nDining Out's at 143.90 of your 300 budget, so plenty of room left."

### Focus runs, main

### `wallet-find-likely-moves` — 20261028-001946-deepseek_deepseek-v4.1-flash.json
Failures: no find_likely_moves call with any arguments | error: None
- user: 'did I log any transfers to my own accounts as spending?'
  - call `query_ledger` {"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28", "top": 31}
  - call `find_transactions` {"search": "transfer", "limit": 20}
  - call `find_transactions` {"search": "savings", "limit": 20}
  - call `find_transactions` {"search": "IBKR", "limit": 20}
  - call `find_transactions` {"search": "card", "limit": 20}
  - call `find_transactions` {"search": "invest", "limit": 20}
  - call `find_transactions` {"search": "top up", "limit": 20}
  - call `find_transactions` {"search": "bill", "limit": 20}
  - reply: "No — nothing like that in your ledger. Zero moves between your own wallets all year, and no transfer, savings, IBKR or card-bill entries logged as spending either.\n\nWorth knowing: that also means nothing's gone into Savings or IBKR this year, so if you've been topping them up, those aren't being tracked. Want me to log one?"

### `wallet-find-likely-moves` — 20261028-002044-deepseek_deepseek-v4.1-flash.json
Failures: no find_likely_moves call with any arguments | error: None
- user: 'did I log any transfers to my own accounts as spending?'
  - call `query_ledger` {"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28", "top": 20}
  - call `find_transactions` {"search": "transfer", "limit": 20}
  - call `find_transactions` {"search": "savings", "limit": 20}
  - call `find_transactions` {"search": "IBKR", "limit": 20}
  - call `find_transactions` {"search": "card", "limit": 20}
  - call `find_transactions` {"search": "invest", "limit": 20}
  - call `find_transactions` {"search": "top up", "limit": 20}
  - call `find_transactions` {"search": "bill", "limit": 20}
  - call `query_ledger` {"direction": "move", "start_date": "2020-01-01", "end_date": "2026-09-28", "top": 20}
  - call `query_ledger` {"direction": "out", "start_date": "2026-01-01", "end_date": "2026-09-28", "group_by": "merchant", "measure": "total", "top": 31}
  - reply: "No — nothing in your ledger is a transfer to your own accounts logged as spending. Zero moves recorded at all, and the 23 expenses this year are all real merchants (FairPrice, Grab, Netflix, Singtel and so on).\n\nIf you did move money to Savings, IBKR or pay the Card recently, it just hasn't been logged — tell me the amount and I'll record it as a move."

### Full run, branch

### `q-saved-august` — 20261028-002151-deepseek_deepseek-v4.1-flash.json
Failures: reply lacks ('4753.22', '4,753.22') | error: None
- user: 'how much did i save in august'
  - call `query_ledger` {"direction": "move", "wallet": "Savings", "wallet_side": "into", "start_date": "2026-08-01", "end_date": "2026-08-31"}
  - call `query_ledger` {"direction": "in", "start_date": "2026-08-01", "end_date": "2026-08-31"}
  - call `query_ledger` {"direction": "out", "start_date": "2026-08-01", "end_date": "2026-08-31"}
  - reply: 'Nothing put away in August — no moves into Savings that month.\n\n• In: 5,000.00 (ACME, 25 Aug)\n• Out: 246.78\n• Into Savings: 0.00\n\nWant me to set a monthly amount to move to Savings each payday?'

### `cat-explain` — 20261028-002151-deepseek_deepseek-v4.1-flash.json
Failures: reply lacks ('grab', '42.10') | error: None
- user: "why is yesterday's grab ride in transport"
  - call `load_skill` {"name": "expenses"}
  - call `find_transactions` {"search": "Grab", "start_date": "2026-09-27", "end_date": "2026-09-27"}
  - call `explain_category` {"transaction_id": "ca210a40-f252-46ba-8fdb-6d157f8b81c5"}
  - reply: "It's in Transport because that's the category it was logged with — not from a rule.\n\nIf you'd rather it sat somewhere else, say the word and I'll move it."

### `mem-short-replies` — 20261028-002151-deepseek_deepseek-v4.1-flash.json
Failures: reply longer than 160 characters | error: None
- user: 'please keep your replies short'
  - call `set_voice` {"length": "short"}
  - reply: 'Done — short from here on.'
- user: 'how much did i spend this month'
  - call `spending_summary` {}
  - reply: "460.03 this month, across 15 transactions.\n\n• Dining Out 143.90\n• Transport 96.30\n• Groceries 88.45\n\nDining Out's at 143.90 of your 300 budget, so plenty of room."
