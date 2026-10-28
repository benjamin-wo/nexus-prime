/** What the AI models cost: the shape of `GET /api/ops/costs` and how its figures are written.
 * Money arrives as decimal strings in US dollars. */

export type CostMonth = {
  start: string;
  spent: string;
  projected: string;
  days_elapsed: number;
  days_in_month: number;
  /** The part (0 to 1) of this month's input tokens the providers served from their prompt cache. */
  cached_share: number;
};
export type CostDay = { day: string; cost: string; calls: number };
export type CostFeature = { feature: string; cost: string; calls: number; share: number };
/** `user_id` is null for work done for no one in particular ("System"). */
export type CostUser = { user_id: string | null; name: string; cost: string; calls: number };
export type CostModel = {
  model: string;
  cost: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  /** Part of `input_tokens` served from the provider's cache, and its share (0 to 1). */
  cached_tokens: number;
  cached_share: number;
};
export type Costs = {
  currency: string;
  month: CostMonth;
  days: CostDay[];
  by_feature: CostFeature[];
  by_user: CostUser[];
  by_model: CostModel[];
  per_active_user_month: string;
};

/** The day ranges the page offers. */
export const RANGES = [7, 30, 90] as const;
export type Range = (typeof RANGES)[number];

const cents = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fractions = new Intl.NumberFormat("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });

/** A US-dollar amount: cents ("US$0.41", "US$1,234.50"), and four decimals under a cent so a
 * handful of cheap calls doesn't read as nothing ("US$0.0042"). Zero is "US$0.00". */
export function formatUsd(value: string | number): string {
  const amount = Number(value);
  if (!Number.isFinite(amount)) return "US$0.00";
  const sign = amount < 0 ? "-" : "";
  const size = Math.abs(amount);
  return `${sign}US$${(size > 0 && size < 0.01 ? fractions : cents).format(size)}`;
}

/** A count with thousands separators: "1,200". */
export const formatCount = (value: number): string => new Intl.NumberFormat("en-US").format(value);

/** One decimal for the short form, none when it would be ".0" or the number is large. */
function trim(value: number): string {
  return value >= 100 ? String(Math.round(value)) : value.toFixed(1).replace(/\.0$/, "");
}

/** A token count in short form: "950", "220k", "3.4M". */
export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${trim(value / 1_000_000)}M`;
  if (value >= 1_000) return `${trim(value / 1_000)}k`;
  return String(value);
}

/** A 0-to-1 share as a whole percent: "62%", and "<1%" when it is only a little. */
export function formatShare(share: number): string {
  const percent = share * 100;
  return percent > 0 && percent < 1 ? "<1%" : `${Math.round(percent)}%`;
}

// Keys as the server records them: a chat handler, or the kind of background job.
const FEATURES: Record<string, string> = {
  chat: "Chat",
  voice: "Voice notes",
  photo: "Photos",
  pdf: "PDFs",
  "memory.update": "Memory",
  "email.sweep": "Email sweep",
  "department.step.travel.research": "Trip research",
  "department.step.investment.plan": "Investment plans",
  "market.summary.user": "Market summary",
  "news.refresh": "News",
  "plans.follow": "Plan follow-ups",
  "plans.refresh": "Plan refresh",
  "budgets.sweep": "Budget checks",
  "bills.sweep": "Bill checks",
  "salary.sweep": "Payday checks",
  "subscriptions.sweep": "Subscription checks",
  "travel.photos": "Trip photos",
  "trip.activity_digest": "Trip digests",
  "whereabouts.follow": "Whereabouts",
  "ops.tickets": "Ops tickets",
  unknown: "Other",
};

/** A feature's name for people; a key we don't know is shown as it is. */
export const featureLabel = (key: string): string => (Object.hasOwn(FEATURES, key) ? FEATURES[key]! : key);

/** A day (YYYY-MM-DD) as "Tue 27 Oct", by the calendar. */
export function costDayLabel(day: string): string {
  // Built from parts so every month is three letters ("Sep", not en-GB's "Sept").
  const part = (type: string, parts: Intl.DateTimeFormatPart[]) => parts.find((p) => p.type === type)?.value ?? "";
  const parts = new Intl.DateTimeFormat("en-US", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).formatToParts(
    new Date(`${day}T00:00:00Z`),
  );
  return `${part("weekday", parts)} ${part("day", parts)} ${part("month", parts)}`;
}
