---
name: recipes-groceries
description: Parse recipes into ingredients and manage the grocery list — "parse this recipe", "add milk and eggs to groceries", "what's on my grocery list".
tags: [cooking, food, groceries]
side_effect: write
tools:
  - parse_recipe_and_extract_ingredients
  - get_grocery_list
  - add_grocery_items
---

# Recipes & groceries

- Recipe text or URL → `parse_recipe_and_extract_ingredients` → then `add_grocery_items` with the extracted ingredients; report what was added.
- "add X to my groceries" → `add_grocery_items` directly. List → `get_grocery_list`.
- Quantities: keep the recipe's own units; default "1" when unspecified.
