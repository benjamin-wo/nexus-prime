# DeepSeek v4.1 Flash on `:nitro` hosts (25 October 2026)

Production saw a garbled reply and a call to a tool that doesn't exist (`add_trip_placeholder`) from `deepseek/deepseek-v4.1-flash-1017:nitro` pinned to Together. Two setups were run once each on the full set (252 cases, 319 turns), with Qwen3.8 Flash reading photos and `--reasoning low`:

- **C:** `deepseek/deepseek-v4.1-flash:nitro`, OpenRouter choosing the host.
- **D:** `deepseek/deepseek-v4.1-flash-1017:nitro`, `--providers together`, the production setup that misbehaved.

| Run | Passed | Median | p90 | Slowest | Made-up tools | Empty replies | Cost a case |
|---|---|---|---|---|---|---|---|
| C: v4.1-flash:nitro, OpenRouter picks | 244/252 | 1.9s | 4.1s | 15.6s | **0** | **0** | about $0.0090* |
| D: v4.1-flash-1017:nitro, Together | 244/252 | 1.9s | 4.0s | **198s** | **3** | **2** | $0.0092 |

\* The runner prices by exact model id, and the `:nitro` ids aren't in OpenRouter's model list, so it reported "unknown". These are the recorded tokens (chat and memory writer) at the host's list price. Together charges $0.30/$1.20 per million tokens for both models. C's host isn't recorded. Its token count would come to $0.0011 a case on the cheapest v4.1-flash host and $0.018 on the dearest. The $0.0090 assumes a Together-tier price, which most fast hosts charge.

## Failures

**C (8):**

| Case | Why |
|---|---|
| `log-dollar-sign` | "$4.20 kopi" not logged as 4.20 SGD in Dining Out |
| `plan-bill-paid` | Rent bill not marked paid, and the 1800 payment not logged |
| `trip-place-reviews` | no `place_info` call for Ichiran; replied that search wasn't working |
| `itinerary-gelato-after-the-castle` | gelato not added after Kuroshiro on 12 Dec |
| `itinerary-label-days` | 15 Dec not labelled Kyoto |
| `multi-lunch-story` | 14 SGD Maxwell lunch not logged |
| `ctx-move-last` | moved Golden Village (24 Sep) to Transport instead of the latest, Kopitiam (28 Sep) |
| `ctx-long-pending` | 85 SGD Jumbo spend not logged at the end of a long conversation |

**D (8):**

| Case | Why |
|---|---|
| `log-dollar-sign` | as C |
| `trip-find-in-stop` | `find_ideas` not limited to the Kyoto stop |
| `trip-heading-there-no-parrot` | reply over 220 characters |
| `web-search-strikes-week` | empty model reply (no text, no tool call, 0 output tokens); the user got "Sorry, I didn't get that" |
| `itinerary-add-plan-no-time` | no `add_to_itinerary` activity for Kuroshiro on 12 Dec |
| `trip-split-costs` | no `split_trip_costs` call |
| `mem-changed-job` | reply didn't mention the new employer, Globex |
| `ctx-long-pending` | as C |

Only `log-dollar-sign` and `ctx-long-pending` failed in both runs. With one run each, the other differences are within the ±2 seen between repeat runs in earlier evals.

## Garbled text and made-up tools

Every reply in both runs was checked for non-Latin script, repeated 4-word fragments, words repeated three times in a row, and broken or run-together words. Every rare word was also reviewed by hand. **Neither run produced garbled text.** The only hits were real: the `messy-chinese` case, which is meant to get a Chinese reply, the name "teamLab", a split where three people each owe 30.00, and Barcelona names (Guàrdia Urbana, Mossos d'Esquadra).

Every tool call was checked against the 88 tools in `build_tools`. **C called none that don't exist. D called three:**

| Case | Made-up tool | What happened |
|---|---|---|
| `inv-plan` | `watch_watchlist` `{}` | sent alongside `research_plan`, `stock_levels` and `watch_stock`; passed |
| `follow-and-last-month` | `query_loan_placeholder` `{}` | sent before the right `query_ledger` call; passed |
| `ctx-move-last` | `find_ledger_placeholder` `{}` | sent before `find_transactions` and the right edit; passed |

Each was an empty-argument call at the start of a parallel batch, and the real call followed. So the cases passed, but this is the same `*_placeholder` naming as production's `add_trip_placeholder`.

D also returned two empty replies, so the user got "Sorry, I didn't get that. Could you say it another way?":

- `web-search-strikes-week` came back empty at once, and that case failed.
- `trip-settle-up` came back empty after **198s**. That case passed only because its checks look at the tool calls, not the reply.

C had no empty replies, and its slowest turn was 15.6s.

## Takeaway

On accuracy and typical speed the two are even: 244/252 each, median 1.9s, p90 about 4s. Only D showed the production problems: three calls to made-up `*_placeholder`-style tools, two empty replies, and one 198s stall. No garbled text appeared in either run, so the production garble wasn't reproduced. These are one run each, so the counts are small. Still, every made-up tool call and empty reply came from `-1017` on Together, which points to that model version or host rather than to `:nitro` routing in general.
