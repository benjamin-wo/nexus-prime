---
name: recipes-groceries
description: Parse recipes into ingredients and manage the grocery list — "parse this recipe", "add milk and eggs to groceries", "what's on my grocery list".
tags: [cooking, food, groceries]
side_effect: write
tools:
  - parse_recipe_and_extract_ingredients
  - get_user_grocery_list
  - sync_to_grocery_list
---

# Recipes & groceries

- Recipe text or URL → `parse_recipe_and_extract_ingredients` → then `sync_to_grocery_list` with the extracted ingredients; report what was added.
- "add X to my groceries" → `sync_to_grocery_list` directly. List → `get_user_grocery_list`.
- Quantities: keep the recipe's own units; default "1" when unspecified.
