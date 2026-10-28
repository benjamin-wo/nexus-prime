# Live evals: fix branch vs main (2026-10-28)

Flags on every run: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`

- Branch: `claude/adoring-lamport-4a97mv` @ `b70072e`
- Main: `origin/main` @ `5c8cbe3`
- Subset: `--case trip --case messy --case edit --case itinerary --case timezone --case log --repeat 3`
- Files: `eval-results/fix-branch/`, `eval-results/fix-main/`, `eval-results/fix-full/`. The raw compare output is in `eval-results/fix/compare.md`.

## Subset totals (3 rounds)

| | Cases | Passed | Per round | Flaky |
|---|---|---|---|---|
| Branch | 78 | 229/234 | 77, 75, 77 | trip-find-near-day, trip-heading-there-no-parrot, itinerary-label-days |
| Main | 77 | 228/231 | 75, 77, 76 | log-two-at-once, trip-find-in-stop, trip-heading-there-no-parrot |

## The five target cases

| Case | Branch | Main |
|---|---|---|
| trip-find-in-stop | 3/3 | 2/3 |
| messy-yen | 3/3 | 3/3 |
| edit-resplit-new-person | 3/3 | 3/3 |
| itinerary-gelato-after-the-castle | 3/3 | 3/3 |
| timezone-landed-tokyo | 3/3 | not on main (the case is new on the branch) |

## Where the branch is 2+ runs worse than main

- **itinerary-label-days: branch 1/3, main 3/3.** It also failed in the full run (below). In all three failures the model made **no tool calls** and offered to set Kyoto up as a new trip instead of labelling 15 Dec.

No other case differs by 2 or more. Smaller differences (1 run): log-two-at-once 3/3 vs 2/3, trip-find-near-day 2/3 vs 3/3, trip-find-in-stop 3/3 vs 2/3, trip-heading-there-no-parrot 1/3 vs 2/3 (branch vs main).

## Full set on the branch (1 round, no case filter)

- **Passed: 280/282 (99%)**
- Reply time per turn: **median 2.1s, p90 5.0s** (390 turns)
- Cost $1.46 in total. 0 errors, 0 model failures.

### Failing cases

**trip-set-aside**. Failures: no `update_trip` call with `set_aside` 400, and it didn't ask to confirm. (It passed 3/3 in the branch subset.)
- User: `put aside 400 each payday for the japan trip`
- Calls: `load_skill(bills)`, `load_skill(salary)`, `show_pay_schedule()`, `add_bill(name="Japan trip", amount="400", due_date="2026-10-23", repeats="monthly", counts_as_spending=false)`
- Reply: "Japan trip set: 400 every payday, first one Fri 23 Oct ✅ Want me to add it to the trip's budget so you can see what's set aside?"

**itinerary-label-days**. Failure: no `label_trip_day` call with day 2026-12-15 and label kyoto.
- User: `we're in Kyoto on 15 Dec`
- Calls: none
- Reply: "Kyoto on 15 Dec — noted. I'll keep your days on Singapore time until you're actually there. Want me to set it up as a trip, with dates and a budget?"

### Branch subset failures (for reference)

- itinerary-label-days, rounds 2 and 3: no calls. The replies were "Kyoto on 15 Dec — nice. Want me to set it up as a trip…" and "Got it — Kyoto on 15 Dec. Want me to set it up as a trip…"
- trip-find-near-day, round 2: it called `find_places(query="ramen", day="2026-12-12")` and `find_ideas(...)`. The case expects `day` to contain "3", but the model passed the resolved date. Reply: "Day 3 is Sat 12 Dec in Tokyo — but place search isn't available right now…"
- trip-heading-there-no-parrot, rounds 1 and 2: the reply was longer than 220 characters. The model explained at length that place lookups are unavailable and offered to add Osaka as a stop. The same failure also happens on main.

## Notes

- Place and web lookups are not configured in the eval environment, so the trip "find" replies all say search is unavailable. The scored tool-call checks still apply.
- The memory writer hit its 1,500-token output limit a few times in the branch subset (`LengthFinishReasonError`, followed by one retry). One turn was recorded as `memory_failed`. The full run had none.
