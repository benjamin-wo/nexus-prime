import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import type { PanelEvent } from "../panels/types";
import { PanelStageProvider, usePanelStageContext, type PanelStage as Stage } from "../panels/usePanelStage";
import { mockApi } from "../testing";
import { PanelStage } from "./PanelStage";

const sgd = (amount: number) => ({ amount: amount.toFixed(4), currency: "SGD" });
const budget = { id: "b1", category_id: null, name: "Overall", limit: sgd(3000), spent: sgd(1500), remaining: sgd(1500), percent: 50, unconverted: [] };
const outlook = {
  month: "2026-11", status: "current", currency: "SGD",
  received: sgd(5000), spent: sgd(2000), moved: sgd(0), net_so_far: sgd(3000),
  expected_in: sgd(0), expected_out: sgd(1200), projected_net: sgd(1800),
  overall: sgd(1800), headroom: sgd(1800), shortfall: sgd(0),
  items: [{ day: "2026-11-20", kind: "bill", label: "Rent", direction: "out", amount: sgd(1200) }],
  no_amount: [], unconverted: [],
};
const tx = (id: string, name: string, amount: number) => ({
  id, direction: "out", amount: sgd(amount), occurred_at: "2026-11-10T04:00:00Z", counterparty: name, category_id: "c1",
  notes: null, status: "confirmed", source: "web", deleted: false,
});
const tripDetail = (role: "owner" | "member") => ({
  trip: { id: "5", destination: "Tokyo", days: 5, role, budget: role === "owner" ? sgd(3000) : null },
  items: [],
  spending: role === "owner" ? { spent: sgd(900), left: sgd(2100), percent: 30, before: sgd(0), today: null, per_day: sgd(180), per_day_left: null, categories: [{ name: "Food", planned: null, spent: sgd(400) }], unconverted: 0 } : null,
});

const event = (over: Partial<PanelEvent> & Pick<PanelEvent, "kind" | "params" | "panel_id">): PanelEvent =>
  ({ version: 1, topic: "your dining budget", as_of: "2026-11-15T10:02:00Z", message_id: "m1", ...over }) as PanelEvent;
const budgets = event({ panel_id: "finance.budgets", kind: "finance.budgets", params: { month: "2026-11" } });
const month = event({ panel_id: "finance.month_outlook", kind: "finance.month_outlook", params: { month: "2026-11" }, topic: "this month" });
const trip = event({ panel_id: "travel.trip_budget:5", kind: "travel.trip_budget", params: { trip_id: "5" }, topic: "the Tokyo trip" });

let stage: Stage;
function Probe() {
  stage = usePanelStageContext();
  return null;
}
function renderStage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PanelStageProvider>
          <Probe />
          <PanelStage />
        </PanelStageProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockApi({
    "GET /budgets": () => [budget],
    "GET /month-outlook": () => outlook,
    "GET /transactions": () => ({ items: [tx("t1", "Kopi Corner", 4.5), tx("t2", "Ya Kun", 6)], total: 2 }),
    "GET /categories": () => [{ id: "c1", name: "Dining Out" }],
    "GET /travel/trips/5": () => tripDetail("owner"),
  });
});

