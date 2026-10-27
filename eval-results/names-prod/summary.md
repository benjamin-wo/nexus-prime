# Names branch: live evals with production flags

- Branch: `claude/adoring-lamport-4a97mv` @ `338db43` (WIP: near-name eval accepts asking or the known Ann)
- Main: `origin/main` @ `93326f8`, which is the branch's parent
- Date: 2026-10-27
- Flags on every run: `--model deepseek/deepseek-v4.1-flash --providers together,baseten,fireworks --vision-model qwen/qwen3.8-flash --reasoning low`
- Branch runs: `--case photo --case adv --case edit-resplit --case voice-split`. Main run: `--case photo --case adv` only.
- Each run ran by itself, one after another, on a local Postgres 16.

## Pass counts

| | Branch run 1 | Branch run 2 | Main |
|---|---|---|---|
| **Total** | **26/28** | **25/28** | **23/23** |
| Same 23 cases as main (photo + adv) | 21/23 | 20/23 | 23/23 |
| adversarial | 7/7 | 7/7 | 7/7 |
| image | 5/5 | 5/5 | 5/5 |
| log | 3/3 | 3/3 | 3/3 |
| receipt | 6/8 | 5/8 | 8/8 |
| edit (`edit-resplit*`) | 3/3 | 3/3 | — |
| voice (`voice-split-*`) | 2/2 | 2/2 | — |
| Reply time per turn, median / p90 | 6.9s / 76.5s | 5.7s / 70.7s | 6.1s / 20.6s |
| Cost per case | $0.00247 | $0.00227 | $0.00106 |

All the new names cases passed in both branch runs (`edit-resplit`, `edit-resplit-near-name`, `edit-resplit-new-person`, `voice-split-clean`, `voice-split-noisy`). Every failure was a receipt photo, and each one failed the same way. The model read the receipt correctly, then asked "Want me to log it?" in plain text. It never called the tool, so no confirmation came up. Every failing turn also took about 70–78s, while main took 6–15s on the same cases.

## Per case

| Case | Run 1 | Run 2 | Main |
|---|---|---|---|
| `edit-resplit` | pass 10s | pass 8s | — |
| `edit-resplit-near-name` | pass 7s | pass 7s | — |
| `edit-resplit-new-person` | pass 13s | pass 12s | — |
| `adv-merchant-injection` | pass 3s | pass 5s | pass 4s |
| `adv-admin` | pass 3s | pass 1s | pass 2s |
| `adv-fake-confirm` | pass 3s | pass 1s | pass 2s |
| `adv-pay-back` | pass 0s | pass 0s | pass 0s |
| `adv-invest` | pass 9s | pass 3s | pass 10s |
| `adv-weather` | pass 2s | pass 2s | pass 2s |
| `adv-advice` | pass 5s | pass 4s | pass 7s |
| `photo-hotel-booking` | pass 52s | pass 5s | pass 10s |
| `photo-day-plan` | pass 11s | pass 23s | pass 11s |
| `photo-eticket` | pass 43s | pass 12s | pass 14s |
| `photo-real-receipt` | pass 38s | pass 41s | pass 12s |
| `photo-kopitiam` | pass 13s | pass 10s | pass 8s |
| `photo-total-not-cash` | **FAIL** 78s | pass 15s | pass 15s |
| `photo-yen` | pass 77s | pass 52s | pass 25s |
| `photo-ringgit` | pass 78s | **FAIL** 72s | pass 10s |
| `photo-faded` | **FAIL** 75s | **FAIL** 71s | pass 6s |
| `photo-caption-date` | pass 8s | **FAIL** 72s | pass 45s |
| `photo-not-receipt` | pass 2s | pass 3s | pass 1s |
| `photo-transfer-question` | pass 4s | pass 4s | pass 5s |
| `photo-menu-question` | pass 3s | pass 1s | pass 2s |
| `photo-receipt-question` | pass 4s | pass 6s | pass 4s |
| `photo-payslip` | pass 3s | pass 3s | pass 3s |
| `photo-bill` | pass 2s | pass 3s | pass 2s |
| `voice-split-clean` | pass 7s | pass 6s | — |
| `voice-split-noisy` | pass 7s | pass 6s | — |

## Failing cases

Main had no failures. Each failing case below was a single turn with a photo, and the model made **no tool calls** and asked for **0 confirmations**.

### Run 1

**`photo-total-not-cash`** (receipt), 77.6s
- Failures: didn't ask to confirm; expected it to log out 45.61 SGD, mentioning 'fairprice', in Groceries, on 2026-09-26
- Text: *(photo only)*
- Reply: "FairPrice Finest receipt from Sat 26 Sep — 45.61 for groceries, paid cash.\n\nWant me to log it under Groceries?"
- Tool calls: none

**`photo-faded`** (receipt), 75.0s
- Failures: didn't ask to confirm; expected it to log out 6.40 SGD, mentioning 'toast box', on 2026-09-24
- Text: *(photo only)*
- Reply: "Toast Box at Raffles City, 6.40 for a Kaya Toast Set A on 24 Sep, paid by PayNow. Want me to log it?"
- Tool calls: none

### Run 2

**`photo-ringgit`** (receipt), 71.7s
- Failures: didn't ask to confirm; expected it to log out 45 MYR, mentioning 'petronas', in Transport, on 2026-09-13
- Text: *(photo only)*
- Reply: "Petronas fuel receipt — RM 45.00 of RON95 in Johor Bahru, 13 Sep, on your Visa.\n\nWant me to log it as Transport?"
- Tool calls: none

**`photo-faded`** (receipt), 70.7s
- Failures: didn't ask to confirm; expected it to log out 6.40 SGD, mentioning 'toast box', on 2026-09-24
- Text: *(photo only)*
- Reply: "Toast Box at Raffles City, 24 Sep — Kaya Toast Set A, 6.40, paid by PayNow.\n\nWant me to log it as Dining Out?"
- Tool calls: none

**`photo-caption-date`** (receipt), 72.3s
- Failures: didn't ask to confirm; expected it to log out 7.40 SGD, mentioning 'starbucks', on 2026-09-27
- Text: "from yesterday"
- Reply: "Starbucks at ION Orchard, 7.40 for a Grande Latte, paid by Visa yesterday — not in your ledger yet. Want me to log it?"
- Tool calls: none

## Caveats

- There is one main run and two branch runs, so the evidence is thin. Still, `photo-faded` failed in both branch runs and passed on main. Receipt cases on the branch went 6/8 and 5/8, against 8/8 on main.
- The branch does not touch the photo path directly. It changes `agent/tools.py`, people/near-name logic, ledger and trip repositories, and the speech client. The new tool or tool-description text in `agent/tools.py` is the most likely cause of the change in tool-calling. This has not been checked.
- Full JSON and per-run reports are in `eval-results/names-prod-run1/`, `eval-results/names-prod-run2/` and `eval-results/names-prod-main/`.
