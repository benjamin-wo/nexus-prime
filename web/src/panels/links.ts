// What a panel is called, where its tab is, and how its filters read as words. Pure: no data fetched here.

import { monthLabel } from "../months";
import type { PanelEvent, PanelKind } from "./types";

export const PANEL_TITLES: Record<PanelKind, string> = {
  "finance.month_outlook": "Month outlook",
  "finance.budgets": "Budgets",
  "finance.transactions": "Transactions",
  "travel.trip_budget": "Trip budget",
};

/** The department a panel's tab belongs to. */
export const PANEL_DEPARTMENT: Record<PanelKind, "Money" | "Travel"> = {
  "finance.month_outlook": "Money",
  "finance.budgets": "Money",
  "finance.transactions": "Money",
  "travel.trip_budget": "Travel",
};

/** The Ledger's address for the filters a transactions panel holds. The panel's params are named as
 * GET /api/transactions names them; the Ledger reads `view`, `category`, `start`, `end`, `paid_with`
 * and `search` from its address. */
export function ledgerSearch(filters: Record<string, string>): string {
  const params = new URLSearchParams();
  if (filters.direction === "out" || filters.direction === "in" || filters.direction === "move") params.set("view", filters.direction);
  else if (filters.status === "pending") params.set("view", "pending");
  if (filters.category_id) params.set("category", filters.category_id);
  else if (filters.uncategorized === "true") params.set("category", "none");
  for (const key of ["start", "end", "paid_with", "search"]) if (filters[key]) params.set(key, filters[key]);
  return params.toString();
}

/** The tab a panel is a view of, with the same params in its address. */
export function tabLink(event: PanelEvent): string {
  switch (event.kind) {
    case "finance.month_outlook":
      return `/accounting?month=${event.params.month}`;
    case "finance.budgets":
      return `/accounting/budgets?month=${event.params.month}`;
    case "finance.transactions": {
      const search = ledgerSearch(event.params);
      return `/accounting/ledger${search ? `?${search}` : ""}`;
    }
    case "travel.trip_budget":
      return `/travel/trips/${encodeURIComponent(String(event.params.trip_id))}`;
  }
}

/** The link at a panel's foot. Transactions go to the Ledger, which is where those filters are read. */
export const openLabel = (event: PanelEvent): string => (event.kind === "finance.transactions" ? "Open in Ledger" : `Open in ${PANEL_DEPARTMENT[event.kind]}`);

const longDay = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${iso}T00:00:00Z`));

/** A transactions panel's filters in plain words: "money out, in Dining, 1 Oct to 31 Oct, matching “coffee”".
 * `categoryName` is the category's name once known. */
export function filterWords(filters: Record<string, string>, categoryName?: string | null): string {
  const parts: string[] = [];
  if (filters.direction === "out") parts.push("money out");
  else if (filters.direction === "in") parts.push("money in");
  else if (filters.direction === "move") parts.push("transfers");
  if (filters.status === "pending") parts.push("pending");
  if (filters.uncategorized === "true") parts.push("with no category");
  else if (filters.category_id) parts.push(`in ${categoryName ?? "one category"}`);
  if (filters.start && filters.end) parts.push(`${longDay(filters.start)} to ${longDay(filters.end)}`);
  else if (filters.start) parts.push(`from ${longDay(filters.start)}`);
  else if (filters.end) parts.push(`until ${longDay(filters.end)}`);
  if (filters.paid_with) parts.push(filters.paid_with === "none" ? "with no card set" : "paid with one card");
  if (filters.search) parts.push(`matching “${filters.search}”`);
  if (filters.source) parts.push(`from ${filters.source}`);
  if (filters.include_deleted === "true") parts.push("including deleted");
  return parts.length === 0 ? "all transactions" : parts.join(", ");
}

/** The query a panel shows, as the part of its line that needs no data. */
export function queryWords(event: PanelEvent, extra?: { categoryName?: string | null; destination?: string | null }): string {
  switch (event.kind) {
    case "finance.month_outlook":
      return `Where ${monthLabel(event.params.month)} ends up`;
    case "finance.budgets":
      return `Budgets in ${monthLabel(event.params.month)}`;
    case "finance.transactions":
      return `Transactions: ${filterWords(event.params, extra?.categoryName)}`;
    case "travel.trip_budget":
      return `Budget and spending for ${extra?.destination ?? "your trip"}`;
  }
}
