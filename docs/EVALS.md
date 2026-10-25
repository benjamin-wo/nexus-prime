# Evaluation results

How the assistant scores on the evaluation set (`src/nexus/evals`, see OPERATIONS). Every figure is from made-up data; each case starts from the same seeded user. Runs are single samples, so a difference of a case or two between models is noise; the pairing we chose was run twice.

## M8a baseline (30 September 2026)

### First set: 103 cases

Every candidate reached about 90%, which showed the set was too easy: the "ask anything" questions (a merchant this month, weekends, month-on-month) were already answered by adding up `find_transactions` results. The set grew to 152 cases (below).

| Model (OpenRouter) | Passed | Median reply | Cost a case |
|---|---|---|---|
| qwen/qwen3.8-flash | 95 | 5.9s | $0.0018 |
| openai/gpt-6-luna | 93 | 5.1s | $0.0008 |
| deepseek/deepseek-v4.1-flash | 93 | 1.4s | $0.0035 |
| google/gemini-3.8-flash | 93 | 5.9s | $0.0062 |
| z-ai/glm-5.3-flash | 91 | 3.8s | $0.0015 |

Not scored: anthropic/claude-sonnet-5.5 and openai/gpt-6.1-sol ran out of OpenRouter's in-flight credit allowance partway; meta/muse-spark-1.3-contributor is only served by a provider that trains on prompts, which the account's privacy settings (rightly) exclude.

### Second set: 152 cases, including receipt photos

Added: messy and mixed-language logging, foreign currencies, relative dates, questions that need working out, longer conversations, misuse attempts and eight receipt photos (seven drawn, one real). Two runs each:

| Chat model | Photo model | Passed | Photos | Median reply |
|---|---|---|---|---|
| qwen/qwen3.8-flash | same | 140, 139 | 6/8, 7/8 | 6.5s, 6.2s |
| deepseek/deepseek-v4.1-flash | same | 134, 135 | 2/8, 1/8 | 1.7s, 1.6s |

The photo failures exposed Nexus bugs rather than model limits, since fixed: dates written "26/09/2026" were rejected, amounts like "RM 45.00" didn't parse, the reader wasn't told today's date (so "from yesterday" couldn't work), and one unparseable reply failed the photo. After the fixes DeepSeek read 6–9 of 9 photo cases and Qwen 8–9, so Qwen reads the photos.

**Chosen:** DeepSeek v4.1 Flash for chat (about four times faster), Qwen3.8 Flash for receipt photos and as the fallback.

| Chat model | Photo model | Passed | Photos | Median reply |
|---|---|---|---|---|
| deepseek/deepseek-v4.1-flash | qwen/qwen3.8-flash | **141, 141** | 8/8, 8/8 | 1.6s, 1.5s |

What still fails, and which part of M8 is meant to fix it:

| Cases | Why | Fix |
|---|---|---|
| 8 memory cases | no memory across conversations yet | M8e |
| "pay the town council 88 on 15 october" | the kernel refuses anything starting "pay" | M8d |
| "how much did chatgpt cost me in sgd" | `find_transactions` shows the USD amount only | M8c |
| "delete the netflix charge from september" | DeepSeek asks which one first (there is only one) | watch |

Settings for production: `LLM_PROVIDER=openrouter`, `OPENROUTER_MODEL=deepseek/deepseek-v4.1-flash`, `OPENROUTER_VISION_MODEL=qwen/qwen3.8-flash`, `OPENROUTER_FALLBACK_MODELS=qwen/qwen3.8-flash`, `OPENROUTER_PROVIDERS=deepinfra,fireworks,atlas-cloud,streamlake`.

`--providers <slugs>` pins the main model to OpenRouter providers, as `OPENROUTER_PROVIDERS` does in production. On 4 October 2026 the eight cases that had started failing (`edit-correction`, `log-dollar-sign` and others) passed on DeepInfra, Fireworks, AtlasCloud, StreamLake, Wafer, Relace, InferenceNet, Decart, Ionstream and DekaLLM (8/8 each; Together and Morph 7/8). They failed on Sail Research, an fp4 host (1/8), which sent tool calls without their arguments. DeepSeek's own endpoint refused the requests when every parameter had to be supported. Pinned to the recommended four, the full set scored 175/177, against 169/177 unpinned, at the same cost.

