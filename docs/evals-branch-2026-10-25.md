# Evals: branch `claude/adoring-lamport-4a97mv`, 2026-10-25

Live runs of the branch at `24610a8` with the production model pairing:

```
--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks \
--vision-model qwen/qwen3.8-flash --reasoning low
```

Local Postgres 16. The eval user `nexus` (CREATEDB) can't create roles, so migration 0056 failed until `nexus_app` was made beforehand and granted to `nexus` WITH ADMIN OPTION. Production migrates as a superuser, so this affects local setup only. No code was changed.

Baseline (main, same setup, today): 246/251 and 248/251, median 1.7–1.8s.

## Full set (258 cases; the branch adds 7)

| Run | Passed | Median | p90 | Slowest turn | Cost a case |
|---|---|---|---|---|---|
| 1 | **256/258** | 1.8s | 3.5s | 42.2s (`photo-day-plan`) | $0.00114 |
| 2 | **256/258** | 1.9s | 3.6s | 21.4s (`photo-ringgit`) | $0.00115 |

No errors and no model failures in either run. The slowest turns were the photo (vision) cases.

Failures:

- Run 1, `web-search-protest-now`: it never called `web_search` and replied that "the news search isn't working on my end right now".
- Run 1, `itinerary-label-days`: no `label_trip_day` call. It said "Noted — Kyoto on 15 Dec" and offered to set up a trip instead.
- Run 2, `cat-explain`: the reply lacked the Grab 42.10 entry ("It's in Transport because that's the category it was given… Want me to move it somewhere else?"). It passed 3/3 in the targeted runs.
- Run 2, `wallet-find-likely-moves`: no `find_likely_moves` call. It answered from the ledger alone ("nothing in your ledger looks like a transfer").

Each failure happened once, and none repeated across the two runs.

## Targeted cases (3 runs each)

Run totals: 11/12, 12/12, 11/12. Median 1.6s in all three, p90 2.4–3.1s.

| Case | Passes |
|---|---|
| mem-split-habit | 3/3 |
| mem-split-habit-mum | 3/3 |
| mem-split-habit-treat | 3/3 |
| mem-split-habit-other-category | 3/3 |
| ctx-long-pending | 3/3 |
| ctx-open-not-nagging | **1/3** |
| ctx-open-resolved | 3/3 |
| plan-bill-paid | 3/3 |
| plan-bill-paid-other-amount | 3/3 |
| log-dollar-sign | 3/3 |
| ask-which-kopitiam | 3/3 |
| cat-explain | 3/3 |

`ctx-open-not-nagging` failed in runs 1 and 3 because the reply brings up tonight's Jumbo dinner again. The check is `\bjumbo\b[^.!?\n]*\b(?:tonight|last night|exact|still)\b`.

- Run 1: "Dining Out: 143.90 of 300.00 used (47%), 156.10 left. Comfortable — and Jumbo tonight will eat into it."
- Run 3: "Dining Out: 143.90 of 300.00 used (47%), 156.10 left.\n\nJumbo tonight (~80) would take you to about 224 — still comfortably inside."

This is the one regression worth looking at. The earlier open item still leaks into an unrelated budget answer.

## Tone: split-habit and bill cases

Every reply below comes from 5 samples per case: 3 targeted runs plus the 2 full runs. None asked a needless confirmation question (0 confirmations, no trailing "?"), and every one made the right tool call.

**Templated / identical phrasing**

- The split-habit setup turn was word for word the same in 13 of 15 samples: "Saved — dinners with Ann will split 50/50 from now on." The other 2 said "Saved — Dining Out with Ann splits 50/50 from now on." The groceries version is close to fixed as well: "Got it — groceries with Ann split 50/50 from now on." (4 of 5).
- `mem-split-habit` second turn, identical in 5 of 5: "Logged 60.00 at Din Tai Fung ✅ Split with Ann — she owes 30.00." (the full runs add a budget line).
- The log replies all use one stem: "Logged 60.00 at X ✅ Dining Out's now 203.90 of 300 this month." It reads consistent rather than wrong, but it is clearly a template.
- `plan-bill-paid`, identical in 2 of 5: "Rent marked paid ✅ Logged 1800.00 SGD — that's your biggest one this month by far." A third sample swaps one word ("biggest hit").

**Robotic or odd wording**

- `plan-bill-paid-other-amount`, tgt2: "Logged Rent 1,850.00 SGD ✅ (bill marked paid, nothing moved by me)." The bracket explains the system's internals, which the user didn't ask about.
- `plan-bill-paid-other-amount`, full1: "(the bill had 1,800, so I used your figure)". This is fine but mechanical.
- Number formatting is inconsistent across samples: "1800.00 SGD" vs "1,800.00 SGD", and "Rent" vs "rent".
- `mem-split-habit-treat`, tgt1: "Logged 80.00 at Paradise, Dining Out, no split ✅" reads like a list of fields.
