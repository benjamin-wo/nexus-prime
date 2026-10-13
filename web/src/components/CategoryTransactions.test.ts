import { describe, expect, it } from "vitest";

import { categoryFilters, ledgerLink } from "./CategoryTransactions";

const period = { start: "2026-10-01", end: "2026-10-13" };

describe("categoryFilters", () => {
  it("counts confirmed money out, like the totals", () => {
    expect(categoryFilters({ category: "c1", ...period })).toEqual({
      direction: "out",
      status: "confirmed",
      ...period,
      category_id: "c1",
    });
  });

  it("asks for uncategorised spending when the category is null", () => {
    expect(categoryFilters({ category: null, ...period })).toMatchObject({ uncategorized: true });
    expect(categoryFilters({ category: null, ...period })).not.toHaveProperty("category_id");
  });

  it("leaves the category out for an overall budget", () => {
    const filters = categoryFilters({ category: undefined, ...period });
    expect(filters).not.toHaveProperty("category_id");
    expect(filters).not.toHaveProperty("uncategorized");
  });
});

describe("ledgerLink", () => {
  it("carries the category, period and money-out view", () => {
    const url = new URL(ledgerLink({ category: "c1", ...period }), "https://example.test");
    expect(url.pathname).toBe("/accounting/ledger");
    expect(Object.fromEntries(url.searchParams)).toEqual({ view: "out", ...period, category: "c1" });
  });

  it("names uncategorised as none, and drops the category for everything", () => {
    expect(ledgerLink({ category: null, ...period })).toContain("category=none");
    expect(ledgerLink({ category: undefined, ...period })).not.toContain("category=");
  });
});
