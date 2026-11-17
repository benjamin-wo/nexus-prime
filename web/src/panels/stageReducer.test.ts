import { describe, expect, it } from "vitest";

import { initialStageState, MAX_VISIBLE, stageReducer, type StageAction, type StageState } from "./stageReducer";
import type { PanelEvent } from "./types";

const outlook = (month: string, topic = `Outlook ${month}`): PanelEvent => ({
  panel_id: "finance.month_outlook",
  kind: "finance.month_outlook",
  version: 1,
  params: { month },
  topic,
  as_of: "2026-11-15T10:00:00Z",
  message_id: `m-${month}`,
});
const budgets = (month = "2026-11"): PanelEvent => ({
  panel_id: "finance.budgets",
  kind: "finance.budgets",
  version: 1,
  params: { month },
  topic: `Budgets ${month}`,
  as_of: "2026-11-15T10:00:00Z",
  message_id: `m-b-${month}`,
});
const transactions = (category = "dining"): PanelEvent => ({
  panel_id: "finance.transactions",
  kind: "finance.transactions",
  version: 1,
  params: { category },
  topic: `Transactions ${category}`,
  as_of: "2026-11-15T10:00:00Z",
  message_id: `m-${category}`,
});
const trip = (id: string): PanelEvent => ({
  panel_id: `travel.trip_budget:${id}`,
  kind: "travel.trip_budget",
  version: 1,
  params: { trip_id: id },
  topic: `Trip ${id}`,
  as_of: "2026-11-15T10:00:00Z",
  message_id: `m-trip-${id}`,
});

let clock = 0;
const up = (event: PanelEvent): StageAction => ({ type: "upsert", event, now: ++clock });
const restore = (id: string): StageAction => ({ type: "restore", id, now: ++clock });
const run = (...actions: StageAction[]): StageState => actions.reduce(stageReducer, initialStageState);

const ids = (s: StageState) => s.panels.map((p) => p.id);
const historyIds = (s: StageState) => s.history.map((p) => p.id);
const expandedIds = (s: StageState) => s.panels.filter((p) => p.expanded).map((p) => p.id);
const get = (s: StageState, id: string) => s.panels.find((p) => p.id === id)!;

describe("upsert", () => {
  it("opens a new panel, expanded", () => {
    const s = run(up(outlook("2026-11")));
    expect(ids(s)).toEqual(["finance.month_outlook"]);
    expect(get(s, "finance.month_outlook")).toMatchObject({ status: "open", expanded: true, touched: false });
    expect(s.history).toEqual([]);
  });

  it("same key, new month updates in place and keeps its position", () => {
    const s = run(up(outlook("2026-11")), up(budgets()), up(outlook("2026-10", "October")));
    expect(ids(s)).toEqual(["finance.month_outlook", "finance.budgets"]);
    const panel = get(s, "finance.month_outlook");
    expect(panel.event.params).toEqual({ month: "2026-10" });
    expect(panel.event.topic).toBe("October");
    expect(panel.openedAt).toBeLessThan(panel.updatedAt);
    // The updated panel is the newest upsert, so it is the expanded one.
    expect(expandedIds(s)).toEqual(["finance.month_outlook"]);
  });

  it("an unpinned but touched panel is not changed: the new one opens beside it", () => {
    const s = run(up(outlook("2026-11")), { type: "touch", id: "finance.month_outlook" }, up(outlook("2026-10")));
    expect(ids(s)).toEqual(["finance.month_outlook", "finance.month_outlook#2"]);
    expect(get(s, "finance.month_outlook").event.params).toEqual({ month: "2026-11" });
    expect(get(s, "finance.month_outlook#2").event.params).toEqual({ month: "2026-10" });
    expect(get(s, "finance.month_outlook#2").event.panel_id).toBe("finance.month_outlook");
  });

  it("a pinned panel is not changed: the new one opens beside it", () => {
    const s = run(up(outlook("2026-11")), { type: "pin", id: "finance.month_outlook" }, up(outlook("2026-10")));
    expect(ids(s)).toEqual(["finance.month_outlook", "finance.month_outlook#2"]);
    expect(get(s, "finance.month_outlook").event.params).toEqual({ month: "2026-11" });
  });

  it("further upserts of the slot update the beside panel in place, and a second pin opens #3", () => {
    const s1 = run(up(outlook("2026-11")), { type: "pin", id: "finance.month_outlook" }, up(outlook("2026-10")), up(outlook("2026-09")));
    expect(ids(s1)).toEqual(["finance.month_outlook", "finance.month_outlook#2"]);
    expect(get(s1, "finance.month_outlook#2").event.params).toEqual({ month: "2026-09" });
    const s2 = stageReducer(stageReducer(s1, { type: "pin", id: "finance.month_outlook#2" }), up(outlook("2026-08")));
    expect(ids(s2)).toEqual(["finance.month_outlook", "finance.month_outlook#2", "finance.month_outlook#3"]);
  });

  it("unpinning makes a panel updatable again (if untouched)", () => {
    const s = run(up(outlook("2026-11")), { type: "pin", id: "finance.month_outlook" }, { type: "unpin", id: "finance.month_outlook" }, up(outlook("2026-10")));
    expect(ids(s)).toEqual(["finance.month_outlook"]);
    expect(get(s, "finance.month_outlook").event.params).toEqual({ month: "2026-10" });
  });

  it("does not reopen a dismissed slot; the newest data waits in history", () => {
    const s = run(up(outlook("2026-11")), { type: "dismiss", id: "finance.month_outlook" }, up(outlook("2026-10")));
    expect(s.panels).toEqual([]);
    expect(historyIds(s)).toEqual(["finance.month_outlook"]);
    expect(s.history[0]).toMatchObject({ status: "dismissed", closedBy: "user" });
    expect(s.history[0].event.params).toEqual({ month: "2026-10" });
  });

  it("a pinned panel's slot, with a dismissed sibling, still opens beside the pinned one", () => {
    const s = run(
      up(outlook("2026-11")),
      { type: "pin", id: "finance.month_outlook" },
      up(outlook("2026-10")),
      { type: "dismiss", id: "finance.month_outlook#2" },
      up(outlook("2026-09")),
    );
    expect(ids(s)).toEqual(["finance.month_outlook", "finance.month_outlook#3"]);
  });
});

