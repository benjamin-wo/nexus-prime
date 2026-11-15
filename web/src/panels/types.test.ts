import { describe, expect, it } from "vitest";

import { KNOWN_KINDS, PANEL_VERSION, parsePanelEvent } from "./types";

const base = { version: 1, topic: "t", as_of: "2026-11-15T10:00:00Z", message_id: "m1" };
const outlook = { ...base, panel_id: "finance.month_outlook", kind: "finance.month_outlook", params: { month: "2026-11" } };

describe("parsePanelEvent", () => {
  it("accepts each known kind", () => {
    expect(PANEL_VERSION).toBe(1);
    expect(KNOWN_KINDS).toHaveLength(4);
    const good = [
      outlook,
      { ...base, panel_id: "finance.budgets", kind: "finance.budgets", params: { month: "2026-10" } },
      { ...base, panel_id: "finance.transactions", kind: "finance.transactions", params: { category: "dining", start: "2026-10-01" } },
      { ...base, panel_id: "finance.transactions", kind: "finance.transactions", params: {} },
      { ...base, panel_id: "travel.trip_budget:7", kind: "travel.trip_budget", params: { trip_id: "7" } },
      { ...base, panel_id: "travel.trip_budget:7", kind: "travel.trip_budget", params: { trip_id: 7 } },
    ];
    for (const raw of good) expect(parsePanelEvent(raw)).toEqual(raw);
  });

  it("drops extra fields", () => {
    expect(parsePanelEvent({ ...outlook, extra: 1 })).toEqual(outlook);
  });

  it.each<[string, unknown]>([
    ["not an object", "x"],
    ["null", null],
    ["an array", []],
    ["unknown kind", { ...outlook, kind: "finance.cash_flow" }],
    ["unknown version", { ...outlook, version: 2 }],
    ["missing version", { ...outlook, version: undefined }],
    ["empty panel_id", { ...outlook, panel_id: "" }],
    ["missing topic", { ...outlook, topic: undefined }],
    ["missing message_id", { ...outlook, message_id: 3 }],
    ["bad as_of", { ...outlook, as_of: "yesterday" }],
    ["params not an object", { ...outlook, params: "2026-11" }],
    ["bad month", { ...outlook, params: { month: "2026-13" } }],
    ["missing month", { ...outlook, params: {} }],
    ["transactions filter with a number", { ...base, panel_id: "finance.transactions", kind: "finance.transactions", params: { min: 5 } }],
    ["trip_budget without trip_id", { ...base, panel_id: "travel.trip_budget:1", kind: "travel.trip_budget", params: {} }],
  ])("drops %s", (_name, raw) => {
    expect(parsePanelEvent(raw)).toBeNull();
  });
});
