import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Me } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { BudgetsPage } from "./BudgetsPage";

const me: Me = {
  user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "csrf",
};
const sgd = (amount: string) => ({ amount, currency: "SGD" });

describe("the Budgets page for a past month", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-02T04:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("shows each budget's spend that month against its limit, read-only", async () => {
    const asked: string[] = [];
    mockApi({
      "GET /budgets": (_, url) => {
        asked.push(url.search);
        return [
          { id: "b1", category_id: null, name: "Overall", limit: sgd("2000.00"), spent: sgd("2140.00"), remaining: sgd("-140.00"), percent: 107, unconverted: [] },
          { id: "b2", category_id: "food", name: "Dining Out", limit: sgd("1000.00"), spent: sgd("900.00"), remaining: sgd("100.00"), percent: 90, unconverted: [] },
        ];
      },
    });
    renderWithProviders(<BudgetsPage me={me} />, "/accounting/budgets?month=2026-10");
    expect(screen.getByRole("group", { name: "Month" })).toHaveTextContent(/October.*2026/);
    const card = await screen.findByRole("region", { name: "Budgets" });
    const rows = await within(card).findAllByRole("listitem");
    expect(rows[0]).toHaveTextContent(/Overall.*SGD.2,140\.00 of SGD.2,000\.00.*Over by SGD.140\.00/s);
    expect(rows[1]).toHaveTextContent(/Dining Out.*SGD.900\.00 of SGD.1,000\.00.*SGD.100\.00 under/s);
    expect(asked).toEqual(["?month=2026-10"]);
    // Limits are changed on this month, not here.
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Add a budget" })).toBeNull();
    // This month's own page is a step forward.
    expect(screen.getByRole("button", { name: "Next month" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(screen.getByRole("group", { name: "Month" })).toHaveTextContent(/November.*2026/);
  });
});

describe("the Budgets page for this month", () => {
  const plan = {
    currency: "SGD",
    total_out: sgd("2600.00"),
    left_to_spend: sgd("1100.00"),
    still_due_out: sgd("1300.00"),
    income: sgd("5000.00"),
    budget_left: null,
    tighter: null,
    plan_warning: null,
    skipped: [],
  };
  const overall = { id: "b1", category_id: null, name: "Overall", limit: sgd("2000.00"), spent: sgd("600.00"), remaining: sgd("1400.00"), percent: 30, unconverted: [] };
  const serve = (budgets: unknown[]) =>
    mockApi({
      "GET /budgets": () => budgets,
      "GET /budgets/month": () => plan,
      "GET /categories": () => [{ id: "food", name: "Dining Out" }],
      "GET /bills": () => [],
      "GET /salary": () => null,
      "GET /subscriptions": () => ({ tracked: [], proposed: [], monthly_totals: [] }),
      "GET /wallets": () => [],
    });

  it("starts as a short Set a monthly limit form, with no summary cards, until there is a budget", async () => {
    serve([]);
    renderWithProviders(<BudgetsPage me={me} />, "/accounting/budgets");
    expect(await screen.findByRole("heading", { name: "Set a monthly limit" })).toBeInTheDocument();
    const form = screen.getByRole("form", { name: "Add a budget" });
    expect(within(form).getByLabelText("Category")).toHaveDisplayValue("All spending");
    expect(within(form).getByLabelText(/Monthly limit/)).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Total spent" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Left to spend" })).toBeNull();
    expect(screen.queryByText(/No budgets yet/)).toBeNull();
    // The month picker stays.
    expect(screen.getByRole("group", { name: "Month" })).toBeInTheDocument();
  });

  it("behaves as before once there is a budget: the summary cards come back", async () => {
    serve([overall]);
    renderWithProviders(<BudgetsPage me={me} />, "/accounting/budgets");
    expect(await screen.findByRole("group", { name: "Total spent" })).toHaveTextContent(/SGD.2,600\.00/);
    expect(screen.getByRole("group", { name: "Left to spend" })).toHaveTextContent(/SGD.1,100\.00/);
    expect(screen.queryByRole("heading", { name: "Set a monthly limit" })).toBeNull();
    expect(screen.getByRole("meter", { name: "Overall budget used" })).toBeInTheDocument();
  });
});
