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
