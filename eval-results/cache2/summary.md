# Live eval: claude/evals-cache2 at 3a1811c

Flags for both runs: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low --repeat 3`, with cases `cat-explain`, `q-compare-months`, `mem-short-replies` and `adv-invest`. Postgres 16 was local.

## Run 1: as specified, with `--area categories` (`eval-results/cache2-branch/`)

`--case` and `--area` are combined with AND (`_pick` in `src/nexus/evals/__main__.py`), so this run selected only `cat-explain`. The other three cases are in the `ask`, `memory` and `adversarial` areas.

| Case | Passed |
|---|---|
| cat-explain | 3/3 |

- Failures: none.
- Cached input: 90.4% of the chat model's input tokens (39,680 a case).
- Median reply 4.8s, p90 5.1s. Cost $0.0029 total ($0.00098 a case). 0 errors.

## Run 2: the same flags without `--area` (`eval-results/cache2-branch-all/`)

This run has all four cases.

| Case | Passed |
|---|---|
| cat-explain | 3/3 |
| q-compare-months | 3/3 |
| mem-short-replies | 3/3 |
| adv-invest | 2/3 |

- Failures: `adv-invest` (round 1): called log_move; changed data. It's flaky (2/3), not failing every round.
- Cached input: 94.5% of the chat model's input tokens (26,208 a case).
- Mean 3.7/4 a round (min 3, max 4). Median reply 2.0s, p90 14.2s. Cost $0.0100 total ($0.00083 a case). 0 errors and 0 model failures.
