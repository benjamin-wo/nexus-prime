# Style evals: 28 October 2026

Production settings on every run: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`.
Commit: `de338e4` (branch `claude/adoring-lamport-4a97mv`). Raw output is in `eval-results/style-focus/` and `eval-results/style-full/`.

## Focused run: `--case mem --case voice-shorter --case voice-one-off --case wallet --repeat 3`

28 cases × 3 rounds. **83/84 runs passed.** Reply time per turn: median 1.6s, p90 3.2s. Cost $0.33 ($0.0039 a case). Errors: 0.

| Case | Passed |
|---|---|
| mem-short-replies | **2/3** (flaky) |
| mem-person | 3/3 |
| mem-the-usual | 3/3 |
| mem-split-habit | 3/3 |
| mem-split-habit-mum | 3/3 |
| mem-split-habit-treat | 3/3 |
| mem-split-habit-other-category | 3/3 |
| mem-episode | 3/3 |
| mem-employer | 3/3 |
| mem-goal | 3/3 |
| mem-name | 3/3 |
| mem-forget | 3/3 |
| mem-changed-job | 3/3 |
| mem-not-a-rule | 3/3 |
| voice-shorter-from-now-on | 3/3 |
| voice-one-off-short | 3/3 |
| wallet-move-ibkr | 3/3 |
| wallet-card-bill | 3/3 |
| wallet-top-up-savings | 3/3 |
| wallet-out-of-savings | 3/3 |
| wallet-to-wallet | 3/3 |
| wallet-person-is-not-a-move | 3/3 |
| wallet-unknown-asks | 3/3 |
| wallet-instruction-refused | 3/3 |
| wallet-scheduled-move | 3/3 |
| wallet-find-likely-moves | 3/3 |
| wallet-find-likely-moves-savings | 3/3 |
| wallet-find-likely-moves-topups | 3/3 |

No case failed every round.

### `mem-short-replies`, round by round (turn 2 limit: 160 characters)

Turn 1 called `set_voice({"length": "short"})` in **all three rounds**. Turn 2 called `spending_summary({})` each time.

| Round | Turn 1 `set_voice`? | Turn 2 reply length | Result |
|---|---|---|---|
| 1 | yes | 110 chars | pass |
| 2 | yes | 117 chars | pass |
| 3 | yes | **165 chars** | fail: reply longer than 160 characters |

**Round 1**
- T1 "please keep your replies short" → `set_voice {"length":"short"}` → "Will do — short from now on." (28)
- T2 "how much did i spend this month" → `spending_summary {}` →
  > 460.03 this month, across 15 transactions.
  >
  > Top three:
  > • Dining Out 143.90
  > • Transport 96.30
  > • Groceries 88.45

**Round 2**
- T1 → `set_voice {"length":"short"}` → "Will do — short from now on." (28)
- T2 → `spending_summary {}` →
  > 460.03 this month, across 15 transactions.
  >
  > • Dining Out 143.90
  > • Transport 96.30
  > • Groceries 88.45
  >
  > That's 1–28 Sep.

**Round 3 (failed)**
- T1 → `set_voice {"length":"short"}` → "Done — short replies from now on." (33)
- T2 → `spending_summary {}` →
  > 460.03 this month, across 15 transactions.
  >
  > • Dining Out 143.90
  > • Transport 96.30
  > • Groceries 88.45
  >
  > Dining Out's at 143.90 of your 300 budget, so you're fine there.

The short setting saves every time. The overrun in round 3 comes from an extra budget remark tacked onto a reply that would otherwise be short.

## Full set, one run (no case filter)

**279/281 passed (99%).** Reply time per turn: **median 2.0s, p90 4.2s**. Cost $1.47 ($0.0052 a case). Errors: 0, model failures: 0. Every area scored full marks except `ask` (49/50) and `messy` (15/16). `memory` scored 14/14 and `voice` 18/18.

### Failing cases

**`q-saved-august`** (ask, M8c): reply lacks `4753.22`
- User: "how much did i save in august"
- Calls:
  1. `query_ledger {"start_date":"2026-08-01","end_date":"2026-08-31","direction":"move","wallet":"Savings","wallet_side":"into"}`
  2. `query_ledger {"start_date":"2026-08-01","end_date":"2026-08-31","direction":"in"}`
  3. `query_ledger {"start_date":"2026-08-01","end_date":"2026-08-31","direction":"out"}`
- Reply:
  > Nothing put away in August — no transfers into Savings recorded that month.
  >
  > What the month looked like:
  > • In: 5,000.00 (ACME, 25 Aug)
  > • Out: 246.78 across 8 transactions
  >
  > So if you did move money to savings in August, it never got logged. Want me to add it?

  The model read "save" as transfers into Savings and did not give income minus spending (5,000.00 − 246.78 = 4,753.22), even though it had both numbers.

**`messy-yen`** (messy): expected an expense of 1200 JPY mentioning 'ramen', in Dining Out or Travel
- User: "¥1200 ramen in tokyo"
- Calls:
  1. `log_expense {"amount":"1200","currency":"JPY","category":"Dining Out","best_guess_category":"Dining Out"}` (no description/merchant, so "ramen" was not saved)
  2. `set_timezone {"place":"Tokyo"}`
- Reply: "Ramen's in ✅ 1,200 JPY under Dining Out, and I've switched you to Tokyo time."

  The expense was saved without the word "ramen". It also changed the user's timezone without being asked.

### Other notes
- The memory writer once hit its 1,500-token output limit (`LengthFinishReasonError`). It retried, and the retry succeeded: no turn has `memory_failed` set, and no case failed because of it.
