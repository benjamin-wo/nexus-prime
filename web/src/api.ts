export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

let csrfToken = "";

export function setCsrf(token: string): void {
  csrfToken = token;
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    credentials: "same-origin",
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (response.status === 204) return undefined as T;
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail : response.statusText);
  }
  return data as T;
}

export type Money = { amount: string; currency: string };
export type Direction = "in" | "out";

/** A foreign amount in the home currency; amount is null when no rate was available. */
export type HomeAmount = { amount: Money | null; rate: string | null; rate_date: string | null };

export type Transaction = {
  id: string;
  direction: Direction;
  amount: Money;
  /** Set on listings for rows not in the home currency. */
  home?: HomeAmount | null;
  occurred_at: string;
  counterparty: string | null;
  category_id: string | null;
  /** The rule that chose the category, if one did. */
  category_rule_id?: string | null;
  notes: string | null;
  status: "confirmed" | "pending";
  source: string;
  deleted: boolean;
  /** A receipt is kept for it; open it at receiptUrl(id). */
  has_receipt?: boolean;
  /** A bill shared with others: the user's share and each person's. */
  split?: { own_share: Money; people: { name: string; share: Money; repaid: Money }[] } | null;
  /** Repayments linking it to other transactions: for a bill, the money in that
   * paid part of it back; for money in, the bill it paid back. */
  links?: { transaction_id: string; counterparty: string | null; occurred_at: string; name: string; amount: Money }[];
  /** The user's own money in it, when friends paid part of it back. */
  own?: Money | null;
  /** Set on listings: another transaction that looks like the same payment. */
  duplicate?: { transaction_id: string; counterparty: string | null; occurred_at: string; amount: Money } | null;
};

/** The receipt's short-lived link; the server checks it's the owner asking. */
export const receiptUrl = (id: string) => `/api/transactions/${id}/receipt`;

/** Offered after a category correction; nothing changes unless the user accepts. */
export type RuleSuggestion = {
  question: string;
  pattern: string;
  category_id: string;
  replaces_category_id: string | null;
};
export type EditedTransaction = Transaction & { rule_suggestion?: RuleSuggestion | null };
export type CategoryRule = {
  id: string;
  pattern: string;
  category_id: string;
  category_name: string;
  explanation: string;
};

export type Memory = {
  id: string;
  kind: "fact" | "preference" | "episode";
  text: string;
  happened_on: string | null;
  updated_at: string;
};

export type ImportLayout = {
  date: number;
  description: number[];
  amount: number | null;
  debit: number | null;
  credit: number | null;
  currency: number | null;
  date_order: "dmy" | "mdy" | "ymd";
  sign: "negative_is_out" | "positive_is_out";
};
export type ImportRow = {
  index: number;
  verdict: "new" | "duplicate" | "imported" | "unclear";
  cells: string[];
  date: string | null;
  description: string;
  amount: string | null;
  currency: string | null;
  direction: "in" | "out" | null;
  category: string | null;
  problem: string | null;
  matches: { date: string; description: string | null; amount: string } | null;
};
export type ImportPreview = {
  headers: string[];
  layout: ImportLayout | null;
  saved_as: string | null;
  rows: ImportRow[];
};
export type ImportRecord = {
  id: string;
  file_name: string;
  added: number;
  created_at: string;
  undone_at: string | null;
  skipped?: number;
};

