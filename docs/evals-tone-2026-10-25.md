# Evals: reply tone, 2026-10-25

`claude/adoring-lamport-4a97mv` (129bce3, "Replies that don't all sound the same") against
`main` (ba7981e). The full set (258 cases) ran twice on the branch and once on main.

Flags for every run: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks
--vision-model qwen/qwen3.8-flash --reasoning low`. Postgres 16, run on 2026-10-25.

## Results

| Run | Passed | Median | p90 | Cost a case |
|---|---|---|---|---|
| main | 254/258 (98%) | 1.9s | 4.2s | $0.00112 |
| branch, run 1 | 253/258 (98%) | 1.9s | 3.9s | $0.00114 |
| branch, run 2 | 256/258 (99%) | 1.8s | 3.9s | $0.00117 |

There were no errors and no model failures in any run. Output tokens per case went from 296 on
main to 305 and 343 on the branch, so each case costs about 2–4% more.

### Failures

**main**
- `trip-find-in-stop`: the ideas search was down, and it made no `find_ideas` call with stop "kyoto".
- `wallet-find-likely-moves`: it used `find_transactions`/`query_ledger` and never called `find_likely_moves`.
- `mem-employer`: it replied "Noted — ACME's your salary source." to "my salary comes from acme", and the case requires a quiet save. The recall in the next session is correct.
- `calc-converted`: it couldn't get an FX rate and gave no SGD figure.

**branch, run 1**
- `web-search-protest-now`: its `web_search` call had no `recent: today` or local query.
- `trip-set-aside`: it called `add_bill` instead of `update_trip(set_aside=400)`, without confirming.
- `follow-repaid-in-full`: it asked "The full 40, or part of it?" when it should have recorded 40 repaid.
- `mem-employer`: same as main.
- `ctx-next-day-words`: it said "tomorrow's Kamakura day" in a reply that must not use "tomorrow".

**branch, run 2**
- `trip-find-in-stop`: same as main.
- `mem-employer`: same as main.

`mem-employer` fails in all three runs and `trip-find-in-stop` in two of them. The four failures
seen only on branch run 1 didn't come back in run 2. They read as model variance rather than
the tone change, but `trip-set-aside` (wrong tool) is worth watching.

## Openers after a change

These are the last replies of turns that made a write call, grouped by their first two
non-numeric words. Main's runner has no opener stat, so main's figures were worked out from its
results JSON with the branch's `opener()`/`openers()`. The same script gives exactly the numbers
the branch's runner reports for both branch runs.

| Run | Replies | Top 3 |
|---|---|---|
| main | 121 | "logged for" 16%, "logged at" 15%, "logged sgd" 6% |
| branch, run 1 | 121 | "grab transport's" 3%, "dining out" 3%, "at maxwell" 2% |
| branch, run 2 | 123 | "dining out" 3%, "grab transport's" 2%, "at maxwell" 2% |

On main, 37% of replies after a change start with "Logged …". On the branch, no opener goes
above 3%.

## Side by side

Branch run 1 is quoted. Run 2 gave the same reply unless noted.

**Log: "grab 12"**
- main: "Logged 12.00 for Grab ✅ Transport's at 108.30 this month."
- branch: "Grab 12.00 ✅ Transport's at 108.30 this month."

**Log: "lunch at maxwell 8.40"**
- main: "Logged 8.40 at Maxwell Food Centre ✅ Dining Out's at 152.30 of 300 this month."
- branch: "8.40 at Maxwell ✅ Dining's at 152.30 of 300 this month."

**Log: "1.8k for a new laptop"**
- main: "Logged 1,800.00 for the new laptop ✅ (Shopping) — That's a big one — want me to set a Shopping budget so the rest of the month doesn't creep?"
- branch: "1,800 for the laptop ✅ Shopping."

**Split habit set: "i always split dinners with ann 50/50"**
- main: "Saved — dinners with Ann will split 50/50 from now on."
- branch: "Done — dinners with Ann will split 50/50 from now on."

**Split habit set: "i always split groceries with ann 50/50"**
- main: "Saved — groceries with Ann now split 50/50 as you log them."
- branch: "Noted — groceries with Ann split 50/50 from now on."
- branch run 2: "Groceries with Ann, 50/50 — saved. New grocery expenses will split automatically."

**Split applied: "dinner 60 at din tai fung" (habit set earlier)**
- main: "Logged 60.00 at Din Tai Fung ✅ Split with Ann — she owes 30.00. Dining Out's now 203.90 of 300 this month."
- branch: "60 at Din Tai Fung ✅ Ann owes you 30 for it. Dining's at 203.90 of 300 this month."

**Split applied: "paid 30 for dinner, ann owes me half"**
- main: "Logged 30.00 for dinner ✅ Ann owes you 15.00, your share 15.00."
- branch: "Dinner's in at 30, and Ann owes you 15 for it ✅"

**Bill paid: "i paid the rent"**
- main: "Rent's marked paid and logged — 1800.00 SGD ✅ (a few days ahead of the 1 Oct due date, so that's September's spending)."
- branch: "Rent's sorted ✅ 1,800 logged, and that's October's rent off your mind."
- branch run 2: "Rent's sorted ✅ 1,800 logged, and the 1 Oct reminder's cleared."

**Bill paid: "rent was 1,850 this month, paid it"**
- main: "Logged Rent at 1,850.00 SGD ✅ (the bill was set at 1,800, so I've used your figure)."
- branch: "Rent's done ✅ 1,850 logged."

**Budget question: "how's my dining out budget looking"**
- main: "Dining Out: 143.90 of 300.00 used, 156.10 left ✅ That's 47% through the month with a few days to go — comfortably on track."
- branch: "Dining's at 143.90 of 300 — 47% used, 156.10 left. Comfortable for the rest of the month."

## Things to look at on the branch

**"1800.00"-style amounts.** In model-written replies these go from 25 on main to 1 in each
branch run:
- run 1, `ctx-long-recall`: "Rent 1800.00, due Thu 1 Oct — that's the one this week. Singtel 45.00 isn't until 28 Oct."
- run 2, `ctx-before-payday`: "• Rent 1800.00 — Thu 1 Oct, in 3 days"

Other 4-digit `.00` amounts show up only in app-built text, which is the same on main:
confirmation cards (`Log a move of 1240.00 SGD…`, `Make 5200.00 SGD your usual salary?`,
`Add a trip: … budget 1500.00 SGD`) and `Recorded 5000.00 SGD salary.` They come from
`agent/tools.py` and `application/income.py`, so prompt changes can't fix them.

**App internals.** No reply names a tool, field or database. Smaller points:
- run 2, `mem-split-habit-other-category`: "New grocery expenses will split automatically." This is mild, but it describes how the app works.
- run 2, `trip-left`: "(JPY spending on those days counts automatically)". This is the same kind of thing.
- Tool outages are explained in plain terms ("the news search isn't working on my end", "Place lookups aren't working"). Main does the same.

**Robotic.** Nothing reads as templated in the old sense, and short acknowledgements like
"Done —", "Noted —" and "Saved —" stay natural. Side effects of the shorter style:
- **Category names get shortened.** "Dining Out" becomes "Dining" in 24 replies in run 1 and 21 in run 2. Main does this 0 times. "Maxwell Food Centre" also becomes "Maxwell". Users might not recognise their own category.
- **Useful detail gets dropped.** The laptop reply loses main's budget suggestion. The rent-at-1,850 reply no longer says the bill was set at 1,800.
- **One factual shift.** Run 1 calls the rent paid before 1 Oct "October's rent". Main called it September's spending. Both are defensible, but the two disagree.
