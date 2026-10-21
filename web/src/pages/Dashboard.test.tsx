import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me, Spending, Summary } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { Dashboard, SpendingChart } from "./Dashboard";

const me: Me = {
  user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "csrf",
};
const sgd = (amount: string) => ({ amount, currency: "SGD" });

const month = (month: string, amount: string, to_date = false) => ({ month, spent: sgd(amount), to_date });
const spending = (over: Partial<Spending> = {}): Spending => ({
  currency: "SGD",
  months: [
    month("2026-05-01", "1800.00"),
    month("2026-06-01", "2100.00"),
    month("2026-07-01", "1500.00"),
    month("2026-08-01", "2600.00"),
    month("2026-09-01", "1900.00"),
    month("2026-10-01", "700.00", true),
  ],
  last_month_to_date: sgd("1000.00"),
  budget: null,
  ...over,
});

const summary: Summary = {
  start: "2026-10-01",
  end: "2026-10-31",
  currency: "SGD",
  totals: [
    { direction: "out", total: sgd("700.00"), count: 8, converted: [], unconverted: [] },
    { direction: "in", total: sgd("5000.00"), count: 1, converted: [], unconverted: [] },
  ],
  by_category: [{ category_id: "food", category_name: "Dining Out", total: sgd("300.00"), count: 5 }],
};

function serve(over: { spending?: Spending; budgets?: unknown[] } = {}) {
  mockApi({
    "GET /summary": () => summary,
    "GET /spending/months": () => over.spending ?? spending(),
    "GET /budgets": () => over.budgets ?? [],
    "GET /transactions": () => ({ items: [], next_cursor: null }),
    "GET /ious": () => [],
    "GET /wallets": () => [],
  });
}

const renderOverview = () => renderWithProviders(<Dashboard me={me} onLog={() => {}} onAsk={() => {}} />);

describe("the spending chart", () => {
  it("is on the Accounting overview, near Where it went, with six months and this month so far last", async () => {
    serve();
    renderOverview();
    const card = await screen.findByRole("region", { name: "Spending by month" });
    const bars = await within(card).findByRole("list", { name: "Spending by month" });
    const months = within(bars).getAllByRole("listitem");
    expect(months).toHaveLength(6);
    expect(months[5]).toHaveTextContent(/Oct so far: SGD.700\.00/);
    expect(months[0]).toHaveTextContent(/May: SGD.1,800\.00/);
    // Where it went sits beside it, in the same column.
    const went = screen.getByRole("region", { name: "Where it went" });
    expect(went.parentElement).toBe(card.parentElement);
  });

  it("has the tiles under it: money received without a budget, and a usual month", async () => {
    serve();
    renderOverview();
    const card = await screen.findByRole("region", { name: "Spending by month" });
    await waitFor(() => expect(card).toHaveTextContent(/Received.*SGD.5,000\.00/s));
    // The average of the five full months: (1800 + 2100 + 1500 + 2600 + 1900) / 5.
    expect(card).toHaveTextContent(/A usual month.*SGD.1,980\.00.*Average of the last 5 months/s);
    // The biggest category is "Where it went", next to it.
    expect(card).not.toHaveTextContent("Biggest category");
  });

  it("swaps Received for the budget left when there is an overall budget", async () => {
    serve({
      spending: spending({ budget: sgd("2000.00") }),
      budgets: [{ id: "b", category_id: null, name: "Overall", limit: sgd("2000.00"), spent: sgd("700.00"), remaining: sgd("1300.00"), percent: 35, unconverted: [] }],
    });
    renderOverview();
    const card = await screen.findByRole("region", { name: "Spending by month" });
    await waitFor(() => expect(card).toHaveTextContent(/Budget left.*SGD.1,300\.00.*35% used/s));
    expect(card).not.toHaveTextContent("Received");
  });
});

describe("SpendingChart", () => {
  it("says every month in words, and which are over the budget", () => {
    renderWithProviders(<SpendingChart data={spending({ budget: sgd("2000.00") })} />);
    const bars = screen.getByRole("list", { name: "Spending by month" });
    expect(within(bars).getByText(/Jun: SGD.2,100\.00, over budget/)).toBeInTheDocument();
    expect(within(bars).getByText(/Aug: SGD.2,600\.00, over budget/)).toBeInTheDocument();
    expect(within(bars).getByText(/Sep: SGD.1,900\.00$/)).toBeInTheDocument();
    // Over-budget months are striped, the current month solid, and it has the usual month's outline.
    expect(bars.querySelectorAll(".month-bar.over")).toHaveLength(2);
    expect(bars.querySelectorAll(".month-bar.now")).toHaveLength(1);
    expect(bars.querySelectorAll(".month-usual")).toHaveLength(1);
  });

  it("names every mark in the legend, and only what is drawn", () => {
    const { container, rerender } = renderWithProviders(<SpendingChart data={spending()} />);
    const legend = () => container.querySelector(".legend")!.textContent;
    expect(legend()).toBe("Past monthsThis month so farA usual month");
    rerender(<SpendingChart data={spending({ budget: sgd("2000.00") })} />);
    expect(legend()).toBe("Within budgetOver budgetThis month so farA usual monthMonthly budget");
  });
});
