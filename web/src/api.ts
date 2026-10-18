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
/** What a person logs by hand: money in or money out. */
export type Direction = "in" | "out";
/** What a ledger row can be: a move is money between two of the user's own wallets,
 * never spending and never income. */
export type TxDirection = Direction | "move";

export type WalletKind = "spending" | "investment" | "savings" | "card" | "other";
/** A named place money sits (a label; no balance is kept). */
export type Wallet = { id: string; name: string; kind: WalletKind; match_words: string[] };
/** A wallet as a transaction names it. */
export type WalletRef = { id: string; name: string; kind: WalletKind };

/** A foreign amount in the home currency; amount is null when no rate was available. */
export type HomeAmount = { amount: Money | null; rate: string | null; rate_date: string | null };

export type Transaction = {
  id: string;
  direction: TxDirection;
  amount: Money;
  /** A move only: where the money left and where it went (null for money in and out). */
  from_wallet?: WalletRef | null;
  to_wallet?: WalletRef | null;
  /** A move only: what arrived, when that isn't `amount`. */
  received?: Money | null;
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
  /** Proposed as a move because the description names a wallet: money out goes from Spending
   * to `move_to`; money in comes from `move_from`. Both null for an ordinary entry. */
  move_to?: Wallet | null;
  move_from?: Wallet | null;
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
export type Category = { id: string; name: string };
export type Me = {
  user: { telegram_user_id: number; role: "owner" | "member" | "guest"; home_currency: string; timezone: string };
  csrf_token: string;
  /** Set by a sign-in that added the person to a trip with a trip invite. */
  joined_trip?: string | null;
};
export type Summary = {
  start: string;
  end: string;
  /** Every total is in this (home) currency; foreign amounts are converted at their day's rate. */
  currency: string;
  totals: { direction: Direction; total: Money; count: number; converted: Money[]; unconverted: Money[] }[];
  by_category: { category_id: string | null; category_name: string | null; total: Money; count: number }[];
  /** Net moved into savings and investment wallets over the period (home currency). */
  put_away?: Money;
  /** put_away / money in (0.24 is 24%); null without money in. */
  saving_rate?: number | null;
  /** Spending, plus moved from Spending to anything but a card. */
  total_out?: Money;
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
/** How this month stands against what's coming: the figures behind "left to spend". */
export type BudgetMonth = {
  currency: string;
  /** Spending so far, plus moves from Spending to your wallets. */
  total_out: Money;
  /** This month's income less total out and what's still due. */
  left_to_spend: Money;
  /** Bills, subscriptions, trip set-asides and scheduled moves still to come this month. */
  still_due_out: Money;
  income: Money;
  /** The overall budget less spending so far; null without one. */
  budget_left: Money | null;
  /** Whichever of the two is lower; null without an overall budget. */
  tighter: "budget" | "left_to_spend" | null;
  plan_warning: string | null;
  /** Scheduled items left out for want of an amount or a rate. */
  skipped: string[];
};
export type Bill = {
  id: string;
  name: string;
  /** Marking it paid logs an expense; false for money moved, not spent (it's marked done). */
  spending: boolean;
  /** A scheduled move's destination; null on spending and on a payment not linked yet. */
  wallet: WalletRef | null;
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
  /** The wallet it names, while it waits: it may have been a move there (or from there). */
  move_wallet_id?: string | null;
  move_wallet?: string | null;
};
/** An entry that may really have been a move; nothing changes until the user says so. */
export type LikelyMove = { transaction: Transaction; wallet: Wallet | null; reason: string };
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
  direction?: TxDirection;
  status?: "pending" | "confirmed";
  search?: string;
  start?: string;
  end?: string;
  category_id?: string;
  uncategorized?: boolean;
};

export function ledgerParams(filters: LedgerFilters, extra: Record<string, string | number> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...filters, ...extra })) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  return params.toString();
}

/** One thing a department is waiting on the user for, on Home. */
export type FeedItem = {
  department: string;
  kind: string;
  text: string;
  link: string;
  urgent: boolean;
  /** Buttons that settle the item; `path` is relative to /api. */
  actions: FeedAction[];
};
export type FeedAction = { key: string; label: string; method: string; path: string };

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

/** Where the trip is for a stretch of days: a city or area, first to last day. One stop's
 * last day may be the next one's first (the travel day). */