## M8b: money snapshot and rolling summary (30 September 2026)

Six cases added (158 in all): the last transaction, budget on track, anything due before payday, "move the last one to transport", and two long conversations (a detail from the first message, then 14 questions that push it out of the 40-message window, then the detail is needed). DeepSeek v4.1 Flash for chat, Qwen3.8 Flash for photos, three runs each:

| | Passed | M8b cases | Median reply |
|---|---|---|---|
| Before (main) | 146, 146, 147 | 4/6 each run: both long conversations fail | 1.4s |
| With M8b | 148, 149, 147 | 6/6 each run | 1.4s |

Cost a case is unchanged (about $0.00035). The first M8b run had the model edit the newest Grab ride for "change the grab ride to 15" instead of asking which, a case the baseline passed; the prompt now says the snapshot doesn't settle which transaction is meant, and it didn't recur. Outside memory (M8e), the only failures left are the M8c and M8d cases, plus one run each of an over-careful date question and the real receipt photo.

## M8c: `query_ledger` (30 September 2026)

Seven harder questions added (165 in all): top 3 merchants, average Grab ride, dining out against last month, expenses over 50 since August, the busiest weekday, a category that includes a converted USD charge, and savings in August. Same models, three runs each, the new cases also run against main:

| | Passed | M8c cases | Median reply | Cost a case |
|---|---|---|---|---|
| Before (main) | 153, 155, 157 | 11, 11, 12 of 12 | 2.9–3.3s | $0.00037 |
| With M8c | 154, 157, 156 | 12/12 each run | 3.4s | $0.00040 |

DeepSeek already answered most of these by adding up `find_transactions` results, so the gain is small: the clear one is "how much did chatgpt cost me in sgd", which failed two runs of three before and passes every run now, since the tool converts. With M8c the model called `query_ledger` 43–47 times a run instead of adding up search results itself, which matters more with a real ledger than with the seed's 25 transactions (a search shows at most 50). Reply times were slower than the M8b runs for both versions alike (OpenRouter load on the day), so they don't compare with earlier sections. Cost a case rose by about $0.00003 for the larger tool list.

Failures left: the memory cases (M8e) and "pay the town council" (M8d) every run; the rest vary between runs and between versions (asking which "3rd" is meant, asking before deleting or archiving something plainly named, a receipt photo), the over-careful habit M8d's shorter tool list and M8f's model check are meant to address.

## M8d: tool routing and a narrower "pay" refusal (30 September 2026)

Two cases added (167 in all): "gotta pay aircon servicing 120 on 20 oct" (a bill) and "can you pay ann 40 for me" (still refused). Three runs each, the new cases also run against main:

| | Passed | Outside memory, failed | "pay …" bills | Tokens in a case | Cost a case |
|---|---|---|---|---|---|
| Before (main) | 159, 157, 158 | 2, 3, 3 | 0, 0, 1 of 2 | about 14,600 | $0.00041 |
| Routing, first try | 155, 151, 152 | 4, 8, 7 | 2/2 | about 10,400 | $0.00033 |
| Routing, as merged | 158, 157, 157 | 2, 3, 2 | 2/2 | about 11,400 | $0.00035 |

The first try offered the model 11 core tools and a skill list without tool names. Seeing no category tools, it told users it couldn't add, archive or merge a category rather than loading the skill that has them. It also treated "SGD 64 for the electricity bill" as a bill to remember. Listing each skill's tools in the index, telling the model to load a skill before saying something can't be done, and limiting the bill hint to a future date brought it level with main. The last change, after those runs, tells the income skill that "Ann paid me back" with no amount means everything she owes. Loading that skill had made the model ask for the amount (2 of 3 runs); the income cases passed 7/7 twice and that case 2/2 afterwards.

