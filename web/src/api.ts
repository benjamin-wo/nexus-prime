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

export type Transaction = {
  id: string;
  direction: Direction;
  amount: Money;
  occurred_at: string;
  counterparty: string | null;
  category_id: string | null;
  notes: string | null;
  status: "confirmed" | "pending";
  source: string;
  deleted: boolean;
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
  totals: { direction: Direction; total: Money; count: number }[];
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