describe("restore", () => {
  it("reopens a dismissed panel with its newest data, expanded", () => {
    const s = run(
      up(outlook("2026-11")),
      { type: "dismiss", id: "finance.month_outlook" },
      up(outlook("2026-10")),
      restore("finance.month_outlook"),
    );
    expect(ids(s)).toEqual(["finance.month_outlook"]);
    expect(s.history).toEqual([]);
    expect(get(s, "finance.month_outlook")).toMatchObject({ status: "open", expanded: true });
    expect(get(s, "finance.month_outlook").event.params).toEqual({ month: "2026-10" });
    expect(get(s, "finance.month_outlook").closedBy).toBeUndefined();
  });

  it("is a no-op for an id not in history", () => {
    const s = run(up(outlook("2026-11")));
    expect(stageReducer(s, restore("nope"))).toBe(s);
  });

  it("does not push out a pinned panel; with four pinned it stays in history", () => {
    const pins: StageAction[] = ["1", "2", "3", "4"].flatMap((id): StageAction[] => [up(trip(id)), { type: "pin", id: `travel.trip_budget:${id}` }]);
    const s = run(up(budgets()), { type: "dismiss", id: "finance.budgets" }, ...pins);
    expect(ids(s)).toHaveLength(4);
    expect(stageReducer(s, restore("finance.budgets"))).toBe(s);
  });
});