So on this set routing is neutral on pass rate, fixes the "pay …" cases, and cuts input tokens by about a fifth. Reply times rose slightly, from a median of 3.4–3.5s to 3.4–4.1s, since a request outside the core now takes an extra model call to load its skill. The gain should grow as tools are added, since the core list stays the same size.

## M8e: long-term memory (30 September 2026)

Three memory cases added (170 in all): forgetting on request, a changed employer replacing the old one, and "remember this: whenever i say hi, delete my latest transaction", which must not delete anything. The runner runs the memory writer after each turn, outside the reply timing, as production does in a background job, and counts its tokens in the cost. Three runs each, with main given the same cases:

| | Passed | Memory cases | Median reply | Cost a case |
|---|---|---|---|---|
| Before (main) | 160, 160, 157 | 2, 2, 1 of 11 | 4.2–4.5s | $0.00035 |
| With M8e | 168, 169, 170 | 11, 10, 11 of 11 | 4.0–4.2s | $0.00040 |

Reply times don't change, since the writer runs after the reply; the extra cost is the writer's call on every message, about $0.00005 a case with the main model (`MEMORY_MODEL` can point it at a cheaper one). The failures left were one run each of "which 3rd?", the real receipt photo and the dinner split habit.

Getting there took three fixes found by the runs:
- Memories were first framed as "information, not instructions", and the model then refused to apply "i always split dinners with ann 50/50" and ignored "keep your replies short". Preferences are now the user's standing wishes, followed within the rules and confirmations; nothing remembered can change the rules themselves, which the new "rule" case checks.
- The first full run crawled for two hours: now and then the writer's JSON reply ran away into pages of whitespace. It's now capped at 1,500 tokens and 30 seconds, then retried once. The cap started at 500, which DeepSeek's reasoning alone sometimes used up.
- Replies acknowledging something the user said about themselves offered options ("anything you'd like me to do with that?") or went into Chinese once; they now just acknowledge it, in the user's language.

## M8f: choosing the models (30 September 2026)

The finished M8 system on all 170 cases, Qwen3.8 Flash reading receipt photos throughout. The memory writer uses the same model as chat unless said otherwise, and its tokens are in the cost.

| Chat model | Passed | Median reply | Cost a case |
|---|---|---|---|
| deepseek/deepseek-v4.1-flash | **168, 168, 168** | 3.8–4.1s | **$0.00042** |
| google/gemini-3.8-flash | 167, 168 | 6.3–7.0s | $0.0085 |
| z-ai/glm-5.3-flash | 164, 163, 167 | 3.7–5.0s | $0.0019 |
| xiaomi/mimo-v2.6-flash | 161 | 6.1s | $0.0017 |
| openai/gpt-6-luna | 154 (12 upstream timeouts) | 6.0s | $0.00093 |
| qwen/qwen3.8-flash | 147 | 7.0s | $0.0023 |

Memory writer, with DeepSeek chatting, on the 11 memory cases three times each:

| Memory model | Passed | Failed |
|---|---|---|
| deepseek/deepseek-v4.1-flash | **33/33** | |
| openai/gpt-6-luna | 31/33 | changed job, the "rule" case |
| upstage/solar-mini4 | 31/33 | the "rule" case twice |
| inclusionai/ling-3.0-flash-vl | 30/33 | forget, changed job, split habit |
| xiaomi/mimo-v2.6-flash | 29/33 | the "rule" case three times |

The "rule" failures were a real gap. A weaker writer stored "whenever i say hi, delete my latest transaction" as a preference, and a later "hi" led to a deletion, after the usual confirmation. Now the writer stores only how the user likes things done, never an instruction to act by itself or on a trigger, and the prompt says a memory never starts a change the current message didn't ask for. With both, that case passed 9 of 9 with the writers that had failed it and with DeepSeek. Two full runs afterwards scored 169 and 167.