export type TripStop = { name: string; start: string; end: string };

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
  /** The user chose to show no photo. */
  photo_off?: boolean;
  packing?: PackItem[];
  /** How longer hops go: public transport, or a hire car. */
  getting_around?: "transit" | "car";
  /** The stops the user set, in date order; empty means they follow the hotels (see
   * TripDetail.suggested_stops). */
  stops: TripStop[];
  /** Costs are split evenly with the people going: offered once someone else is going. */
  split_evenly: boolean;
  /** "owner" for the user's own trip, "member" for one they were added to: there the budget,
   * set-aside and planned amounts are left out (null, empty). */
  role: "owner" | "member";
  /** The owner's name, as they sign in with. */
  owner_name: string | null;
};

export type PackItem = { text: string; done: boolean };

/** The forecast once it reaches the trip, else the same dates in recent years. */
export type TripWeather = {
  place: string;
  kind: "forecast" | "typical";
  years: number;
  days: { day: string; high: number | null; low: number | null; rain: number | null; summary: string | null; code: number | null }[];
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
  /** A plan's end time, HH:MM. */
  ends_at?: string | null;
  /** A link to book or read more (https only). */
  link?: string | null;
  /** The list a place to visit is filed under (Food, Sights…). */
  list_name?: string | null;
  /** Its place in the day (or in places to visit) once rearranged by hand. */
  order?: number | null;
  scheduled: boolean;
  cost: Money | null;
  logged: boolean;
  manual: boolean;
  /** The user's own pin on the map, for a plan with no Google Maps place (never Google's
   * coordinates, which can't be kept). Dropped once a place is linked. */
  lat?: number | null;
  lng?: number | null;
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
  /** A thumbnail served by our API, and who took it (credited where shown). */
  photo_url?: string | null;
  photo_author?: string | null;
  photo_author_url?: string | null;
  /** Where it is, for the trip map (fetched with the place, never stored). */
  lat?: number | null;
  lng?: number | null;
  /** The neighbourhood it's in ("Gion"): fetched with the place, never stored. */
  area?: string | null;
  /** The city it's in ("Kyoto"): names a trip's stop. Fetched with the place, never stored. */
  city?: string | null;
};
/** A place a travel guide or article recommends, with the page it came from and its
 * Google Maps match when there is one. Nothing is saved until the user picks it. */
export type Idea = {
  name: string;
  area: string | null;
  kind: string | null;
  why: string;
  source: { url: string; title: string };
  place: Place | null;
};
/** `destination` is where the search looked: the trip's, a stop's, or "<area>, <stop>" for a day. */
export type Ideas = { query: string; destination: string; ideas: Idea[] };
/** Where a search for a trip looks. Neither: the whole trip. `stop` is one of the trip's stops
 * (its name, as in `stops`/`suggested_stops`); `day` is a date (YYYY-MM-DD) inside the trip, and
 * leans a Google Maps search towards the places planned that day. Both need the trip: the server
 * answers 422 for a stop that isn't the trip's, a day outside it (or outside the given stop), and
 * 404 for a trip that isn't yours. */
export type SearchScope = { stop?: string | null; day?: string | null };
/** The query string for `GET /travel/places/search` in a trip, scoped to a stop or a day. */
export function placeSearchPath(q: string, tripId: string, scope: SearchScope = {}): string {
  return `/travel/places/search?q=${encodeURIComponent(q)}&trip_id=${tripId}${scopeQuery(scope)}`;
}
/** The path for `GET /travel/trips/{id}/ideas` (guides and articles), scoped to a stop or a day. */
export function tripIdeasPath(tripId: string, q: string, scope: SearchScope = {}): string {
  return `/travel/trips/${tripId}/ideas?q=${encodeURIComponent(q)}${scopeQuery(scope)}`;
}
function scopeQuery({ stop, day }: SearchScope): string {
  return `${stop ? `&stop=${encodeURIComponent(stop)}` : ""}${day ? `&day=${encodeURIComponent(day)}` : ""}`;
}
export type LinkedPlace = {
  booking_id: string;
  place: Place;
  warning: string | null;
  /** For a flight's or train's airport or station: its name, and the days it's left from or landed at. */
  station?: string | null;
  stops?: { day: string; side: "from" | "to" }[];
};
export type TravelMode = "walk" | "transit" | "drive";
/** Getting from one of a day's stops to the next. */
export type Hop = {
  start_id: string;
  end_id: string;
  start: string;
  end: string;
  mode: TravelMode;
  /** Null when Google found no way to get there like that. */
  minutes: number | null;
  metres: number | null;
  /** Takes longer than the time between the two plans. */
  tight: boolean;
  directions: string;
  /** Between an airport and a place right by it (a hire-car desk): not drawn or timed. */
  beside_airport?: boolean;
};

