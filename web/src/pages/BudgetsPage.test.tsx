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