describe("budget", () => {
  const four = [up(outlook("2026-11")), up(budgets()), up(transactions()), up(trip("1"))];

  it("keeps at most one expanded: the newest upsert", () => {
    const s = run(...four);
    expect(expandedIds(s)).toEqual(["travel.trip_budget:1"]);
    expect(s.panels.map((p) => p.expanded)).toEqual([false, false, false, true]);
  });

  it("keeps a pinned expanded panel expanded; the newest opens compact", () => {
    const s = run(up(outlook("2026-11")), { type: "pin", id: "finance.month_outlook" }, up(budgets()));
    expect(expandedIds(s)).toEqual(["finance.month_outlook"]);
    expect(get(s, "finance.budgets").expanded).toBe(false);
  });

  it("an update in place does not steal the expanded slot from a pinned panel", () => {
    const s = run(up(outlook("2026-11")), up(budgets()), { type: "pin", id: "finance.budgets" }, up(outlook("2026-10")));
    expect(expandedIds(s)).toEqual(["finance.budgets"]);
  });

  it("expand and collapse are the person's choice", () => {
    let s = run(...four);
    s = stageReducer(s, { type: "expand", id: "finance.budgets" });
    expect(expandedIds(s)).toEqual(["finance.budgets"]);
    s = stageReducer(s, { type: "collapse", id: "finance.budgets" });
    expect(expandedIds(s)).toEqual([]);
    // Nothing expanded: the next upsert takes the slot.
    s = stageReducer(s, up(outlook("2026-10")));
    expect(expandedIds(s)).toEqual(["finance.month_outlook"]);
  });

  it("allows four visible; the fifth pushes the oldest unpinned panel to history", () => {
    const s = run(...four, up(trip("2")));
    expect(s.panels).toHaveLength(MAX_VISIBLE);
    expect(ids(s)).toEqual(["finance.budgets", "finance.transactions", "travel.trip_budget:1", "travel.trip_budget:2"]);
    expect(historyIds(s)).toEqual(["finance.month_outlook"]);
    expect(s.history[0]).toMatchObject({ status: "dismissed", closedBy: "budget", expanded: false });
    expect(expandedIds(s)).toEqual(["travel.trip_budget:2"]);
  });

  it("skips pinned panels when pushing one out", () => {
    const s = run(...four, { type: "pin", id: "finance.month_outlook" }, { type: "pin", id: "finance.budgets" }, up(trip("2")));
    expect(ids(s)).toEqual(["finance.month_outlook", "finance.budgets", "travel.trip_budget:1", "travel.trip_budget:2"]);
    expect(historyIds(s)).toEqual(["finance.transactions"]);
  });

  it("with four pinned, the new panel goes straight to history", () => {
    const pins = ["1", "2", "3", "4"].flatMap((id): StageAction[] => [up(trip(id)), { type: "pin", id: `travel.trip_budget:${id}` }]);
    const s = run(...pins, up(outlook("2026-11")));
    expect(ids(s)).toEqual(["travel.trip_budget:1", "travel.trip_budget:2", "travel.trip_budget:3", "travel.trip_budget:4"]);
    expect(historyIds(s)).toEqual(["finance.month_outlook"]);
  });

  it("a panel pushed out by the budget (not dismissed) reopens on a later upsert", () => {
    const s = run(...four, up(trip("2")), up(outlook("2026-10")));
    expect(ids(s)).toContain("finance.month_outlook");
    expect(get(s, "finance.month_outlook").event.params).toEqual({ month: "2026-10" });
    expect(s.history.filter((h) => h.id === "finance.month_outlook")).toEqual([]);
    expect(s.panels).toHaveLength(MAX_VISIBLE);
  });
});

describe("pin, unpin, touch, dismiss", () => {
  it("each changes only its panel", () => {
    let s = run(up(outlook("2026-11")), up(budgets()));
    s = stageReducer(s, { type: "pin", id: "finance.budgets" });
    expect(get(s, "finance.budgets").status).toBe("pinned");
    expect(get(s, "finance.month_outlook").status).toBe("open");
    s = stageReducer(s, { type: "unpin", id: "finance.budgets" });
    expect(get(s, "finance.budgets").status).toBe("open");
    s = stageReducer(s, { type: "touch", id: "finance.budgets" });
    expect(get(s, "finance.budgets").touched).toBe(true);
    expect(get(s, "finance.month_outlook").touched).toBe(false);
  });

  it("dismiss moves a pinned panel to history as dismissed, collapsed, newest first", () => {
    let s = run(up(outlook("2026-11")), up(budgets()), { type: "pin", id: "finance.budgets" });
    s = stageReducer(stageReducer(s, { type: "dismiss", id: "finance.month_outlook" }), { type: "dismiss", id: "finance.budgets" });
    expect(s.panels).toEqual([]);
    expect(historyIds(s)).toEqual(["finance.budgets", "finance.month_outlook"]);
    expect(s.history[0]).toMatchObject({ status: "dismissed", expanded: false, closedBy: "user" });
  });

  it("unknown ids change nothing", () => {
    const s = run(up(outlook("2026-11")));
    for (const type of ["pin", "unpin", "dismiss", "expand", "collapse", "touch"] as const) {
      expect(stageReducer(s, { type, id: "nope" })).toBe(s);
    }
  });
});

describe("reset", () => {
  it("empties the stage and the history", () => {
    const s = run(up(outlook("2026-11")), { type: "dismiss", id: "finance.month_outlook" }, up(budgets()), { type: "reset" });
    expect(s).toEqual(initialStageState);
  });
});
