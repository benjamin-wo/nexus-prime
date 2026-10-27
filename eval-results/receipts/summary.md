# Receipts live evals

Flags on every run: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`

## Pass counts

| Run | Passed |
|---|---|
| Run 1 (photo + adv) | 23/23 |
| Run 2 (photo + adv) | 23/23 |
| Full (no filter) | 276/277 |

## Photo case turn times

p90 is linearly interpolated over every turn of the photo-* cases.

| Run | Photo turns | Median | p90 |
|---|---|---|---|
| Run 1 (photo + adv) | 16 | 5.1s | 13.2s |
| Run 2 (photo + adv) | 16 | 5.8s | 13.0s |
| Full (no filter) | 16 | 5.3s | 19.0s |
| All three runs | 48 | 5.8s | 15.5s |

## Photo cases over 30 s

- `photo-caption-date` — 37.8s (Run 1 (photo + adv))

## Failing cases

### `trip-find-in-stop` — Full (no filter)

- Area: ask
- Failures: no find_ideas call with {'stop': Has(text='kyoto')}

**Turn 1** (5.88s) — user: 'things to do in Kyoto for my japan trip'

Tool calls:
- `load_skill` {"name": "trips"}
- `list_trips` {}
- `find_ideas` {"query": "things to do in Kyoto"}
- `find_places` {"query": "things to do in Kyoto"}

Replies:
> Couldn't pull Kyoto ideas — the guides and Maps lookup aren't set up on my side right now, so I've got nothing real to give you rather than made-up names.
> 
> Your Japan trip is Tokyo, 10 to 18 Dec, with Ann. Want me to block out a couple of Kyoto days on it (say 13 to 14 Dec) so it's on the plan, and I can try the ideas search again later?


## Notes

- Runs 1 and 2 logged a vision-read `TimeoutError` in `nexus/agent/receipts.py` (READ_TIMEOUT) (the case was not identified in the console output); both runs still reported 0 errors and 23/23 passed. The full run logged none.
- Raw results: `eval-results/receipts-run1/`, `receipts-run2/`, `receipts-full/` (JSON + report.md per run).
