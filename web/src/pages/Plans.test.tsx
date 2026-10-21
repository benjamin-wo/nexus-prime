import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { PlanBrief, PlanDetail } from "../api";
import { formatShortDate, priceWhen } from "../format";
import { mockApi } from "../testing";
import { PlanPage, PlansPage } from "./Plans";

// Made-up plans for a made-up stock.
const brief: PlanBrief = {
  id: "p2",
  symbol: "ACME",
  verdict: "wait",
  verdict_text: "Wait for a dip to buy",
  headline: "ACME: Wait for a dip to buy",
  reason: "It's above the buy zone.",
  summary_line: "ACME: Wait for a pullback.",
  created_at: "2026-10-14T09:00:00Z",
  valid_until: "2026-10-28",
  expired: false,
  status: "open",
  entered_on: null,
  outcome_day: null,
  outcome_price: null,
  result_percent: null,
  alerts: true,
  followed: true,
  keep_fresh: false,
  refreshed_from: null,
  price: "182.40",
  price_at: "2026-10-14T21:42:00Z",
  price_kind: "live",
};

function detail(over: Partial<PlanBrief> = {}, notes: string[] = [], replacedBy: PlanDetail["replaced_by"] = null): PlanDetail {
  return {
    brief: { ...brief, ...over },
    replaced_by: replacedBy,
    closes: [],
    plan: {
      symbol: "ACME",
      as_of: "2026-10-13",
      close: "180.10",
      verdict: "wait",
      verdict_text: "Wait for a dip to buy",
      reason: "It's above the buy zone.",
      entry_low: "170.00",
      entry_high: "172.00",
      entry_why: "20-day average",
      stop: "165.00",
      risk: "5.00",
      targets: [{ price: "190.00", reward_risk: "2.5", why: "resistance" }],
      valid_until: "2026-10-28",
      earnings_in_window: null,
      trend: null,
      held: null,
      held_gain_percent: null,
      levels: [],
      technical: "A steady climb.",
      news: [],
      risks: [],
      bull: [],
      bear: [],
      summary: "Wait for a pullback.",
      invalidation: "A close below 165.00.",
      sources: [],
      notes,
    },
  };
}

