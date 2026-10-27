# Wallet evals: branch vs main

- branch: `claude/adoring-lamport-4a97mv` @ `7ebcba7`
- main: `origin/main` @ `219392a`
- flags: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low --case wallet`

## `wallet-find-likely-moves`

| run | branch | main |
|---|---|---|
| 1 | FAIL | FAIL |
| 2 | pass | pass |
| 3 | FAIL | FAIL |
| 4 | pass | FAIL |

branch: 2/4
main: 1/4

## All wallet cases (passes out of 4 runs)

| case | branch | main |
|---|---|---|
| `wallet-move-ibkr` | 4/4 | 4/4 |
| `wallet-card-bill` | 4/4 | 4/4 |
| `wallet-top-up-savings` | 4/4 | 4/4 |
| `wallet-out-of-savings` | 4/4 | 4/4 |
| `wallet-to-wallet` | 4/4 | 4/4 |
| `wallet-person-is-not-a-move` | 4/4 | 4/4 |
| `wallet-unknown-asks` | 4/4 | 4/4 |
| `wallet-instruction-refused` | 4/4 | 4/4 |
| `wallet-scheduled-move` | 4/4 | 4/4 |
| `wallet-find-likely-moves` | 2/4 | 1/4 |
| **total** | **38/40** | **37/40** |

Per run:

| run | branch | main |
|---|---|---|
| 1 | 9/10 | 9/10 |
| 2 | 10/10 | 10/10 |
| 3 | 9/10 | 9/10 |
| 4 | 10/10 | 9/10 |

## Failures and their tool calls

### branch-1: `wallet-find-likely-moves`

- failure: no find_likely_moves call with any arguments

Turn 1: 'did I log any transfers to my own accounts as spending?'
- `query_ledger` `{"direction": "move", "start_date": "2026-09-01", "end_date": "2026-09-28"}`
- `find_transactions` `{"search": "savings", "limit": 20}`
- `find_transactions` `{"search": "IBKR", "limit": 20}`
- `find_transactions` `{"search": "transfer", "limit": 20}`
- `find_transactions` `{"direction": "out", "start_date": "2026-09-01", "end_date": "2026-09-28", "limit": 50}`
- `find_transactions` `{"direction": "out", "limit": 50, "start_date": "2026-06-01", "end_date": "2026-08-31"}`
- `find_transactions` `{"search": "card", "limit": 20}`
- `find_transactions` `{"search": "bill", "limit": 20}`
- `query_ledger` `{"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28"}`

### branch-3: `wallet-find-likely-moves`

- failure: no find_likely_moves call with any arguments

Turn 1: 'did I log any transfers to my own accounts as spending?'
- `query_ledger` `{"direction": "move", "start_date": "2026-09-01", "end_date": "2026-09-28"}`
- `find_transactions` `{"search": "transfer", "limit": 20}`
- `find_transactions` `{"search": "savings", "limit": 20}`
- `find_transactions` `{"search": "IBKR", "limit": 20}`
- `find_transactions` `{"search": "card", "limit": 20}`
- `find_transactions` `{"search": "bill", "limit": 20}`
- `find_transactions` `{"search": "top up", "limit": 20}`
- `find_transactions` `{"search": "invest", "limit": 20}`
- `query_ledger` `{"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28"}`
- `find_transactions` `{"start_date": "2026-09-01", "end_date": "2026-09-28", "limit": 50}`

### main-1: `wallet-find-likely-moves`

- failure: no find_likely_moves call with any arguments

Turn 1: 'did I log any transfers to my own accounts as spending?'
- `query_ledger` `{"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28", "top": 31}`
- `find_transactions` `{"search": "transfer", "limit": 20}`
- `find_transactions` `{"search": "savings", "limit": 20}`
- `find_transactions` `{"search": "IBKR", "limit": 20}`
- `find_transactions` `{"limit": 20, "search": "card"}`
- `find_transactions` `{"limit": 20, "search": "invest"}`
- `find_transactions` `{"limit": 20, "search": "top up"}`
- `find_transactions` `{"limit": 20, "search": "bill"}`

### main-3: `wallet-find-likely-moves`

- failure: no find_likely_moves call with any arguments

Turn 1: 'did I log any transfers to my own accounts as spending?'
- `find_transactions` `{"direction": "move", "limit": 50}`
- `find_transactions` `{"search": "transfer", "limit": 50}`
- `find_transactions` `{"search": "savings", "limit": 50}`
- `find_transactions` `{"search": "IBKR", "limit": 50}`
- `find_transactions` `{"search": "card", "limit": 50}`
- `query_ledger` `{"direction": "out", "start_date": "2026-01-01", "end_date": "2026-09-28", "group_by": "merchant", "measure": "total", "top": 31}`
- `query_ledger` `{"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28", "top": 31}`

### main-4: `wallet-find-likely-moves`

- failure: no find_likely_moves call with any arguments

Turn 1: 'did I log any transfers to my own accounts as spending?'
- `query_ledger` `{"direction": "move", "start_date": "2026-01-01", "end_date": "2026-09-28", "top": 20}`
- `find_transactions` `{"search": "transfer", "limit": 20}`
- `find_transactions` `{"search": "savings", "limit": 20}`
- `find_transactions` `{"search": "IBKR", "limit": 20}`
- `find_transactions` `{"search": "card", "limit": 20}`
- `find_transactions` `{"search": "top up", "limit": 20}`
- `find_transactions` `{"search": "invest", "limit": 20}`
- `query_ledger` `{"direction": "out", "start_date": "2026-01-01", "end_date": "2026-09-28", "group_by": "merchant", "measure": "total", "top": 31}`

