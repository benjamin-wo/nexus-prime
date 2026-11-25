import { api } from "../api";
import type { WeightUnit } from "./api";

/** The Health body, energy and food API (`/api/health/...`): weigh-ins, the wellness profile, consents, foods and meals.
 * Amounts come as decimal strings. Nothing here works out a nutrient: the server does, and sends ranges. */

export type Signpost = { name: string; contact: string; note: string };
/** What a read says about safety. `check_in` is fixed text from the server; `new_signals` are signals first seen by this read. */
export type SafetyNote = { suspended: boolean; signposts: Signpost[]; new_signals: string[]; check_in: string | null };

export type Sex = "female" | "male" | "unspecified";
export type ActivityLevel = "sedentary" | "light" | "moderate" | "active" | "very_active";
export type Goal = "lose" | "maintain" | "gain" | "performance";
export type Gate = { name: string; allowed: boolean; reason: string };
export type Profile = {
  sex_for_equations: Sex;
  birth_year: number | null;
  height_cm: string | null;
  activity_level: ActivityLevel | null;
  goal: Goal;
  target_rate_pct_per_week: string | null;
  numbers_free: boolean;
  ed_history: boolean;
  unit_system: "metric" | "imperial";
  updated_at: string;
  safety: { gates: Gate[]; suspended: boolean; signposts: Signpost[] };
};
export type ProfileInput = Omit<Profile, "updated_at" | "safety"> & { confirm_ed_override?: boolean };

export type TrendPoint = { date: string; scale_kg: string | null; trend_kg: string };
export type WeightOverview = {
  hidden: boolean;
  trend_words: string;
  points: TrendPoint[] | null;
  trend_kg: string | null;
  rate_kg_per_week: string | null;
  rate_pct_per_week: string | null;
  rate_text: string | null;
  last_weigh_in: { at: string; kg: string } | null;
};
export type Sample = { id: string; kind: string; value: string; unit: string; value_kg: string | null; start_at: string };

export type Scope = "ai_processing" | "source:health_connect" | "source:healthkit" | "source:oauth" | "model_improvement";
export type ScopeState = { scope: Scope; active: boolean; granted_at: string | null; withdrawn_at: string | null };
export type Consents = {
  health_consented_at: string | null;
  scopes: ScopeState[];
  ai_provider: { name: string; country: string };
  wellness_statement: string;
};

export type Portion = { label: string; grams: string };
export type Food = { id: string; source: string; name: string; aliases: string[]; kcal_per_100g: string; portions: Portion[] };
export type Cooking = "fried" | "stir-fried" | "curry/gravy";
export type MealSlot = "breakfast" | "lunch" | "dinner" | "snack";
export type EstimateKind = "weighed" | "portion" | "estimated";
export type Nutrients = { kcal: string; protein_g: string; carbs_g: string; fat_g: string; fibre_g: string | null };
export type Totals = { point: Nutrients; low: Nutrients; high: Nutrients };
export type MealItem = {
  id: string | null;
  /** null for an estimate the assistant made without a database food. */
  food_id: string | null;
  /** Where the figures came from; absent before estimates existed. */
  source_detail?: "db" | "ai_estimate" | null;
  name: string | null;
  grams: string;
  label: string;
  kind: EstimateKind;
  cooking: Cooking | null;
  note: string | null;
  nutrients: Nutrients | null;
};
export type Meal = { id: string; meal: MealSlot; eaten_at: string; source: string; note: string | null; items: MealItem[]; totals: Totals | null };
export type ItemInput = { food_id: string | null; grams: string; label?: string; kind?: EstimateKind; cooking?: Cooking | null; note?: string | null };
export type MealInput = { meal: MealSlot; items: ItemInput[]; eaten_at?: string; note?: string };
export type Day = {
  date: string;
  hidden: boolean;
  meals: Meal[];
  totals: Totals | null;
  targets_kcal: string | null;
  remaining: { kcal: string; protein_g: string; fibre_g: string | null } | null;
  safety: SafetyNote;
};

const base = "/health";
const q = (params: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export const bodyKey = {
  profile: ["health", "profile"] as const,
  consents: ["health", "consents"] as const,
  weight: ["health", "weight"] as const,
  day: (date: string | null) => ["health", "day", date] as const,
  meals: ["health", "day"] as const,
};

export const bodyApi = {
  profile: () => api<Profile | null>(`${base}/profile`),
  saveProfile: (body: ProfileInput) => api<Profile>(`${base}/profile`, { method: "PUT", body }),
  consents: () => api<Consents>(`${base}/consents`),
  /** One tap: the master consent and the AI scope together. */
  turnOn: () => api<Consents>(`${base}/consent/all`, { method: "POST" }),
  grant: (scope: Scope) => api<ScopeState>(`${base}/consents/${encodeURIComponent(scope)}`, { method: "PUT" }),
  withdraw: (scope: Scope) => api<ScopeState>(`${base}/consents/${encodeURIComponent(scope)}`, { method: "DELETE" }),

  weight: (days = 90) => api<WeightOverview>(`${base}/weight${q({ days })}`),
  logWeight: (value: string, unit: WeightUnit) => api<Sample>(`${base}/samples`, { method: "POST", body: { kind: "weight", value, unit } }),

  foods: (text: string) => api<Food[]>(`${base}/foods${q({ text, limit: 20 })}`),
  day: (date: string | null) => api<Day>(`${base}/day${q({ date: date ?? undefined })}`),
  logMeal: (body: MealInput) => api<Meal>(`${base}/meals`, { method: "POST", body }),
  editMeal: (id: string, body: Partial<MealInput>) => api<Meal>(`${base}/meals/${id}`, { method: "PATCH", body }),
  deleteMeal: (id: string) => api<null>(`${base}/meals/${id}`, { method: "DELETE" }),
};
