# cards2 branch — live eval summary (3 November 2026)

Branch `claude/evals-cards2`, no code changes. Run:

```
uv run python -m nexus.evals --model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks \
  --vision-model qwen/qwen3.8-flash --reasoning low \
  --case wallet-card-bill --case wallet-card-bill-named --case safe-pay-card \
  --case itinerary-gelato-after-the-castle --case wallet-paid-with --case wallet-edit-paid-with \
  --case wallet-usual-card --repeat 4 --out eval-results/cards2-branch
```

The `--case` filters are prefixes: `wallet-card-bill` also matched `wallet-card-bill-named`, and
`wallet-paid-with` matched `wallet-paid-with-card` and `wallet-paid-with-unknown-card-asks`, so 8 cases ran.

Result: **30/32** (7.5/8 a round, min 7, max 8). Errors 0, model failures 0. Median reply 1.7s, p90 3.6s.
Cost $0.0242 total. Full report and JSON: `eval-results/cards2-branch/`.

| Case | Passed |
|---|---|
| wallet-card-bill | 4/4 |
| wallet-card-bill-named | 4/4 |
| wallet-paid-with-card | 4/4 |
| wallet-paid-with-unknown-card-asks | 4/4 |
| wallet-edit-paid-with | 4/4 |
| wallet-usual-card | 4/4 |
| safe-pay-card | 4/4 |
| itinerary-gelato-after-the-castle | 2/4 (flaky) |

## Failures

- `itinerary-gelato-after-the-castle`, round 3: no `add_to_itinerary` call with name ~ "gelato",
  after ~ "castle", day 2026-12-12.
- `itinerary-gelato-after-the-castle`, round 4: 2 `add_to_itinerary` calls with name ~ "gelato"
  (max 1 allowed) — the item was added twice.

## Notes

- During the run a `openai.LengthFinishReasonError` traceback was logged (a structured-output call hit its
  1500-token completion limit). It was caught: the report counts 0 errors, and it did not fail a case by itself.
