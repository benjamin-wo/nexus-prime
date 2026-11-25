import type { Meal } from "./bodyApi";

/** What a deleted meal needs to be put back as it was. */
export const restore = (m: Meal) => ({
  meal: m.meal,
  eaten_at: m.eaten_at,
  ...(m.note ? { note: m.note } : {}),
  items: m.items.map((i) => ({ food_id: i.food_id, grams: i.grams, label: i.label, kind: i.kind, cooking: i.cooking, note: i.note })),
});

/** A meal as one line of foods: "Chicken rice, Soup". */
export const foodsLine = (m: Meal) => m.items.map((i) => i.name ?? i.label ?? "Food").join(", ");

/** Whether any item is the assistant's estimate rather than a database food. */
export const hasEstimate = (m: Meal) => m.items.some((i) => i.source_detail === "ai_estimate");
