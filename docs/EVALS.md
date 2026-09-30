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

Settings for production: `LLM_PROVIDER=openrouter`, `OPENROUTER_MODEL=deepseek/deepseek-v4.1-flash`, `OPENROUTER_VISION_MODEL=qwen/qwen3.8-flash`, `OPENROUTER_FALLBACK_MODELS=qwen/qwen3.8-flash`.

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
