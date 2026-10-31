# Payer eval: claude/adoring-lamport-4a97mv vs main (31 October 2026)

Branch commit `9fe2c8c` (as checked out on `claude/evals-payer`); main `0c9e5ad`.

Flags for both: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low --repeat 3`

Cases: `--case plan-pay --case mem- --case voice-default-no-stock`. `inc-` was dropped because it matches no case id (the income cases are `income-*`). On main the `plan-pay` prefix picks up the same cases except `plan-pay-payer`, which main doesn't have, so nothing needed removing there.

Files: `payer-main/20261031-000841-*` (main), `payer-branch/20261031-000838-*` (branch).

## Totals

| | Passed | Mean a round | Median reply | Cost a case |
|---|---|---|---|---|
| main | 54/54 | 18.0/18 | 1.5s | $0.00070 |
| branch | 56/57 | 18.7/19 | 1.5s | $0.00069 |

Errors: 0 and model failures: 0 in both.

## Pass rates per case

| Case | main | branch |
|---|---|---|
| plan-pay-phrasing | 3/3 | 3/3 |
| plan-pay-aircon | 3/3 | 3/3 |
| plan-pay-rule | 3/3 | 3/3 |
| plan-pay-payer | n/a | **2/3** |
| mem-person | 3/3 | 3/3 |
| mem-the-usual | 3/3 | 3/3 |
| mem-split-habit | 3/3 | 3/3 |
| mem-split-habit-mum | 3/3 | 3/3 |
| mem-split-habit-treat | 3/3 | 3/3 |
| mem-split-habit-other-category | 3/3 | 3/3 |
| voice-default-no-stock | 3/3 | 3/3 |
| mem-short-replies | 3/3 | 3/3 |
| mem-episode | 3/3 | 3/3 |
| mem-employer | 3/3 | 3/3 |
| mem-goal | 3/3 | 3/3 |
| mem-name | 3/3 | 3/3 |
| mem-forget | 3/3 | 3/3 |
| mem-changed-job | 3/3 | 3/3 |
| mem-not-a-rule | 3/3 | 3/3 |

## Compare output

`uv run python -m nexus.evals compare eval-results/payer-main/*.json eval-results/payer-branch/*.json`

```
case            20261031-000841-deepseek_deepseek-v4.1-flash  20261031-000838-deepseek_deepseek-v4.1-flash
plan-pay-payer                                             -                                           2/3
(18 cases passed every run in both files; --all shows them)

Passed overall: 20261031-000841-deepseek_deepseek-v4.1-flash 54/54, 20261031-000838-deepseek_deepseek-v4.1-flash 56/57
Rates differing by 2 or more out of N: 0
In only one file: plan-pay-payer
```

## Cases worse on the branch

None. Every case that exists on both sides passed 3/3 on both.

## `plan-pay-payer`

**Does not pass 3/3: it passed 2/3** (failed in round 1, passed rounds 2 and 3).

Failure in round 1: `no set_pay_schedule call with {'payer': Has(text='acme')}` and `expected paid by Acme`. Given "my salary comes from Acme Pte Ltd", the model made no tool call at all. It replied "Got it — Acme Pte Ltd it is." and saved nothing to the pay schedule. With three runs, one miss isn't enough to tell flakiness from a consistent weak spot. More rounds would show which.