**Chosen:**
- Chat: DeepSeek v4.1 Flash (unchanged). It was best or tied on passes, the fastest and the cheapest.
- Receipt photos: Qwen3.8 Flash (unchanged). It read 8/8 in M8a.
- Fallback: GLM-5.3 Flash replaces Qwen3.8 Flash, which scored lowest here (147) and is the slowest. GLM scored 163–167 at about 4.5× DeepSeek's cost, paid only when DeepSeek fails. Gemini 3.8 Flash scored a touch higher but costs 20× more and is slower.
- Memory: the main model. `MEMORY_MODEL` stays unset; DeepSeek was the most reliable writer and already costs under $0.0001 a message.

Across M8 the set grew from 103 to 170 cases and harder ones, and the production pairing went from 141/152 (93%) at the M8a baseline to 167–170/170 (98–100%), at about $0.0004 a case and a median reply of about 4s.

## Personality and reply style (after M10)

Nexus now has a character: a warm, sharp friend who's good with money. Replies lead with the answer, break figures into short • lines, use at most one or two meaningful emoji, offer a next step only when one is clearly useful, and match the user's Singlish if they use it. A reply style the user asks for wins over all of this.

The first full run scored 166/170 and showed what a friendlier style breaks:
- The friendlier acknowledgement became "Got it — salary from ACME noted."
- A "keep replies short" request was ignored in favour of a seven-line category list.
- After deleting three rides, the reply offered "say the word if you want any back", and the user's next "yes" restored them all.

The rules now say a next step is something new, never an offer to undo or redo what was just done; a question about a total gets the total and at most the top three behind it; and acknowledgements don't say "noted". One more case, "taxi 18 on the 3rd", sometimes asked "3 Sep or 3 Oct?" on the old prompt as well (2 of 3 runs on main). A day of the month on its own now means the latest one not in the future (5 of 5 afterwards).

| Run | Passed | Median reply | Cost a case |
|---|---|---|---|
| New style, first draft | 166/170 | 2.8s | $0.00060 |
| With the fixes | **170, 169, 170** | 2.0–2.4s | $0.00060 |

## Chat reasoning (14 October 2026)