/** A trip as its read-only link shows it: the plan, never money, references, notes or
 * who's going. */
export type SharedBooking = Pick<Booking, "kind" | "title" | "provider" | "starts" | "ends" | "segments" | "hotel" | "address" | "check_in" | "check_out" | "day" | "at" | "category">;
export type SharedTrip = Pick<Trip, "destination" | "start" | "end" | "days" | "status" | "days_until" | "day_number" | "day_labels" | "photo"> & {
  stops: TripStop[];
  bookings: SharedBooking[];
  /** False when the owner hides flights, stays and tickets: `bookings` then holds only their own plans. */
  show_bookings: boolean;
  /** Days a hidden booking starts or ends on (dates only), so the page can say "Travel day"
   * rather than "Free day". Empty while bookings are shown. */
  hidden_days: string[];
};
export type TripShare = {
  token: string | null;
  /** The link shows flights, stays and tickets (on unless turned off). Money, references, notes
   * and who's going are never shown. */
  show_bookings: boolean;
};

/** A cost on the trip that nobody owes a share of yet. */
export type ToSplit = {
  transaction_id: string;
  day: string;
  counterparty: string | null;
  category: string | null;
  /** The whole bill. */
  amount: Money;
  home: Money | null;
};

/** Something a fellow traveller paid for the trip that the user shares in. */
export type PaidByOther = {
  id: string;
  person: string;
  /** The whole bill, in the currency it was paid in. */
  amount: Money;
  note: string | null;
  paid_on: string;
  /** The other travellers sharing it, besides the payer and the user. */
  split_with: string[];
  /** The user's equal part, in the currency it was paid in: what they owe the payer. */
  my_share: Money;
  settled: boolean;
  settled_at: string | null;
};

/** One thing owed between the user and a person: "iou" is their share of a bill the user paid,
 * "payment" the user's share of a bill they paid. */
export type BalancePart = {
  kind: "iou" | "payment";
  id: string;
  label: string | null;
  amount: Money;
  home: Money | null;
  on: string;
};

/** Where the user stands with one person (open items only). `net` is in the home currency,
 * positive when they owe the user, and null when a part has no exchange rate yet; then
 * `net_by_currency` (signed the same way) has the amounts and `direction` is null if the
 * currencies differ. */
export type Balance = {
  person: string;
  direction: "owes_you" | "you_owe" | "even" | null;
  net: Money | null;
  net_by_currency: Money[];
  owes_you: BalancePart[];
  you_owe: BalancePart[];
};

/** POST /travel/trips/{id}/split: `all` splits every cost not split yet, else `transaction_ids`. */
export type SplitBody = { transaction_ids: string[] } | { all: true };
export type SplitResult = {
  with_people: string[];
  done: { transaction_id: string; counterparty: string | null; amount: Money; own_share: Money }[];
  /** Split meanwhile, not on the trip, or can't be split: left alone. */
  skipped: { transaction_id: string; reason: string }[];
};

/** POST/PUT /travel/trips/{id}/paid-by-others. `person` must be a traveller on the trip;
 * `currency` defaults to the home currency, `paid_on` to today and `split_with` (the other
 * travellers sharing it besides the payer and the user) to everyone. */
export type PaidByOtherBody = {
  person: string;
  amount: string;
  currency?: string | null;
  note?: string | null;
  paid_on?: string | null;
  split_with?: string[] | null;
};

/** POST /travel/trips/{id}/settle. What they owe the user is always recorded as money in when it is
 * marked paid back; `log` also records the user's share of what they paid as an expense. */
export type SettleResult = {
  person: string;
  ious_repaid: number;
  payments_settled: number;
  income: Money[];
  expenses: Money[];
};

export type ScreenshotRead = { added: Booking[]; repeated: number; message: string };

/** Something worth a look on a trip day, worked out on the server. */
export type DayNote = { kind: "clash" | "order" | "free" | "arrival"; text: string; ids: string[]; start?: string | null; end?: string | null };

/** A trip day: its entries' ids in itinerary order, and its notes. */
export type DayPlan = { day: string; order: string[]; notes: DayNote[] };

