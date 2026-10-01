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
  merchant: string | null;
  transaction_id: string | null;
  actionable: boolean;
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
  kind: "bill" | "subscription" | "salary";
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
export type Updates = { frequency: Frequency; description: string; options: Record<Frequency, string> };
export type Reply = { text: string; buttons: { label: string; data: string }[][] };

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
