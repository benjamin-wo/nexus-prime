import { api } from "./core";
import type { Money } from "./money";

export type Position = { symbol: string; quantity: string; average_cost: Money; cost: Money };
export type HoldingsDraft = { id: string; positions: Position[]; changes: string[]; first: boolean };
export type EarningsDate = { day: string; timing: string | null };

/** What a price is: live while the US market is open, the day's last price until the official
 * close arrives (provisional), or an official close. */
export type PriceKind = "live" | "provisional_close" | "close";

/** A holding at its latest price (live while the market is open, else the last close); the price
 * fields are null until it has a price. */
export type Holding = Position & {
  updated_at: string;
  price: Money | null;
  /** The trading day the price belongs to. */
  price_day: string | null;
  price_kind: PriceKind | null;
  /** When the price was traded; null for an official close. */
  price_at: string | null;
  value: Money | null;
  gain: Money | null;
  gain_percent: string | null;
  day_change: Money | null;
  day_percent: string | null;
  value_home: Money | null;
  earnings: EarningsDate | null;
};
export type PortfolioTotals = {
  value: Money | null;
  cost: Money | null;
  gain: Money | null;
  gain_percent: string | null;
  day_change: Money | null;
  day_percent: string | null;
  as_of: string | null;
  /** When the newest live or provisional price was traded; null when all are closes. */
  as_of_at: string | null;
  /** Live if any holding's price is, else provisional_close if any is, else close. */
  price_kind: PriceKind;
  missing: string[];
  realised: Money | null;
  dividends: Money | null;
  total_return: Money | null;
};

export type TradeRecord = {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: string;
  price: Money | null;
  traded_on: string;
  realised: Money | null;
};

export type DividendRecord = { symbol: string; ex_date: string; per_share: Money; shares: string; gross: Money; withheld: Money; net: Money };
export type ExpectedDividend = { symbol: string; per_share: Money; payments: number; net: Money; yield_on_value: string | null; yield_on_cost: string | null };
export type Dividends = {
  received: DividendRecord[];
  received_home: Money | null;
  this_year_home: Money | null;
  expected: ExpectedDividend[];
  expected_home: Money | null;
};

export type Portfolio = {
  holdings: Holding[];
  totals: PortfolioTotals;
  draft: HoldingsDraft | null;
  screenshots: boolean;
  prices: boolean;
};

/** Where the market is, for wording: open now, closed after trading today, or not yet open today
 * (so the figures are the last session's). */
export type Session = "live" | "closed_today" | "previous";
export type Mover = {
  symbol: string;
  /** False for a watched stock, shown when nothing is held. */
  held: boolean;
  price: string;
  day_percent: string;
  price_kind: PriceKind;
  /** When the price was traded; null for an official close. */
  price_at: string | null;
  price_day: string;
  /** The day's newest headline, published since the session opened. */
  headline: NewsItem | null;
};
/** What moved today: the portfolio's change and its three biggest movers. */
export type Today = {
  session: Session;
  /** The trading day (New York) the figures belong to. */
  day: string;
  change: Money | null;
  percent: string | null;
  price_kind: PriceKind;
  as_of_at: string | null;
  holds: boolean;
  movers: Mover[];
  prices: boolean;
};
/** A short reading of the day's headlines for one stock's move (POST /investments/today/{symbol}/why). */
export type Why = {
  symbol: string;
  day: string;
  day_percent: string;
  text: string;
  headlines: NewsItem[];
  cached: boolean;
};

export type Watched = {
  symbol: string;
  price: string | null;
  price_day: string | null;
  price_kind: PriceKind | null;
  price_at: string | null;
  day_percent: string | null;
  earnings: EarningsDate | null;
};
export type Watchlist = { stocks: Watched[]; prices: boolean; news: boolean };

