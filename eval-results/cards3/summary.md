# cards3: itinerary eval, branch vs main (3 November 2026)

Flags: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low --case itinerary- --repeat 6`

- Branch `claude/evals-cards3`: `eval-results/cards3-branch/20261103-053136-*`
- Main (`origin/main` at `553c1a0`): `eval-results/cards3-main/20261103-053139-*`

Both ran at the same time against a local Postgres 16. 0 errors and 0 model failures on either side.

## Pass rates by case

| Case | Main | Branch |
|---|---|---|
| itinerary-add-plan | 6/6 | 6/6 |
| itinerary-add-plan-with-cost | 6/6 | 6/6 |
| itinerary-add-plan-no-time | 6/6 | 6/6 |
| itinerary-add-plan-no-venue | 6/6 | 6/6 |
| itinerary-gelato-after-the-castle | 5/6 | 6/6 |
| itinerary-change-hotel | 6/6 | 6/6 |
| itinerary-change-length | 6/6 | 6/6 |
| itinerary-hotel-whole-trip | 6/6 | 6/6 |
| itinerary-place-to-visit | 6/6 | 6/6 |
| itinerary-label-days | 6/6 | 6/6 |
| **Total** | **59/60** | **60/60** |

| | Main | Branch |
|---|---|---|
| Median / p90 reply | 3.0s / 4.0s | 3.1s / 4.0s |
| Cost a case | $0.00097 | $0.00098 |

## Compare output

```
$ uv run python -m nexus.evals compare eval-results/cards3-main/20261103-053139-deepseek_deepseek-v4.1-flash.json eval-results/cards3-branch/20261103-053136-deepseek_deepseek-v4.1-flash.json
Case                               20261103-053139-deepseek_deepseek-v4.1-flash  20261103-053136-deepseek_deepseek-v4.1-flash
itinerary-gelato-after-the-castle                                           5/6                                           6/6
(9 cases passed every run in both files; --all shows them)

Passed overall: 20261103-053139-deepseek_deepseek-v4.1-flash 59/60, 20261103-053136-deepseek_deepseek-v4.1-flash 60/60
Rates differing by 2 or more out of N: 0
```

## itinerary-gelato-after-the-castle failures

**Branch:** none, 6/6.

**Main:** 1 failure (round 3 of 6):

> no add_to_itinerary call with {'name': Has(text='gelato'), 'after': Has(text='castle'), 'day': Has(text='2026-12-12')}

Turn 1 ("add Kuroshiro Castle to the 12th of my Japan trip") went fine. On turn 2 ("add a gelato stop after the castle") the model called `find_places(query="gelato", day="12")`, then `add_to_itinerary(name="Gelato stop", after="Kuroshiro Castle", ...)` **without `day`** (and with `place: "Tokyo"`). After that it repaired things with `change_itinerary_entry(day="2026-12-12", after="Kuroshiro Castle")`, `trip_status`, and `change_itinerary_entry(time="10:30", minutes=20)`. The reply said "Gelato stop is right after the castle, 10:30–10:50 ✅". So the result may well have been right in the end, but the grader looks for `day` on the `add_to_itinerary` call itself, and it wasn't there.

## Reading

The difference is 1 out of 6, under the 2-of-N threshold, so the compare flags nothing. On this sample the branch is level with main: no regression, and nothing here shows an improvement either.
