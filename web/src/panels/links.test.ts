import { describe, expect, it } from "vitest";

import { filterWords, ledgerSearch, openLabel, tabLink } from "./links";
import type { PanelEvent } from "./types";

const base = { version: 1 as const, topic: "x", as_of: "2026-11-15T10:00:00Z", message_id: "m1" };

describe("ledgerSearch", () => {
  it("renames the transactions endpoint's filters to what the Ledger reads from its address", () => {
    expect(ledgerSearch({ direction: "out", category_id: "c1", start: "2026-10-01", end: "2026-10-31", search: "coffee" })).toBe(
      "view=out&category=c1&start=2026-10-01&end=2026-10-31&search=coffee",
    );
    expect(ledgerSearch({ status: "pending" })).toBe("view=pending");
    expect(ledgerSearch({ uncategorized: "true" })).toBe("category=none");
    expect(ledgerSearch({})).toBe("");
  });
});

describe("filterWords", () => {
  it("says the filters in plain words", () => {
    expect(filterWords({})).toBe("all transactions");
    expect(filterWords({ direction: "in", uncategorized: "true", search: "pay", include_deleted: "true" })).toBe(
      "money in, with no category, matching “pay”, including deleted",
    );
    expect(filterWords({ category_id: "c1" }, "Dining Out")).toBe("in Dining Out");
  });
});

describe("tabLink", () => {
  it("opens the tab each kind is a view of, with the same params", () => {
    const outlook: PanelEvent = { ...base, panel_id: "finance.month_outlook", kind: "finance.month_outlook", params: { month: "2026-10" } };
    const trip: PanelEvent = { ...base, panel_id: "travel.trip_budget:7", kind: "travel.trip_budget", params: { trip_id: 7 } };
    const tx: PanelEvent = { ...base, panel_id: "finance.transactions", kind: "finance.transactions", params: { direction: "out" } };
    expect(tabLink(outlook)).toBe("/accounting?month=2026-10");
    expect(tabLink(trip)).toBe("/travel/trips/7");
    expect(tabLink(tx)).toBe("/accounting/ledger?view=out");
    expect([outlook, trip, tx].map(openLabel)).toEqual(["Open in Money", "Open in Travel", "Open in Ledger"]);
  });
});
