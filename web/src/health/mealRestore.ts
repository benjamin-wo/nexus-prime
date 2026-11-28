import type { ItemInput, Meal, MealInput, MealItem } from "./bodyApi";

/** One item as the meals API takes it. An AI estimate has no database food, so it goes back with its own figures. */
function restoreItem(i: MealItem): ItemInput | null {
  const base = { grams: i.grams, label: i.label, kind: i.kind, cooking: i.cooking, note: i.note };
  if (i.food_id) return { food_id: i.food_id, ...base };
  const n = i.nutrients;
  if (!n) return null; // numbers-free mode hides the figures, so there is nothing to put back
  return { food_id: null, ...base, name: i.name, estimate: { kcal: n.kcal, protein_g: n.protein_g, carbs_g: n.carbs_g, fat_g: n.fat_g } };
}

/** What a deleted meal needs to be put back as it was; null when part of it can't be recreated. */
export function restore(m: Meal): MealInput | null {
  const items = m.items.map(restoreItem);
  if (items.some((i) => i === null)) return null;
  return {
    meal: m.meal,
    eaten_at: m.eaten_at,
    ...(m.note ? { note: m.note } : {}),
    items: items as ItemInput[],
  };
}

/** A meal as one line of foods: "Chicken rice, Soup". */
export const foodsLine = (m: Meal) => m.items.map((i) => i.name ?? i.label ?? "Food").join(", ");

/** Whether any item is the assistant's estimate rather than a database food. */
export const hasEstimate = (m: Meal) => m.items.some((i) => i.source_detail === "ai_estimate");
