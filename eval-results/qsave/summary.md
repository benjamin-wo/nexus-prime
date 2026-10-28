# q-* and messy-yen: branch vs main

Model `deepseek/deepseek-v4.1-flash` (providers together, baseten, fireworks; reasoning low), vision `qwen/qwen3.8-flash`.
Branch `claude/adoring-lamport-4a97mv` @ de338e4 with `--repeat 3`; main @ b35a353, three separate runs.

| Case | Branch | Main |
|---|---|---|
| q-month-spent | 3/3 | 3/3 |
| q-category-month | 3/3 | 3/3 |
| q-last-month | 3/3 | 3/3 |
| q-merchant-month | 3/3 | 3/3 |
| q-weekends | 3/3 | 3/3 |
| q-biggest | 3/3 | 3/3 |
| q-compare-months | 3/3 | 3/3 |
| q-who-owes | 3/3 | 3/3 |
| q-bills | 3/3 | 3/3 |
| q-budget | 3/3 | 3/3 |
| q-payday | 3/3 | 3/3 |
| q-subscriptions | 3/3 | 3/3 |
| q-coming-up | 3/3 | 3/3 |
| q-yesterday | 3/3 | 3/3 |
| q-earned | 3/3 | 3/3 |
| q-categories | 3/3 | 3/3 |
| q-top-merchants | 3/3 | 3/3 |
| q-average-ride | 3/3 | 3/3 |
| q-dining-vs-last | 3/3 | 3/3 |
| q-over-50 | 3/3 | 3/3 |
| q-busiest-weekday | 3/3 | 3/3 |
| q-software-sgd | 3/3 | 3/3 |
| q-saved-august ⚠️ | 1/3 | 3/3 |
| messy-yen | 3/3 | 3/3 |
| **Total** | **70/72** | **72/72** |

## Failures

### `q-saved-august` — branch round 1

Failures: reply lacks ('4753.22', '4,753.22')

**User:** how much did i save in august

Tool calls:

- `query_ledger` `{"direction": "move", "wallet": "Savings", "wallet_side": "into", "start_date": "2026-08-01", "end_date": "2026-08-31"}`
- `spending_summary` `{"start_date": "2026-08-01", "end_date": "2026-08-31"}`
- `query_ledger` `{"direction": "in", "start_date": "2026-08-01", "end_date": "2026-08-31"}`
- `query_ledger` `{"direction": "move", "start_date": "2026-08-01", "end_date": "2026-08-31"}`

Reply:

> Nothing recorded as put away in August — no moves into Savings or IBKR that month.
> 
> What did happen:
> • In: 5,000.00 (ACME Pte Ltd, 25 Aug)
> • Out: 246.78 across 8 transactions
> 
> So the 5,000 just sat in Spending. Want me to set up a monthly transfer to Savings so it happens on its own?

### `q-saved-august` — branch round 2

Failures: reply lacks ('4753.22', '4,753.22')

**User:** how much did i save in august

Tool calls:

- `query_ledger` `{"direction": "move", "wallet": "Savings", "wallet_side": "into", "start_date": "2026-08-01", "end_date": "2026-08-31"}`
- `query_ledger` `{"direction": "in", "start_date": "2026-08-01", "end_date": "2026-08-31"}`
- `query_ledger` `{"direction": "out", "start_date": "2026-08-01", "end_date": "2026-08-31"}`

Reply:

> Nothing put away in August — no moves into Savings at all.
> 
> • In: 5,000.00 (ACME, 25 Aug)
> • Out: 246.78 across 8 transactions
> 
> So the rest just sat in Spending. Want me to set a standing transfer to Savings each payday?