export type Page = { items: Transaction[]; total: number };
export type Category = { id: string; name: string; active: boolean };
export type Me = {
  user: { telegram_user_id: number; role: "owner" | "member"; home_currency: string; timezone: string };
  csrf_token: string;
};
export type Summary = {
  start: string;
  end: string;
  /** Every total is in this (home) currency; foreign amounts are converted at their day's rate. */
  currency: string;
  totals: { direction: Direction; total: Money; count: number; converted: Money[]; unconverted: Money[] }[];
  by_category: { category_id: string | null; category_name: string | null; total: Money; count: number }[];
};
/** Money out per month for Home's chart, oldest first, ending with this month so far. */
export type Spending = {
  currency: string;
  months: { month: string; spent: Money; to_date: boolean }[];
  last_month_to_date: Money;
  budget: Money | null;
};
export type Iou = {
  split_id: string;
  transaction_id: string;
  participant_name: string;
  share: Money;
  outstanding: Money;
  expense_occurred_at: string;
};
export type Budget = {
  id: string;
  category_id: string | null;
  name: string;
  limit: Money;
  spent: Money;
  remaining: Money;
  percent: number;
  unconverted: Money[];
};
export type Bill = {
  id: string;
  name: string;
  amount: Money | null;
  cadence: "once" | "weekly" | "monthly" | "yearly";
  due: string;
  days_until: number;
  snoozed: boolean;
};
export type Salary = {
  rule: "monthly_day" | "last_weekday" | "biweekly";
  day: number | null;
  anchor: string | null;
  description: string;
  usual: Money | null;
  next_payday: string;
  days_until: number;
};
export type EmailStatus = "pending" | "logged" | "skipped" | "not_receipt" | "no_amount" | "duplicate" | "failed";
export type InboundEmail = {
  id: string;
  received_at: string;
  sender: string;
  subject: string;
  status: EmailStatus;
  reason: string | null;
  amount: string | null;
  currency: string | null;
  merchant: string | null; // who was paid; for money received, who sent it
  received: boolean; // money in, not money spent
  transaction_id: string | null;
  actionable: boolean;
  /** The payment it looks like a second record of, while it waits. */
  duplicate_of?: string | null;
};
export type EmailConnection = {
  id: string;
  provider: "gmail" | "forward";
  address: string;
  status: "active" | "broken";
  last_checked: string | null;
  last_received: string | null;
};
export type EmailOverview = {
  available: boolean;
  forwarding_available: boolean;
  connections: EmailConnection[];
  emails: InboundEmail[];
};
export type Expected = {
  kind: "bill" | "subscription" | "salary" | "trip";
  name: string;
  direction: "in" | "out";
  amount: Money | null;
  home: Money | null;
};
export type CashDay = {
  day: string;
  money_in: Money;
  money_out: Money;
  net: Money;
  expected: Expected[];
  expected_net: Money;
};
export type CashFlow = {
  start: string;
  end: string;
  today: string;
  currency: string;
  days: CashDay[];
  logged_in: Money;
  logged_out: Money;
  expected_in: Money;
  expected_out: Money;
  unknown_amounts: number;
  unconverted: Money[];
};
export type Subscription = {
  id: string;
  name: string;
  cadence: "weekly" | "monthly" | "yearly";
  amount: Money;
  monthly: Money;
  last_charged_on: string;
  next_charge: string;
  previous_amount: Money | null;
  price_changed_on: string | null;
};
export type Subscriptions = { tracked: Subscription[]; proposed: Subscription[]; monthly_totals: Money[] };
export type Frequency = "instant" | "hourly" | "thrice_daily" | "daily" | "off";
export type Updates = {
  frequency: Frequency;
  /** HH:MM, local time: when the daily summary goes. */
  daily_at: string;
  description: string;
  options: Record<Frequency, string>;
};
export type Reply = { text: string; buttons: { label: string; data: string }[][] };
/** The running chat as the user saw it, oldest first; notifications aren't part of it. */
export type ChatHistory = {
  lines: { id: number; role: "user" | "nexus"; text: string; channel: string | null; at: string }[];
  more: boolean;
  pending: Reply | null;
};

export type LedgerFilters = {
  direction?: Direction;
  status?: "pending";
  search?: string;
  start?: string;
  end?: string;
  category_id?: string;
};

export function ledgerParams(filters: LedgerFilters, extra: Record<string, string | number> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params.toString();
}

/** One thing a department is waiting on the user for, on Home. */
export type FeedItem = { department: string; kind: string; text: string; link: string; urgent: boolean };

