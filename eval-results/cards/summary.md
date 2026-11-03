# Cards branch vs main: live eval results (3 November 2026)

- Branch: `claude/adoring-lamport-4a97mv` at `8ffd53e` ("Record which card paid for each expense"). Main: `origin/main` at `553c1a0`.
- Flags for every run: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`.
- Branch and main ran side by side each time, on the same local Postgres 16. The runner made and migrated its own throwaway DB per run.
- Raw files: `eval-results/cards-{branch,main}/`, `eval-results/cards-recheck-{branch,main}/` (JSON + report), `*.log` (console output), `cards-compare.txt`, `cards-recheck-compare.txt`.

## Full runs (one sample each)

| Run | Cases | Passed | Median / p90 reply | Cost total | Cost a case |
|---|---|---|---|---|---|
| main | 283 | **282/283** | 1.8s / 4.3s | $0.1758 | $0.00062 |
| branch | 287 (+4 new) | **283/287** | 1.9s / 4.1s | $0.1757 | $0.00061 |

Failures:
- main: `log-two-at-once`.
- branch: `trip-heading-there-no-parrot`, `itinerary-gelato-after-the-castle`, `wallet-card-bill`, `mem-short-replies`.

### compare (main, branch)

```
case                                20261103-043323-deepseek_deepseek-v4.1-flash  20261103-043323-deepseek_deepseek-v4.1-flash
log-two-at-once                                                              0/1                                           1/1
trip-heading-there-no-parrot                                                 1/1                                           0/1
itinerary-gelato-after-the-castle                                            1/1                                           0/1
wallet-card-bill                                                             1/1                                           0/1
mem-short-replies                                                            1/1                                           0/1
wallet-paid-with-card                                                          -                                           1/1
wallet-paid-with-unknown-card-asks                                             -                                           1/1
wallet-edit-paid-with                                                          -                                           1/1
wallet-usual-card                                                              -                                           1/1
(278 cases passed every run in both files; --all shows them)

Passed overall: 20261103-043323-deepseek_deepseek-v4.1-flash 282/283, 20261103-043323-deepseek_deepseek-v4.1-flash 283/287
Rates differing by 2 or more out of N: 0
In only one file: wallet-paid-with-card, wallet-paid-with-unknown-card-asks, wallet-edit-paid-with, wallet-usual-card
```

(Both columns have the same file name, `20261103-043323-…`, because the runs started in the same second. The first column is main and the second is the branch.)

## Rechecks (`--repeat 3`)

Rechecked cases:
- The four that passed on main and failed on the branch.
- The four new card cases.
- `wallet-card-bill` and `safe-pay-card`.

Each was named with its own `--case`, and each prefix matches exactly one case. The new cases exist only on the branch.

| Case | main | branch |
|---|---|---|
| wallet-card-bill | 3/3 | **1/3** |
| itinerary-gelato-after-the-castle | 3/3 | 2/3 |
| trip-heading-there-no-parrot | 2/3 | 2/3 |
| mem-short-replies | 2/3 | 3/3 |
| safe-pay-card | 3/3 | 3/3 |
| wallet-paid-with-card | – | 3/3 |
| wallet-paid-with-unknown-card-asks | – | 3/3 |
| wallet-edit-paid-with | – | 3/3 |
| wallet-usual-card | – | 3/3 |

Recheck cost:
- branch: $0.0215 (27 case runs, $0.00080 a case).
- main: $0.0177 (15 case runs, $0.00118 a case).

### compare (recheck main, recheck branch)

```
case                                20261103-044011-deepseek_deepseek-v4.1-flash  20261103-044011-deepseek_deepseek-v4.1-flash
trip-heading-there-no-parrot                                                 2/3                                           2/3
itinerary-gelato-after-the-castle                                            3/3                                           2/3
wallet-card-bill                                                             3/3                                           1/3  <-
mem-short-replies                                                            2/3                                           3/3
wallet-paid-with-card                                                          -                                           3/3
wallet-paid-with-unknown-card-asks                                             -                                           3/3
wallet-edit-paid-with                                                          -                                           3/3
wallet-usual-card                                                              -                                           3/3
(1 cases passed every run in both files; --all shows them)

Passed overall: 20261103-044011-deepseek_deepseek-v4.1-flash 13/15, 20261103-044011-deepseek_deepseek-v4.1-flash 23/27
Rates differing by 2 or more out of N: 1
- wallet-card-bill: 3/3 vs 1/3, better in 20261103-044011-deepseek_deepseek-v4.1-flash
In only one file: wallet-paid-with-card, wallet-paid-with-unknown-card-asks, wallet-edit-paid-with, wallet-usual-card
```

(Again, the first column is main and the second is the branch.)

## Cases worse on the branch

### `wallet-card-bill`: a regression (main 1/1 + 3/3, branch 0/1 + 1/3)

"paid my credit card bill 1,240" should get an offer to log a move of 1,240 SGD from Spending to Card. In 3 of the branch's 4 runs it got "Which card was it — Card, Citi PremierMiles or DBS Altitude?" instead, with no tool call. Grading failed it on "didn't ask to confirm; expected moved 1240 SGD from Spending to Card".

The cause is the branch's seed (`src/nexus/evals/seed.py`). It adds two named cards, Citi PremierMiles and DBS Altitude, next to the generic `Card` wallet. With three cards, "my credit card bill" really is ambiguous. Either:
- the case should now expect the question (`asks=True`) or name the card, or
- the prompt/skill should pick a default card for the bill (e.g. the one with the bill, or the usual card).

That is a decision about intended behaviour. No code was changed here.

### `itinerary-gelato-after-the-castle`: likely noise (main 1/1 + 3/3, branch 0/1 + 2/3)

In the failing runs the model added the gelato stop without `day`, then fixed the day with `change_itinerary_entry`. The end state is right, but the check wants `day` on the `add_to_itinerary` call. The trips path isn't touched by the card work, and the passing branch runs look the same as main. 2 failures in 4 runs against 0 in 4 is still worth one more look if it keeps showing up.

### Not worse on the rechecks

- `trip-heading-there-no-parrot`: 2/3 on both. Replies over 220 characters while lookups were down. Flaky on both.
- `mem-short-replies`: branch 3/3, main 2/3. The full-run failure was a 170-odd-character spending summary. Flaky on both.

## Notes

- `log-two-at-once` failed only on main's full run: one 4.30 expense instead of 1.80 + 2.50. It passed on the branch. This looks like noise; it wasn't rechecked, since the brief covers branch failures only.
- Both full runs logged one "memory reply didn't parse; trying once more" traceback. Neither run had errors or model failures.
- `eval-results/photos/` (the runner's download cache of a third-party receipt photo) is not committed.
- Total spend: $0.3907 (full runs $0.3515 + rechecks $0.0392).
