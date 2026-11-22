import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Holding, Portfolio } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { InvestmentPage } from "./Investment";

const acme: Holding = {
  symbol: "NVDA",
  quantity: "10",
  average_cost: { amount: "150.00", currency: "USD" },
  cost: { amount: "1500.00", currency: "USD" },
  updated_at: "2026-10-20T12:00:00Z",
  price: { amount: "182.40", currency: "USD" },
  price_day: "2026-10-20",
  price_kind: "close",
  price_at: null,
  value: { amount: "1824.00", currency: "USD" },
  gain: { amount: "324.00", currency: "USD" },
  gain_percent: "21.6",
  day_change: null,
  day_percent: null,
  value_home: null,
  earnings: null,
};

const totals: Portfolio["totals"] = {
  value: null,
  cost: null,
  gain: null,
  gain_percent: null,
  day_change: null,
  day_percent: null,
  as_of: null,
  as_of_at: null,
  price_kind: "close",
  missing: [],
  realised: null,
  dividends: null,
  total_return: null,
};

function open(extra: Record<string, () => unknown> = {}) {
  let holdings = [acme];
  const calls = mockApi({
    "GET /investments": () => ({ holdings, totals, draft: null, screenshots: false, prices: true }),
    "GET /investments/trades": () => [],
    "GET /investments/dividends": () => ({ received: [], expected: [] }),
    "DELETE /investments/holdings/NVDA": () => {
      holdings = [];
      return undefined;
    },
    "PUT /investments/holdings/MSFT": () => undefined,
    "POST /investments/trades": () => ({}),
    ...extra,
  });
  renderWithProviders(<InvestmentPage />);
  return calls;
}

afterEach(() => vi.restoreAllMocks());

/** Opens the holding's sheet, where Edit and Remove are. */
async function openHolding(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /^NVDA, 10 shares/ }));
  return screen.getByRole("dialog", { name: "NVDA" });
}

describe("changing the portfolio", () => {
  it("asks before removing a holding, in the page, and says it was removed", async () => {
    const dialog = vi.spyOn(window, "confirm");
    const calls = open();
    const user = userEvent.setup();
    await user.click(within(await openHolding(user)).getByRole("button", { name: "Remove NVDA" }));
    const ask = screen.getByRole("group", { name: "Remove NVDA" });
    expect(ask).toHaveTextContent("Remove NVDA from your holdings?");
    // Nothing has been sent, and Keep puts the sheet back as it was.
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(within(ask).getByRole("button", { name: "Keep" }));
    expect(screen.queryByRole("group", { name: "Remove NVDA" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Remove NVDA" }));
    await user.click(within(screen.getByRole("group", { name: "Remove NVDA" })).getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Removed NVDA");
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(1));
    expect(await screen.findByRole("status")).toHaveTextContent("Removed NVDA");
    expect(dialog).not.toHaveBeenCalled();
  });

  it("keeps the holding and says why when it can't be removed", async () => {
    open({ "DELETE /investments/holdings/NVDA": () => new Response(JSON.stringify({ detail: "Try again in a moment" }), { status: 500 }) });
    const user = userEvent.setup();
    await user.click(within(await openHolding(user)).getByRole("button", { name: "Remove NVDA" }));
    await user.click(within(screen.getByRole("group", { name: "Remove NVDA" })).getByRole("button", { name: "Remove" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove NVDA" })).toBeInTheDocument();
  });

  it("edits a holding in its sheet, says Updated, and closes the sheet", async () => {
    const calls = open({ "PUT /investments/holdings/NVDA": () => undefined });
    const user = userEvent.setup();
    await user.click(within(await openHolding(user)).getByRole("button", { name: "Edit NVDA" }));
    const form = screen.getByRole("form", { name: "Edit NVDA" });
    await user.clear(within(form).getByLabelText("Shares"));
    await user.type(within(form).getByLabelText("Shares"), "12");
    await user.click(within(form).getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Updated NVDA");
    expect(calls.some((c) => c.method === "PUT" && c.path === "/investments/holdings/NVDA")).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says Added MSFT after adding a holding by hand", async () => {
    const calls = open();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Add one by hand" }));
    const form = await screen.findByRole("form", { name: "Add a holding" });
    await user.type(within(form).getByLabelText("Ticker"), "msft");
    await user.type(within(form).getByLabelText("Shares"), "3");
    await user.type(within(form).getByLabelText(/Avg cost/), "400");
    await user.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added MSFT");
    expect(calls.some((c) => c.method === "PUT" && c.path === "/investments/holdings/MSFT")).toBe(true);
  });

  it("says what a recorded trade was", async () => {
    open();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Record a trade" }));
    const form = await screen.findByRole("form", { name: "Record a trade" });
    await user.selectOptions(within(form).getByLabelText("Side"), "sell");
    await user.type(within(form).getByLabelText("Ticker"), "nvda");
    await user.type(within(form).getByLabelText("Shares"), "4");
    await user.click(within(form).getByRole("button", { name: "Record" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Recorded: sold 4 NVDA");
  });
});
