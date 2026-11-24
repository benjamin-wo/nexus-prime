import type { Cooking, MealSlot, Nutrients, Totals } from "./bodyApi";
import type { WeightUnit } from "./api";

const n = (s: string) => Math.round(Number(s));
const group = (v: number) => v.toLocaleString("en-US");

/** "about 600–750 kcal" from the server's low and high; one figure only when the two are the same. Never a point value. */
export function kcalRange(t: Pick<Totals, "low" | "high">): string {
  const lo = n(t.low.kcal);
  const hi = n(t.high.kcal);
  return lo === hi ? `about ${group(lo)} kcal` : `about ${group(lo)}–${group(hi)} kcal`;
}

/** "about 30–40 g" for one nutrient of the range. */
export function gramsRange(t: Pick<Totals, "low" | "high">, key: keyof Pick<Nutrients, "protein_g" | "carbs_g" | "fat_g">): string {
  const lo = n(t.low[key]);
  const hi = n(t.high[key]);
  return lo === hi ? `about ${lo} g` : `about ${lo}–${hi} g`;
}

export const SLOTS: { value: MealSlot; label: string }[] = [
  { value: "breakfast", label: "Breakfast" },
  { value: "lunch", label: "Lunch" },
  { value: "dinner", label: "Dinner" },
  { value: "snack", label: "Snack" },
];
export const slotLabel = (slot: MealSlot) => SLOTS.find((s) => s.value === slot)?.label ?? slot;

export const COOKING: { value: Cooking | null; label: string }[] = [
  { value: null, label: "None" },
  { value: "fried", label: "Fried" },
  { value: "stir-fried", label: "Stir-fried" },
  { value: "curry/gravy", label: "Curry or gravy" },
];
export const cookingLabel = (c: Cooking) => COOKING.find((x) => x.value === c)?.label ?? c;

const LB_PER_KG = 2.20462262;
/** A weight from the server (kg) in the unit the person logs in, to one decimal ("82.4"). */
export function inUnit(kg: string, unit: WeightUnit): string {
  const v = unit === "lb" ? Number(kg) * LB_PER_KG : Number(kg);
  return (Math.round(v * 10) / 10).toFixed(1).replace(/\.0$/, "");
}

/** Today as YYYY-MM-DD on this device. */
export const localToday = () => new Intl.DateTimeFormat("en-CA").format(new Date());
