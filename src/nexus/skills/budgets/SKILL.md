---
name: budgets
description: Monthly budgets, overall or per category, and how much of each is used.
tools: [set_budget, list_budgets, remove_budget]
---
# Budgets

- A budget is a monthly spending limit in the user's home currency, either overall or
  for one category. The same limit applies every month and nothing rolls over.
- "budget 400 for food", "set my food budget to 400": `set_budget` with that category.
  "monthly budget 2000" or "budget 2000 overall": `set_budget` with no category.
  Setting a budget again changes it. Never guess the amount; ask if it's missing.
- "how am I doing on my budgets?", "budget left for food?": `list_budgets`, then answer
  in one or two short lines (what's used, what's left).
- "remove the food budget": `remove_budget`; the confirmation step asks the user.
- The user is told automatically when a budget reaches 50%, 80% and 100%. You don't
  send those alerts and you can't change the thresholds.
- Budgets only track spending. They never block or move money.
