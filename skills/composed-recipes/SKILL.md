---
name: composed-recipes
description: One-shot composed digests — "brief me" / "good morning" (briefing), "where did my money go" (spend autopsy), "grocery run", "track my bills", "commute conditions".
tags: [briefing, finance, planning]
side_effect: read
tools:
  - run_recipe
---

# Composed recipes

- "good morning" / "brief me" / "what's up today" → `run_recipe("briefing")`.
- "where did my money go" / "spend autopsy" → `run_recipe("spend_autopsy")`.
- "grocery run" → `run_recipe("grocery_run")` (pairs with the recipes-groceries skill for edits).
- "track my bills" → `run_recipe("bill_watch")`. Commute + weather → `run_recipe("commute_conditions")`.
- Present the returned digest as-is — it is already composed and honest about missing config. Add a short friendly opener, don't restructure the data.