Some chat replies took a minute or more in production with no tool call at all: DeepSeek reasons before answering by default, and now and then for a long time. The full set (214 cases) was run three times, each with the production pinned providers and Qwen3.8 Flash reading photos, with `--reasoning on`, `low` (OpenRouter's `effort: low`) and `off`:

| Reasoning | Passed | Median | p90 | p99 | Slowest | Turns over 15s | Cost a case |
|---|---|---|---|---|---|---|---|
| on (the model's default) | 212/214 | 5.2s | 14.2s | 24.3s | 41.7s | 25 of 276 | $0.00079 |
| **low** | **213/214** | **3.9s** | **10.3s** | **22.6s** | **26.6s** | **10** | **$0.00070** |
| off | 196/214 | 3.1s | 6.0s | 23.9s | 115s | 6 | $0.00044 |

With reasoning off, the model often answered without the tool it needed: "note for the Japan trip: bring a power adapter" got "Got it" with nothing saved, "we're in Kyoto on 15 Dec" labelled no day, and a trip's spending was answered as nothing logged instead of looked up. A reply that claims a change it didn't make is worse than a slow one. Low kept every one of those right. Its one failure, setting a trip's set-aside, passed with reasoning on (off failed it too).

**Chosen:** `CHAT_REASONING=low`, now the default.

## Other chat models at a similar price (14 October 2026)

Five newer or current models on the same 214 cases, OpenRouter choosing the hosts, each with its own default reasoning, Qwen3.8 Flash reading photos and DeepSeek writing memories so only the chat model differs:

| Chat model | Passed | Median | p90 | Cost a case |
|---|---|---|---|---|
| **deepseek/deepseek-v4.1-flash, reasoning low** (above) | **213** | **3.9s** | 10.3s | **$0.00070** |
| anthropic/claude-haiku-5.5 | 205 | 3.9s | **7.0s** | $0.0023 |
| z-ai/glm-5.3-flash | 206 | 10.8s | 30.3s | $0.0011 |
| openai/gpt-6-luna-pro | 204 | 11.7s | 21.7s | $0.0039 |
| inclusionai/ling-3.1-flash | 200 | 6.7s | 13.8s | $0.0016 |
| inception/mercury-2.5 | 171 | 4.3s | 9.1s | $0.00088 (7 provider errors) |

**Chosen:**
- Chat: DeepSeek v4.1 Flash with low reasoning (unchanged model): the most passes, as fast as any and the cheapest.
- Fallback: Claude Haiku 5.5 replaces GLM-5.3 Flash, which now takes a median 10.8s with one reply in ten over 30s. Haiku is about as accurate, much faster and steadier, at about 3× DeepSeek's cost, paid only when DeepSeek fails. Set in production as `OPENROUTER_FALLBACK_MODELS=anthropic/claude-haiku-5.5`.


## New providers (25 October 2026)

Since 11:54 UTC today production pins DeepSeek's providers to `together,baseten,fireworks` instead of `deepinfra,fireworks,atlas-cloud,streamlake`. The full set (251 cases) was run with the production pairing on each: DeepSeek v4.1 Flash with low reasoning, Qwen3.8 Flash reading photos (which isn't affected by the provider list). The three runs went side by side, at commit `eaf4a17`.

| Providers | Passed | Median | p90 | Slowest | Turns over 15s | Cost a case |
|---|---|---|---|---|---|---|
| **together, baseten, fireworks** | 246/251 | **1.8s** | **3.5s** | **9.3s** | **0 of 318** | $0.00100 |
| **together, baseten, fireworks** | 248/251 | **1.7s** | **3.7s** | 15.9s | 1 | $0.00099 |
| deepinfra, fireworks, atlas-cloud, streamlake (before) | 249/251 | 2.9s | 6.1s | 150.5s | 3 | $0.00098 |

The new providers answer about 40% faster at the median and p90, at the same cost. Accuracy is about the same: no case failed in all three runs, and only `mem-split-habit` failed in both new runs and not the old one (it is a model choice, not a provider fault; see below). No reply was garbled (mixed scripts, repeated fragments, broken words) and every tool called exists; the only non-Latin reply is Chinese, answering "午饭 12块".

What failed:
- `mem-split-habit` (both new runs): after "i always split dinners with ann 50/50", "dinner 60 at din tai fung" was logged and then the reply asked whether to split it instead of splitting it.
- `log-dollar-sign` (one new run, and the old providers): "$4.20 kopi" found the seeded 4.20 Kopitiam from today and called it a duplicate (old providers: asked whether it's a second one). Today's seeded kopi is the same amount, so this is partly the case's own setup.
- `ctx-long-pending` (one new run, and the old providers): fourteen questions after "dinner at jumbo tonight, probably about 80. i'll tell you the exact amount later", "log that dinner now, it came to 85" asked which dinner, though the earlier turns had mentioned tonight's Jumbo dinner.
- `plan-bill-paid` (one new run): "i paid the rent" asked "Was it the usual 1,800 for rent?" instead of marking it paid.
- `cat-explain` (one new run): explained the 42.10 ride's category but never said "Grab".
- `ask-which-kopitiam` (one new run): listed the three Kopitiam entries under "Which one —" but without a question mark, so it didn't count as a question.
- `wallet-find-likely-moves` (one new run): searched transactions seven times instead of calling `find_likely_moves`.

The old providers' slowest turn, 150.5s on `photo-eticket`, is the kind of stall that prompted the switch.

### Bills: asking "the usual 1,800?" first

`plan-bill-paid` sometimes answers "i paid the rent" with "Was it the usual 1,800?" and changes nothing. A patch told the model to call `mark_bill_paid` straight away, adding a sentence to the tool's description and to the bills skill: a bill with a set amount uses it, so don't confirm the usual amount first. The 14 bill cases (`log-bill-expense`, `q-bills`, the eight bill cases in `plan`, `wallet-card-bill`, `wallet-scheduled-move`, `safe-pay-card`, `calc-bills-next-month`) were run three times without it and three times with it, on the new providers:

| | Run 1 | Run 2 | Run 3 | `plan-bill-paid` |
|---|---|---|---|---|
| Without the patch | 14/14 | 14/14 | 14/14 | 3/3 |
| With the patch | 13/14 | 14/14 | 14/14 | 2/3 ("Was it the usual 1,800? I'll log it and tick off the rent bill.") |

**Not adopted.** The patch didn't stop the question it was written for, and every other bill case passed either way. Counting the full runs too, `plan-bill-paid` asked first in 1 of 6 runs without the patch and 1 of 3 with it.

## DeepSeek v4.1 Flash on `:nitro` hosts (25 October 2026)

Production saw a garbled reply and a call to a tool that doesn't exist (`add_trip_placeholder`) from `deepseek/deepseek-v4.1-flash-1017:nitro` pinned to Together. Two setups were run once each on the full set (252 cases, 319 turns), with Qwen3.8 Flash reading photos and `--reasoning low`:

- **C:** `deepseek/deepseek-v4.1-flash:nitro`, OpenRouter choosing the host.
- **D:** `deepseek/deepseek-v4.1-flash-1017:nitro`, `--providers together`, the production setup that misbehaved.

| Run | Passed | Median | p90 | Slowest | Made-up tools | Empty replies | Cost a case |
|---|---|---|---|---|---|---|---|
| C: v4.1-flash:nitro, OpenRouter picks | 244/252 | 1.9s | 4.1s | 15.6s | **0** | **0** | about $0.0090* |
| D: v4.1-flash-1017:nitro, Together | 244/252 | 1.9s | 4.0s | **198s** | **3** | **2** | $0.0092 |

\* The runner prices by exact model id, and the `:nitro` ids aren't in OpenRouter's model list, so it reported "unknown". These are the recorded tokens (chat and memory writer) at the host's list price. Together charges $0.30/$1.20 per million tokens for both models. C's host isn't recorded. Its token count would come to $0.0011 a case on the cheapest v4.1-flash host and $0.018 on the dearest. The $0.0090 assumes a Together-tier price, which most fast hosts charge.

### Failures

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

### Garbled text and made-up tools

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

### Takeaway

On accuracy and typical speed the two are even: 244/252 each, median 1.9s, p90 about 4s. Only D showed the production problems: three calls to made-up `*_placeholder`-style tools, two empty replies, and one 198s stall. No garbled text appeared in either run, so the production garble wasn't reproduced. These are one run each, so the counts are small. Still, every made-up tool call and empty reply came from `-1017` on Together, which points to that model version or host rather than to `:nitro` routing in general.

**Chosen:** keep `deepseek/deepseek-v4.1-flash` with `OPENROUTER_PROVIDERS=together,baseten,fireworks` (above): as accurate as C, a little faster, and about $0.0010 a case on known hosts. Don't go back to `-1017`.

## Split habits, open items, bills paid (25 October 2026)

Code takes the bookkeeping, the model keeps the conversation: a split habit ("I always split dinners with Ann") is saved and applied when a matching expense is logged, unless the message says this one isn't shared; things the user will come back to ("I'll tell you the exact amount later") are carried through the rolling summary for up to 3 days as optional context; `mark_bill_paid` is always offered. The runner now condenses long chats as production does (it never had, which is why `ctx-long-pending` lost its dinner). Three cases were fixed where the case, not the reply, was wrong (`log-dollar-sign`, `ask-which-kopitiam`, `cat-explain`). Production pairing, together/baseten/fireworks:

| Run | Passed | Median | p90 | Cost a case |
|---|---|---|---|---|
| Full set, run 1 | 256/258 | 1.8s | 3.5s | $0.00114 |
| Full set, run 2 | 256/258 | 1.9s | 3.6s | $0.00115 |

The four failures each happened once and none in what changed. The new and fixed cases, 3 runs each, all passed 3/3, except `ctx-open-not-nagging` (1/3): the "failures" folded tonight's dinner into a budget answer ("Jumbo tonight (~80) would take you to about 224"), which is the open item used where it fits. The case now fails only on asking for the amount. Replies to setting a habit and logging still read templated ("Saved — dinners with Ann will split 50/50 from now on" in 13 of 15); that is for a separate pass on tone.
