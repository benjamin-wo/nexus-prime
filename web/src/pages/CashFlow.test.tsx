import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { CashDay, CashFlow, Money } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { barStep, CashFlowPage } from "./CashFlow";

const sgd = (amount: string): Money => ({ amount, currency: "SGD" });

function day(date: string, over: Partial<CashDay> = {}): CashDay {
  return {
    day: date,
    money_in: sgd("0"),
    money_out: sgd("0"),
    net: sgd("0"),
    expected: [],
    expected_net: sgd("0"),
    ...over,
  };
}

const days: CashDay[] = Array.from({ length: 30 }, (_, n) => day(`2026-11-${String(n + 1).padStart(2, "0")}`));
const set = (date: string, over: Partial<CashDay>) => {
  days[days.findIndex((d) => d.day === date)] = day(date, over);
};
set("2026-11-03", { money_out: sgd("1900"), net: sgd("-1900") });
set("2026-11-11", { money_out: sgd("46.65"), net: sgd("-46.65") });
set("2026-11-12", { money_out: sgd("4"), net: sgd("-4") });
set("2026-11-10", { money_in: sgd("120"), net: sgd("120") });
set("2026-11-20", {
  expected: [{ kind: "subscription", name: "Netflix", direction: "out", amount: sgd("17.98"), home: sgd("17.98") }],
  expected_net: sgd("-17.98"),
});
set("2026-11-25", {
  expected: [{ kind: "salary", name: "Payday", direction: "in", amount: sgd("4700"), home: sgd("4700") }],
  expected_net: sgd("4700"),
});
set("2026-11-27", {
  expected: [{ kind: "bill", name: "Gym", direction: "out", amount: null, home: null }],
  expected_net: sgd("0"),
});

const flow: CashFlow = {
  start: "2026-11-01",
  end: "2026-11-30",
  today: "2026-11-12",
  currency: "SGD",
  days,
  logged_in: sgd("120"),
  logged_out: sgd("1950.65"),
  expected_in: sgd("4700"),
  expected_out: sgd("17.98"),
  unknown_amounts: 1,
  unconverted: [],
};

const nameOf = (el: HTMLElement) => (el.getAttribute("aria-label") ?? "").replace(/\s/g, " ");

describe("Cash flow calendar", () => {
  it("names each day with the full figure and draws no amount text in the cells", async () => {
    mockApi({ "GET /cashflow": () => flow });
    renderWithProviders(<CashFlowPage />);
    const grid = await screen.findByRole("group", { name: "Days" });
    const names = within(grid).getAllByRole("button").map(nameOf);
    expect(names).toContain("November 11, spent SGD 46.65");
    expect(names).toContain("November 10, money in SGD 120.00");
    expect(names).toContain("November 25, expected in SGD 4,700.00");
    expect(names).toContain("November 20, expected out SGD 17.98");
    expect(names).toContain("November 27, 1 expected, no amount set");
    expect(names).toContain("November 1");
    // The cell holds the date and bars only: no amounts to shrink.
    const cell = within(grid).getByRole("button", { name: /^November 11,/ });
    expect(cell).toHaveTextContent(/^11$/);
    expect(cell.querySelector(".cal-bar.out")).not.toBeNull();
    expect(within(grid).getByRole("button", { name: /^November 25,/ }).querySelector(".cal-bar.expected.in")).not.toBeNull();
    expect(within(grid).getByRole("button", { name: /^November 10,/ }).querySelector(".cal-bar.in:not(.expected)")).not.toBeNull();
    expect(within(grid).getByRole("button", { name: /^November 1$/ }).querySelector(".cal-bar")).toBeNull();
  });

  it("makes taller bars for bigger days", async () => {
    mockApi({ "GET /cashflow": () => flow });
    renderWithProviders(<CashFlowPage />);
    const grid = await screen.findByRole("group", { name: "Days" });
    const bar = (name: RegExp) => within(grid).getByRole("button", { name }).querySelector(".cal-bar")?.className ?? "";
    expect(bar(/^November 12,/)).toContain("step-1");
    expect(bar(/^November 11,/)).toContain("step-2");
    expect(bar(/^November 3,/)).toContain("step-4");
    expect(bar(/^November 25,/)).toContain("step-4");
  });

  it("steps by log scale against the month's largest day", () => {
    expect(barStep(5, 4700)).toBe(1);
    expect(barStep(50, 4700)).toBe(2);
    expect(barStep(300, 4700)).toBe(3);
    expect(barStep(4700, 4700)).toBe(4);
    expect(barStep(5, 0)).toBe(1);
  });

  it("shows a legend under the grid", async () => {
    mockApi({ "GET /cashflow": () => flow });
    renderWithProviders(<CashFlowPage />);
    const key = await screen.findByRole("list", { name: "Key" });
    expect(key).toHaveTextContent("Spent");
    expect(key).toHaveTextContent("Expected");
    expect(key).toHaveTextContent("Money in");
    expect(key).toHaveTextContent("Taller bar = more");
  });

  it("selects a day on tap and lists what is expected on it", async () => {
    mockApi({ "GET /cashflow": () => flow });
    renderWithProviders(<CashFlowPage />);
    const grid = await screen.findByRole("group", { name: "Days" });
    // Today is selected to begin with.
    expect(within(grid).getByRole("button", { name: /^November 12,/ })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(within(grid).getByRole("button", { name: /^November 25,/ }));
    expect(within(grid).getByRole("button", { name: /^November 25,/ })).toHaveAttribute("aria-pressed", "true");
    expect(within(grid).getByRole("button", { name: /^November 12,/ })).toHaveAttribute("aria-pressed", "false");
    const detail = screen.getByRole("region", { name: /Wednesday/ });
    expect(within(detail).getByRole("listitem")).toHaveTextContent("Payday");
    expect(within(detail).getByRole("listitem")).toHaveTextContent("+SGD");
    await userEvent.click(within(grid).getByRole("button", { name: /^November 27,/ }));
    expect(within(screen.getByRole("region", { name: /Friday/ })).getByRole("listitem")).toHaveTextContent("Amount not set");
  });

  it("keeps the month totals", async () => {
    mockApi({ "GET /cashflow": () => flow });
    renderWithProviders(<CashFlowPage />);
    expect(await screen.findByText("Logged in / out")).toBeInTheDocument();
    expect(screen.getByText("Expected in / out")).toBeInTheDocument();
  });
});
