# Prompt cache branch vs main: full eval set (28 October 2026)

Branch `claude/evals-cache` / `claude/adoring-lamport-4a97mv` (9c58141, "Record cached input tokens end to end, and put the fixed system prompt first") against `origin/main` (b8dee64). One full run each with the production flags:
`--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low` (282 cases, 390 turns).

## Pass counts

| Run | Passed | Median reply | p90 | Tokens a case (in / out) | Reported cost |
|---|---|---|---|---|---|
| main | **280/282** | 2.2s | 4.8s | 36500 / 309 | $1.5217 total, $0.00540 a case |
| branch | **278/282** | 2.0s | 4.1s | 36252 / 339 | $0.2775 total, $0.00098 a case |

Errors 0 and model failures 0 in both. Both logs have a few tracebacks for model replies that hit the output limit (`LengthFinishReasonError`); the runner handled them, so none counted as an error.

## Compare (`compare cache-main/… cache-branch/…`; first column main, second branch)

```
case                               main  branch
q-compare-months                   1/1   0/1
cat-explain                        1/1   0/1
itinerary-gelato-after-the-castle  0/1   1/1
follow-repaid-in-full              0/1   1/1
mem-short-replies                  1/1   0/1
adv-invest                         1/1   0/1
(276 cases passed every run in both files)

Passed overall: main 280/282, branch 278/282
Rates differing by 2 or more out of N: 0
```

(Both result files have the same model in their names, so `compare` labels both columns `…-deepseek_deepseek-v4.1-flash`. The raw output is in `eval-results/cache-compare.txt`.)

## Recheck: the 4 cases that passed on main and failed on the branch, `--repeat 3` on both

| Case | main | branch |
|---|---|---|
| `q-compare-months` | 3/3 | 3/3 |
| `cat-explain` | 3/3 | **1/3** |
| `mem-short-replies` | 2/3 | 3/3 |
| `adv-invest` | 2/3 | 2/3 |
| Total | 10/12 | 9/12 |

`compare` flags one case: **`cat-explain`, 3/3 on main vs 1/3 on the branch**. Counting the full runs, that's 4/4 vs 1/4. In each branch failure the model never called `explain_category` ("no explain_category call with any arguments"). This looks like a real regression on the branch, not noise. One guess, not checked: moving the fixed system prompt first changed how the category-explaining instructions sit in the prompt.

The other three are noise: `q-compare-months` passed 3/3 on both, and `mem-short-replies` and `adv-invest` are flaky on main too. Raw output: `eval-results/cache-recheck-compare.txt`.

## Caching (branch report)

- **OpenRouter did report cached tokens.** 89.1% of the chat model's input tokens came from the provider's prompt cache: 32310 of 36252 a case, 9,111,552 of 10,223,159 overall. 367 of 390 turns had some cached input.
- Median input tokens per turn: **18,490** on the branch (18,411 on main).
- Estimated cost of each full run: **branch $0.2775** (cached tokens at the cached rate) and **main $1.5217**.

The cost gap mostly comes from how each version counts, not from the branch spending less. Main doesn't record cached tokens (its JSON shows 0 for every turn) and prices all input at the full rate. Its input token count is almost the same as the branch's (36,500 vs 36,252 a case). So main's calls were very likely being cached by the providers too, and main's $1.52 overstates its real cost. Priced like main, the branch would come to about $1.5. The branch's real gain is that cached tokens are now recorded and priced correctly. Whether putting the fixed system prompt first raises the cache hit rate can't be measured against main, because main records no cache figures.

## Files

- `eval-results/cache-branch/`, `eval-results/cache-main/`: full-run JSON and Markdown reports; `cache-*.log` are the console logs.
- `eval-results/cache-recheck-branch/`, `eval-results/cache-recheck-main/`: the `--repeat 3` rechecks.
- Not committed: `eval-results/photos/`, the runner's download cache of a receipt photo from a third-party site.
