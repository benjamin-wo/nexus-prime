---
name: web-research
description: Search the web and read pages for facts, news, prices, definitions — "who is X", "what's the weather", "latest news on Y".
tags: [web, knowledge, news]
side_effect: read
tools:
  - search_web
  - fetch_url
---

# Web research

- `search_web(query)` for open questions, news, facts. `fetch_url(url)` ONLY when the user gives a specific link.
- Summarize from exactly what the tools return. NEVER invent URLs, headlines, prices, or quotes that are not in the results.
- Cite the source domain inline (e.g. "per channelnewsasia.com") when stating a specific fact.
- If search returns nothing useful, say so and offer to retry with different wording — do not guess.
- A raw URL in your final reply is only allowed if a search_web/fetch_url call this turn actually produced it.