describe("PanelStage", () => {
  it("says what it is for when nothing is open", () => {
    renderStage();
    expect(screen.getByText("Ask Nexus about your money or a trip and the right view opens here.")).toBeInTheDocument();
  });

  it("opens a panel with why it opened, its query and when it was read, and announces it without taking focus", async () => {
    renderStage();
    const before = document.activeElement;
    act(() => stage.upsert(budgets));
    const card = await screen.findByRole("article", { name: "Budgets" });
    expect(within(card).getByText("Opened because you asked about your dining budget")).toBeInTheDocument();
    expect(within(card).getByText(/Budgets in November 2026 · as of/)).toBeInTheDocument();
    expect(await within(card).findByText("50% used · SGD 1,500.00 under")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open in Money" })).toHaveAttribute("href", "/accounting/budgets?month=2026-11");
    expect(screen.getByRole("status")).toHaveTextContent("Budgets opened");
    expect(document.activeElement).toBe(before);
  });

  it("shows the newest panel large and the rest as compact cards with one figure", async () => {
    renderStage();
    act(() => stage.upsert(budgets));
    act(() => stage.upsert(month));
    const big = await screen.findByRole("article", { name: "Month outlook" });
    expect(await within(big).findByText("Rent")).toBeInTheDocument();
    const small = screen.getByRole("article", { name: "Budgets" });
    expect(within(small).queryByRole("link")).toBeNull();
    expect(await within(small).findByText("50% used")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Month outlook opened");
    await userEvent.click(within(small).getByRole("button", { name: "Expand Budgets" }));
    expect(within(screen.getByRole("article", { name: "Budgets" })).getByRole("link", { name: "Open in Money" })).toBeInTheDocument();
    expect(within(screen.getByRole("article", { name: "Month outlook" })).queryByRole("link")).toBeNull();
  });

  it("pins, dismisses into Recently closed, and restores", async () => {
    renderStage();
    const user = userEvent.setup();
    act(() => stage.upsert(budgets));
    await user.click(await screen.findByRole("button", { name: "Pin Budgets" }));
    expect(screen.getByRole("button", { name: "Unpin Budgets" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Unpin Budgets" }));
    await user.click(screen.getByRole("button", { name: "Dismiss Budgets" }));
    expect(screen.queryByRole("article")).toBeNull();
    const history = screen.getByRole("region", { name: "Recently closed" });
    expect(within(history).getByText(/your dining budget/)).toBeInTheDocument();
    // Prime does not bring back what was dismissed.
    act(() => stage.upsert(budgets));
    expect(screen.queryByRole("article")).toBeNull();
    await user.click(within(history).getByRole("button", { name: /Reopen Budgets/ }));
    expect(await screen.findByRole("article", { name: "Budgets" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Recently closed" })).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Budgets opened");
  });

  it("collapses a panel to its title and headline", async () => {
    renderStage();
    act(() => stage.upsert(month));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Collapse Month outlook" }));
    const card = screen.getByRole("article", { name: "Month outlook" });
    expect(await within(card).findByText("left by month end")).toBeInTheDocument();
    expect(within(card).queryByText("Rent")).toBeNull();
  });

  it("marks a panel touched when the person works in it, so Prime opens the next one beside it", async () => {
    renderStage();
    act(() => stage.upsert(budgets));
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Transactions" }));
    expect(stage.state.panels[0].touched).toBe(true);
    act(() => stage.upsert(event({ panel_id: "finance.budgets", kind: "finance.budgets", params: { month: "2026-10" } })));
    expect(stage.state.panels.map((p) => p.id)).toEqual(["finance.budgets", "finance.budgets#2"]);
  });

  it("lists matching transactions with the count, a total and a link to the Ledger carrying the filters", async () => {
    renderStage();
    act(() =>
      stage.upsert(
        event({ panel_id: "finance.transactions", kind: "finance.transactions", params: { direction: "out", category_id: "c1", start: "2026-11-01", end: "2026-11-30" }, topic: "Dining Out, 1–30 Nov" }),
      ),
    );
    const card = await screen.findByRole("article", { name: "Transactions" });
    expect(await within(card).findByText("2 transactions")).toBeInTheDocument();
    expect(within(card).getByText(/SGD 10\.50 out/)).toBeInTheDocument();
    expect(within(card).getByText("Kopi Corner")).toBeInTheDocument();
    expect(await within(card).findByText(/money out, in Dining Out, .*1.* to .*30/)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open in Ledger" })).toHaveAttribute(
      "href",
      "/accounting/ledger?view=out&category=c1&start=2026-11-01&end=2026-11-30",
    );
  });

  it("shows a trip's budget to its owner", async () => {
    renderStage();
    act(() => stage.upsert(trip));
    const card = await screen.findByRole("article", { name: "Trip budget" });
    expect(await within(card).findByText("SGD 900.00")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open in Travel" })).toHaveAttribute("href", "/travel/trips/5");
    expect(within(card).getByText(/Budget and spending for Tokyo/)).toBeInTheDocument();
  });

  it("shows no figures to a member of the trip", async () => {
    mockApi({ "GET /travel/trips/5": () => tripDetail("member") });
    renderStage();
    act(() => stage.upsert(trip));
    const card = await screen.findByRole("article", { name: "Trip budget" });
    expect(await within(card).findByText("Only the trip's owner can see its money.")).toBeInTheDocument();
    expect(within(card).queryByText(/SGD/)).toBeNull();
  });

  it("shows no figures when the server refuses", async () => {
    mockApi({ "GET /travel/trips/5": () => new Response(JSON.stringify({ detail: "not your trip" }), { status: 403 }) });
    renderStage();
    act(() => stage.upsert(trip));
    const card = await screen.findByRole("article", { name: "Trip budget" });
    expect(await within(card).findByText("Only the trip's owner can see its money.")).toBeInTheDocument();
    expect(within(card).queryByText(/SGD/)).toBeNull();
  });

  it("says when a panel could not load", async () => {
    mockApi({ "GET /budgets": () => new Response("{}", { status: 500 }) });
    renderStage();
    act(() => stage.upsert(budgets));
    expect(await screen.findByText("Couldn't load the budgets.")).toBeInTheDocument();
  });
});