/** What a trip has cost so far against its budget. */
export type TripSpending = {
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
/** The set-aside plan for a trip. */
export type TripSaving = {
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

export type TripDetail = {
  trip: Trip;
  bookings: Booking[];
  /** Each day's entries in order, as the server arranges them. */
  days?: DayPlan[];
  /** Places to visit (no day yet) in the user's order. */
  places_order?: string[];
  places: boolean;
  /** Quick ideas from travel guides and articles are set up. */
  ideas?: boolean;
  /** The stops the hotels suggest (named by each hotel's area where Google Maps knows it):
   * what the page shows until the user sets their own in trip.stops. */
  suggested_stops: TripStop[];
  /** Travel times between a day's stops are set up. */
  routes?: boolean;
  /** The browser key for Google's map; null when there's no map. */
  map_key?: string | null;
  booked: Money | null;
  booked_unlogged: Money | null;
  to_spend: Money | null;
  ready: { nights_without_stay: string[]; has_transport: boolean; has_budget: boolean; done: number; total: number };
  /** Null for a member of the trip (`trip.role`), who gets the plan and no money. */
  spending: TripSpending | null;
  /** Null for a member of the trip. */
  saving: TripSaving | null;
  /** Empty for a member of the trip, as are `items`, `to_split`, `just_mine`, `paid_by_others`
   * and `balances`; `booked`, `booked_unlogged` and `to_spend` are null. */
  owed: { name: string; amounts: Money[]; home: Money | null }[];
  /** Costs not split yet (newest first), while the trip splits evenly and others are going. */
  to_split: ToSplit[];
  /** Expenses marked "just mine". */
  just_mine: string[];
  /** What fellow travellers paid for the trip, oldest first, settled ones included. */
  paid_by_others: PaidByOther[];
  /** Where the user stands with each person (open items only), A to Z. */
  balances: Balance[];
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

/** Someone on a trip: its owner, or a person added to it. */
export type TripMember = {
  id: string;
  /** As they sign in with Telegram; "Someone" if they never gave one. */
  name: string;
  role: "owner" | "member";
  /** Null for the owner. */
  added_at: string | null;
  /** The person asking. */
  you: boolean;
};
/** A trip invite link that can still be used (never the link itself). */
export type TripInvite = { id: string; created_at: string; expires_at: string };
/** `POST /travel/trips/{id}/invites`: a single-use link, valid for 7 days. The token and url are
 * shown this once. */
export type IssuedTripInvite = TripInvite & { token: string; url: string };
/** One change to the plan of a shared trip, newest first (the latest 20). */
export type TripActivity = { actor: string; summary: string; at: string };
/** `POST /travel/invites/{token}/accept`: `new` is false when they were on the trip already. */
export type JoinedTrip = { trip_id: string; new: boolean };
/** The path for the trip's members (`GET`), or one of them (`DELETE`: the owner removes someone,
 * a member removes themselves). */
export const tripMembersPath = (tripId: string, memberId?: string) =>
  `/travel/trips/${tripId}/members${memberId ? `/${memberId}` : ""}`;
/** The path for the trip's invites (`GET`, `POST`), or one of them (`DELETE` cancels it). */
export const tripInvitesPath = (tripId: string, inviteId?: string) =>
  `/travel/trips/${tripId}/invites${inviteId ? `/${inviteId}` : ""}`;
/** The path for `GET /travel/trips/{id}/activity`. */
export const tripActivityPath = (tripId: string) => `/travel/trips/${tripId}/activity`;
/** The path for `PUT /travel/trips/{id}/notes` (body `{ notes: string | null }`), how a member edits the notes. */
export const tripNotesPath = (tripId: string) => `/travel/trips/${tripId}/notes`;
/** The path for `POST /travel/invites/{token}/accept`. */
export const acceptInvitePath = (token: string) => `/travel/invites/${encodeURIComponent(token)}/accept`;

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

/** `POST /travel/research/{run_id}/ideas` body: the research's areas (by name, 1 to 10) whose things
 * to do become ideas on one of your upcoming or ongoing trips, each under a list named after its area. */
export type ResearchIdeasIn = { trip_id: string; areas: string[] };
/** What was done: ideas saved (at most 4 an area), ideas already on the trip (skipped), and the
 * research's place when it is none of the trip's stops (offer it as one; `PUT /stops` saves it).
 * Errors: 404 for a research or trip that isn't yours, 422 for a finished trip, no areas, an area the
 * research lacks, or a trip that's full. Safe to repeat. */
export type ResearchIdeasOut = { added: number; skipped: number; stop_suggestion: string | null };

/** Someone paid (or paying) before, suggested on the entry form from the user's own ledger. */
export type MerchantSuggestion = {
  name: string;
  category_id: string | null;
  category: string | null;
  /** The amount usually paid. */
  amount: Money;
  times: number;
  last_on: string;
};