/** A department's long piece of work, saved step by step. */
export type Run = {
  id: string;
  department: string;
  kind: string;
  title: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: string;
  steps_done: number;
  steps_total: number;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export type Position = { symbol: string; quantity: string; average_cost: Money; cost: Money };
export type HoldingsDraft = { id: string; positions: Position[]; changes: string[]; first: boolean };
export type EarningsDate = { day: string; timing: string | null };

/** A holding at the last daily close; the price fields are null until it has a price. */
export type Holding = Position & {
  updated_at: string;
  price: Money | null;
  price_day: string | null;
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

export type Watched = {
  symbol: string;
  price: string | null;
  price_day: string | null;
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
  status: "open" | "target" | "stopped" | "expired";
  entered_on: string | null;
  outcome_day: string | null;
  outcome_price: string | null;
  result_percent: string | null;
  alerts: boolean;
  followed: boolean;
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
};
export type PlanDetail = { brief: PlanBrief; plan: PlanBody; closes: { day: string; close: string }[] };

/** A trip (Travel). Budget, set-aside and planned amounts are in the home currency. */
export type Trip = {
  id: string;
  destination: string;
  start: string;
  end: string;
  days: number;
  currency: string;
  budget: Money | null;
  companions: string[];
  set_aside: Money | null;
  planned: Record<string, Money>;
  status: "upcoming" | "ongoing" | "finished";
  days_until: number;
  day_number: number | null;
  notes: string | null;
  day_labels: Record<string, string>;
  /** A famous view of where it goes, from Wikimedia Commons, once found. */
  photo?: TripPhoto | null;
};

/** A trip's header photo, served by our API, with the credit its licence asks for. */
export type TripPhoto = {
  url: string;
  credit: string;
  page: string | null;
  licence_url: string | null;
  spot: string | null;
};

/** A flight, hotel or train booking read from email. Times are local as booked. */
export type Booking = {
  id: string;
  trip_id: string | null;
  kind: "flight" | "hotel" | "rail" | "activity";
  title: string;
  provider: string | null;
  starts: string;
  ends: string | null;
  segments: { number: string | null; origin: string | null; destination: string | null; departs: string | null; arrives: string | null }[];
  hotel: string | null;
  address: string | null;
  check_in: string | null;
  check_out: string | null;
  name: string | null;
  day: string | null;
  at: string | null;
  note: string | null;
  reference: string | null;
  booked_via: string | null;
  category: string | null;
  place_id: string | null;
  scheduled: boolean;
  cost: Money | null;
  logged: boolean;
  manual: boolean;
};

/** A place as Google Maps shows it: fetched when shown, only its id is kept. */
export type Place = {
  id: string;
  name: string;
  address: string | null;
  kind: string | null;
  rating: string | null;
  ratings: number | null;
  price: string | null;
  maps_url: string | null;
  website: string | null;
  phone: string | null;
  summary: string | null;
  status: string | null;
  hours: string[];
  reviews: { rating: number | null; text: string; author: string | null; author_url: string | null; when: string | null }[];
};
export type LinkedPlace = { booking_id: string; place: Place; warning: string | null };

export type ScreenshotRead = { added: Booking[]; repeated: number; message: string };

export type TripDetail = {
  trip: Trip;
  bookings: Booking[];
  places: boolean;
  booked: Money | null;
  booked_unlogged: Money | null;
  to_spend: Money | null;
  ready: { nights_without_stay: string[]; has_transport: boolean; has_budget: boolean; done: number; total: number };
  spending: {
    spent: Money;
    left: Money | null;
    percent: number | null;
    before: Money;
    today: Money | null;
    per_day: Money | null;
    per_day_left: Money | null;
    categories: { name: string; planned: Money | null; spent: Money }[];
    unconverted: number;
  };
  saving: {
    per_payday: Money | null;
    paydays_done: number;
    paydays_left: number;
    saved: Money | null;
    by_start: Money | null;
    covers_budget: boolean | null;
    suggested: Money | null;
    fits: boolean | null;
    next_payday: string | null;
    pay_schedule: boolean;
  };
  owed: { name: string; amounts: Money[]; home: Money | null }[];
  items: {
    transaction_id: string;
    day: string;
    counterparty: string | null;
    category: string | null;
    amount: Money;
    home: Money | null;
    linked: boolean;
  }[];
};

/** A trip's research: every price names a source (by id), checked on the date given. */
export type Research = {
  destination: string;
  start: string;
  end: string;
  nights: number;
  travellers: number;
  currency: string | null;
  home_currency: string;
  when_summary: string;
  when: { text: string; source: number }[];
  prices: { label: string; low: string; high: string; currency: string; per: string; source: number; home_low: string | null; home_high: string | null }[];
  areas: { name: string; why: string; things: string[]; source: number }[];
  getting_around: string;
  getting_around_source: number | null;
  sources: { id: number; url: string; title: string; checked_on: string }[];
  estimate_low: string | null;
  estimate_high: string | null;
  estimate_lines: string[];
  budget: string | null;
  paydays_left: number;
  set_aside: string | null;
  fits: boolean | null;
  trip_id: string | null;
};