function renderPlan(id = "p2") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/investment/plans/${id}`]}>
        <Routes>
          <Route path="/investment/plans/:id" element={<PlanPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderList() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PlansPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const record = { finished: 0, targets: 0, stopped: 0, expired: 0, never_entered: 0, average_result: null, open: 1, odds_plans: 0, odds_said: null, odds_happened: null, text: "" };

describe("the plan page's price line", () => {
  it("shows the price the plan was written with and when it was live", async () => {
    mockApi({ "GET /investments/plans/p2": () => detail() });
    renderPlan();
    expect(await screen.findByText("Price 182.40")).toBeInTheDocument();
    expect(screen.getByText(/^Live · /)).toBeInTheDocument();
  });

  it("calls a close a close", async () => {
    mockApi({ "GET /investments/plans/p2": () => detail({ price_kind: "close", price_at: null }) });
    renderPlan();
    expect(await screen.findByText("Price 182.40")).toBeInTheDocument();
    expect(screen.getByText(priceWhen("close", null, "2026-10-13"))).toBeInTheDocument();
  });

  it("is left out on a plan made before prices were kept", async () => {
    mockApi({ "GET /investments/plans/p2": () => detail({ price: null, price_at: null, price_kind: null }) });
    renderPlan();
    await screen.findByRole("heading", { name: "ACME plan" });
    expect(screen.queryByText(/^Price /)).not.toBeInTheDocument();
  });
});

describe("Keep this plan fresh", () => {
  it("is an off switch on an open plan, with what it does", async () => {
    mockApi({ "GET /investments/plans/p2": () => detail() });
    renderPlan();
    const toggle = await screen.findByRole("checkbox", { name: "Keep this plan fresh" });
    expect(toggle).not.toBeChecked();
    expect(toggle).toHaveAccessibleDescription("Nexus re-runs it when the price moves a lot, after earnings, or once a week.");
  });

  it("turns on at once, tells the server and reads the plan and the list again", async () => {
    let fresh = false;
    const calls = mockApi({
      "GET /investments/plans/p2": () => detail({ keep_fresh: fresh }),
      "GET /investments/plans": () => [{ ...brief, keep_fresh: fresh }],
      "PUT /investments/plans/p2/keep-fresh": (body) => {
        fresh = (body as { on: boolean }).on;
        return new Response(null, { status: 204 });
      },
    });
    renderPlan();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Keep this plan fresh" }));
    expect(screen.getByRole("checkbox", { name: "Keep this plan fresh" })).toBeChecked();
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.path === "/investments/plans/p2")).toHaveLength(2));
    expect(calls).toContainEqual({ method: "PUT", path: "/investments/plans/p2/keep-fresh", body: { on: true } });
    expect(screen.getByRole("checkbox", { name: "Keep this plan fresh" })).toBeChecked();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("goes back and says why when the server refuses", async () => {
    mockApi({
      "GET /investments/plans/p2": () => detail(),
      "PUT /investments/plans/p2/keep-fresh": () =>
        new Response(JSON.stringify({ detail: "that plan has finished; ask for a fresh plan to keep fresh" }), { status: 422 }),
    });
    renderPlan();
    await userEvent.click(await screen.findByRole("checkbox", { name: "Keep this plan fresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("that plan has finished");
    expect(screen.getByRole("checkbox", { name: "Keep this plan fresh" })).not.toBeChecked();
  });

  it("isn't offered on a plan that has finished or been replaced", async () => {
    mockApi({
      "GET /investments/plans/p2": () => detail({ status: "refreshed", outcome_day: null }),
      "GET /investments/plans": () => [],
    });
    renderPlan();
    await screen.findByRole("heading", { name: "ACME plan" });
    expect(screen.queryByRole("checkbox", { name: "Keep this plan fresh" })).not.toBeInTheDocument();
  });
});

describe("a plan and the one it replaced", () => {
  it("links back to the plan it was refreshed from", async () => {
    mockApi({ "GET /investments/plans/p2": () => detail({ refreshed_from: { id: "p1", created_at: "2026-10-07T09:00:00Z" } }) });
    renderPlan();
    const link = await screen.findByRole("link", { name: `Refreshed from the plan of ${formatShortDate("2026-10-07T09:00:00Z")}` });
    expect(link).toHaveAttribute("href", "/investment/plans/p1");
  });

  it("has no such line on a first plan", async () => {
    mockApi({ "GET /investments/plans/p2": () => detail() });
    renderPlan();
    await screen.findByRole("heading", { name: "ACME plan" });
    expect(screen.queryByText(/Refreshed from/)).not.toBeInTheDocument();
  });

  it("is labelled Refreshed and points to the newer plan the detail names", async () => {
    const calls = mockApi({
      "GET /investments/plans/p1": () => detail({ id: "p1", status: "refreshed" }, [], { id: "p2", created_at: "2026-10-14T09:00:00Z" }),
    });
    renderPlan("p1");
    expect(await screen.findByText("🔄 Refreshed")).toBeInTheDocument();
    const link = await screen.findByRole("link", { name: "A newer plan replaced this one" });
    expect(link).toHaveAttribute("href", "/investment/plans/p2");
    // It doesn't go looking through the plans list for it.
    expect(calls.some((c) => c.path === "/investments/plans")).toBe(false);
  });

  it("is just the label when nothing replaced it", async () => {
    mockApi({ "GET /investments/plans/p1": () => detail({ id: "p1", status: "refreshed" }) });
    renderPlan("p1");
    expect(await screen.findByText("🔄 Refreshed")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "A newer plan replaced this one" })).not.toBeInTheDocument();
  });

  it("points to a plan asked for by hand over it, whatever its own status", async () => {
    mockApi({
      "GET /investments/plans/p1": () => detail({ id: "p1", status: "open" }, [], { id: "p3", created_at: "2026-10-15T09:00:00Z" }),
    });
    renderPlan("p1");
    const link = await screen.findByRole("link", { name: "A newer plan replaced this one" });
    expect(link).toHaveAttribute("href", "/investment/plans/p3");
  });
});

describe("the plan's notes", () => {
  it("shows what the backend wrote about the price, once each", async () => {
    mockApi({ "GET /investments/plans/p2": () => detail({}, ["The price is already under the buy zone: 168.20 now, buy zone 170.00 to 172.00."]) });
    renderPlan();
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("⚠️ The price is already under the buy zone");
    expect(screen.getAllByText(/already under the buy zone/)).toHaveLength(1);
  });
});

describe("the plans list", () => {
  it("is called Trade plans, and a single plan links back to it", async () => {
    mockApi({
      "GET /investments/plans/record": () => record,
      "GET /investments/plans": () => [{ ...brief, headline: "ACME: wait" }],
    });
    renderList();
    expect(screen.getByRole("heading", { name: "Trade plans", level: 1 })).toBeInTheDocument();
    expect(await screen.findByRole("list", { name: "Trade plans" })).toBeInTheDocument();
    cleanup();
    mockApi({ "GET /investments/plans/p2": () => detail() });
    renderPlan();
    expect(await screen.findByRole("heading", { name: "ACME plan", level: 1 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Trade plans" })).toHaveAttribute("href", "/investment/plans");
  });

  it("tags open plans that keep themselves fresh, and labels the replaced ones", async () => {
    mockApi({
      "GET /investments/plans/record": () => record,
      "GET /investments/plans": () => [
        { ...brief, id: "p3", headline: "ACME: kept fresh", keep_fresh: true, refreshed_from: { id: "p1", created_at: "2026-10-07T09:00:00Z" } },
        { ...brief, id: "p4", headline: "BOLT: plain", keep_fresh: false },
        { ...brief, id: "p1", headline: "ACME: replaced", status: "refreshed", keep_fresh: false },
      ],
    });
    renderList();
    const fresh = await screen.findByRole("link", { name: /ACME: kept fresh/ });
    expect(fresh).toHaveTextContent("Fresh");
    expect(screen.getByRole("link", { name: /BOLT: plain/ })).not.toHaveTextContent("Fresh");
    const replaced = screen.getByRole("link", { name: /ACME: replaced/ });
    expect(replaced).toHaveTextContent("🔄 Refreshed");
    expect(replaced).not.toHaveTextContent("Fresh");
  });

  it("doesn't tag a finished plan as fresh", async () => {
    mockApi({
      "GET /investments/plans/record": () => record,
      "GET /investments/plans": () => [{ ...brief, headline: "ACME: done", status: "target", outcome_day: "2026-10-20", keep_fresh: true }],
    });
    renderList();
    expect(await screen.findByRole("link", { name: /ACME: done/ })).not.toHaveTextContent("Fresh");
  });
});
