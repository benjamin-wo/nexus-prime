import type { Consents, Day, Food, Meal, Profile, SafetyNote, WeightOverview } from "./bodyApi";

export const consented = { consented_at: "2026-11-20T08:00:00Z" };
export const calm: SafetyNote = { suspended: false, signposts: [], new_signals: [], check_in: null };
/** What the server sends (domain/health_texts.py): SGH and SOS, and KKH first for under-18s. */
export const signposts = [
  { name: "SGH Eating Disorders Programme", contact: "eatingdisorders@sgh.com.sg", note: "Specialist support for ages 13 and up." },
  { name: "Samaritans of Singapore", contact: "1767, or WhatsApp 9151 1767", note: "Someone to talk to, any time." },
];
export const signpostsUnder18 = [{ name: "KK Women's and Children's Hospital (KKH)", contact: "6294 4050", note: "Appointments for under-18s." }, ...signposts];
export const CHECK_IN_TEXT =
  "I've noticed some patterns in your logs lately that can mean things are hard. No judgement at all. If you'd like to talk to someone, the contacts below are there for you, and I'll keep calorie targets switched off for now.";

const n = (kcal: string, p = "10") => ({ kcal, protein_g: p, carbs_g: "50", fat_g: "10", fibre_g: null });
export const totals = { point: n("675"), low: n("600", "30"), high: n("750", "40") };

export const rice: Food = {
  id: "rice-1",
  source: "hpb",
  name: "Chicken rice",
  aliases: [],
  kcal_per_100g: "170",
  portions: [{ label: "1 plate", grams: "350" }],
};

export const lunch: Meal = {
  id: "m1",
  meal: "lunch",
  eaten_at: "2026-11-24T12:30:00Z",
  source: "manual",
  note: null,
  items: [{ id: "i1", food_id: rice.id, name: "Chicken rice", grams: "350", label: "1 plate", kind: "portion", cooking: null, note: null, nutrients: n("675") }],
  totals,
};

export const day = (over: Partial<Day> = {}): Day => ({
  date: new Intl.DateTimeFormat("en-CA").format(new Date()),
  hidden: false,
  meals: [lunch],
  totals,
  targets_kcal: "1900",
  remaining: { kcal: "1225", protein_g: "70", fibre_g: null },
  safety: calm,
  ...over,
});

export const hiddenDay = (): Day => ({
  ...day(),
  hidden: true,
  meals: [{ ...lunch, totals: null, items: lunch.items.map((i) => ({ ...i, nutrients: null })) }],
  totals: null,
  targets_kcal: null,
  remaining: null,
});

export const weight = (over: Partial<WeightOverview> = {}): WeightOverview => ({
  hidden: false,
  trend_words: "slowly down",
  points: [
    { date: "2026-11-10", scale_kg: "83.2", trend_kg: "83.0" },
    { date: "2026-11-17", scale_kg: "82.6", trend_kg: "82.7" },
    { date: "2026-11-24", scale_kg: null, trend_kg: "82.4" },
  ],
  trend_kg: "82.4",
  rate_kg_per_week: "-0.3",
  rate_pct_per_week: "-0.4",
  rate_text: "about 0.3 kg a week down over the last 2 weeks",
  last_weigh_in: { at: "2026-11-23T07:00:00Z", kg: "82.5" },
  ...over,
});
export const hiddenWeight = (): WeightOverview => ({
  hidden: true, trend_words: "slowly down", points: null, trend_kg: null, rate_kg_per_week: null, rate_pct_per_week: null, rate_text: null, last_weigh_in: null,
});

export const consents: Consents = {
  health_consented_at: "2026-11-20T08:00:00Z",
  scopes: [
    { scope: "ai_processing", active: false, granted_at: null, withdrawn_at: null },
    { scope: "model_improvement", active: true, granted_at: "2026-11-21T08:00:00Z", withdrawn_at: null },
  ],
  ai_provider: { name: "OpenRouter", country: "United States" },
  wellness_statement: "This product is not intended to diagnose, treat, mitigate, cure or prevent any disease or medical condition.",
};

export const profile: Profile = {
  sex_for_equations: "unspecified",
  birth_year: 1990,
  height_cm: "172",
  activity_level: "light",
  goal: "maintain",
  target_rate_pct_per_week: null,
  numbers_free: false,
  ed_history: true,
  unit_system: "metric",
  updated_at: "2026-11-24T08:00:00Z",
  safety: { gates: [{ name: "weight_loss", allowed: false, reason: "ed_history" }], suspended: true, signposts },
};