export type Levels = {
  as_of: string;
  close: string;
  averages: Record<string, string>;
  trend: "uptrend" | "downtrend" | "mixed" | null;
  rsi: string | null;
  atr: string | null;
  atr_percent: string | null;
  support: string[];
  resistance: string[];
  year_high: string;
  year_low: string;
  days: number;
};
/** Where the close lands after a week, month or quarter, from the stock's own volatility. */
export type PriceRange = { days: number; label: string; low_68: string; high_68: string; low_90: string; high_90: string };
export type NewsItem = { headline: string; source: string; url: string; summary: string; published_at: string };
export type Stock = {
  symbol: string;
  held: Position | null;
  watching: boolean;
  levels: Levels | null;
  ranges: PriceRange[];
  /** Its last year in numbers (returns, falls, how busy, against the market, earnings moves). */
  history?: string[];
  earnings: EarningsDate | null;
  news: NewsItem[];
  prices: boolean;
  news_enabled: boolean;
  plan: PlanBrief | null;
  plans_enabled: boolean;
  /** Live while the market is open, else the last close; null until it has any price. */
  price: string | null;
  price_day: string | null;
  price_kind: PriceKind | null;
  price_at: string | null;
  /** Up to three short facts: that price against the 50- and 200-day averages and the nearest levels. */
  now_vs_levels: string[];
};

export type PlanBrief = {
  id: string;
  symbol: string;
  verdict: string;
  verdict_text: string;
  headline: string;
  reason: string;
  summary_line: string;
  created_at: string;
  valid_until: string;
  expired: boolean;
  /** "refreshed": replaced by its own refresh (Keep fresh); it is closed and not scored. */
  status: "open" | "target" | "stopped" | "expired" | "refreshed";
  entered_on: string | null;
  outcome_day: string | null;
  outcome_price: string | null;
  result_percent: string | null;
  alerts: boolean;
  followed: boolean;
  /** Made again by itself when it goes stale (price moved over an ATR, earnings, a week old, ran out). */
  keep_fresh: boolean;
  /** The plan this one replaced, and when that was made. */
  refreshed_from: { id: string; created_at: string } | null;
  /** The price the plan was written with: live, the day's last before the close, or the close
   * (null on plans made before prices were kept). `price_at` is when it was traded; null for a close. */
  price: string | null;
  price_at: string | null;
  price_kind: PriceKind | null;
};
export type PlanRecord = {
  finished: number;
  targets: number;
  stopped: number;
  expired: number;
  never_entered: number;
  average_result: string | null;
  open: number;
  odds_plans: number;
  odds_said: number | null;
  odds_happened: number | null;
  text: string;
};
export type PlanTarget = { price: string; reward_risk: string; why: string };
export type PlanStep = {
  kind: "buy" | "take_profit" | "cut_loss" | "trail" | "review";
  title: string;
  price: string | null;
  detail: string;
  change: string[];
};
/** Replays of the last year's daily moves: how often each target closed before the stop. */
export type PlanOdds = {
  reference: string;
  stop: string;
  days: number;
  targets: { price: string; chance: number; typical_days: number | null }[];
  stop_first: number;
  neither: number;
  paths: number;
};
export type PlanSource = { id: number; headline: string; source: string; url: string; published_at: string };
export type PlanBody = {
  symbol: string;
  as_of: string;
  close: string;
  verdict: string;
  verdict_text: string;
  reason: string;
  entry_low: string | null;
  entry_high: string | null;
  entry_why: string | null;
  stop: string | null;
  risk: string | null;
  targets: PlanTarget[];
  stop_why?: string | null;
  trail_to?: string | null;
  average_cost?: string | null;
  playbook?: PlanStep[];
  valid_until: string;
  earnings_in_window: string | null;
  trend: string | null;
  held: string | null;
  held_gain_percent: string | null;
  levels: string[];
  technical: string;
  news: { text: string; sources: number[] }[];
  risks: string[];
  bull: string[];
  bear: string[];
  summary: string;
  invalidation: string;
  sources: PlanSource[];
  /** Parts a writer couldn't finish; the numbers are always complete. */
  incomplete?: string[];
  odds?: PlanOdds | null;
  ranges?: string[];
  history?: string[];
  /** The price now when it was written, and when it is already past the buy zone or the stop (plain notes). */
  price?: string | null;
  price_at?: string | null;
  price_kind?: PriceKind | null;
  notes?: string[];
  atr?: string | null;
};
export type PlanDetail = {
  brief: PlanBrief;
  plan: PlanBody;
  closes: { day: string; close: string }[];
  /** The user's newest plan that replaced this one (a refresh, or a plan asked for by hand over a kept-fresh one). */
  replaced_by: { id: string; created_at: string } | null;
};

/** Turn Keep fresh on or off for an open plan (`PUT /investments/plans/{id}/keep-fresh`, 204). */
export function setPlanKeepFresh(id: string, on: boolean): Promise<void> {
  return api(`/investments/plans/${id}/keep-fresh`, { method: "PUT", body: { on } });
}
