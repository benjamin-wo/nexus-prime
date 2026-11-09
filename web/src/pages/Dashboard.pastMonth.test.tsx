import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, Spending, Summary } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { Dashboard } from "./Dashboard";

// A made-up Monday, 2 November 2026 in Singapore: "this month" is November.
const me: Me = {
  user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "csrf",
};
const sgd = (amount: string) => ({ amount, currency: "SGD" });
const total = (direction: "out" | "in", amount: string, count = 1) => ({
  direction,
  total: sgd(amount),
  count,
  converted: [],
  unconverted: [],
});

const novemberSummary: Summary = {
  start: "2026-11-01",
  end: "2026-11-02",
  currency: "SGD",
  totals: [total("out", "150.00", 2), total("in", "0.00", 0)],
  by_category: [{ category_id: "food", category_name: "Dining Out", total: sgd("150.00"), count: 2 }],
};
const octoberSummary: Summary = {
  start: "2026-10-01",
  end: "2026-10-31",
  currency: "SGD",
  totals: [total("out", "2140.00", 31), total("in", "5200.00")],
  by_category: [
    { category_id: "food", category_name: "Dining Out", total: sgd("900.00"), count: 12 },
    { category_id: "ride", category_name: "Transport", total: sgd("400.00"), count: 9 },
  ],
  put_away: sgd("1000.00"),
  saving_rate: 0.19,
};

const row = (month: string, amount: string, to_date = false) => ({ month, spent: sgd(amount), to_date });
const months = (): Spending => ({
  currency: "SGD",
  months: [
    row("2026-06-01", "2100.00"),
    row("2026-07-01", "1500.00"),
    row("2026-08-01", "2600.00"),
    row("2026-09-01", "2320.00"),
    row("2026-10-01", "2140.00"),
    row("2026-11-01", "150.00", true),
  ],
  last_month_to_date: sgd("90.00"),
  budget: null,
});

const budget = (name: string, spent: string, limit: string, percent: number, remaining: string) => ({
  id: name,
  category_id: name === "Overall" ? null : "food",
  name,
  limit: sgd(limit),
  spent: sgd(spent),
  remaining: sgd(remaining),
  percent,
  unconverted: [],
});

function serve() {
  const asked: string[] = [];
  const calls = mockApi({
    "GET /summary": (_, url) => {
      asked.push(url.search);
      const start = url.searchParams.get("start");
      if (start === "2026-10-01") return octoberSummary;
      if (start === "2026-02-01") return { ...octoberSummary, totals: [total("out", "1000.00"), total("in", "0.00")] };
      return start ? { ...octoberSummary, start, totals: [total("out", "0.00", 0), total("in", "0.00", 0)] } : novemberSummary;
    },
    "GET /spending/months": () => months(),
    "GET /budgets": (_, url) =>
      url.searchParams.get("month") === "2026-10"
        ? [budget("Overall", "2140.00", "2000.00", 107, "-140.00"), budget("Dining Out", "900.00", "1000.00", 90, "100.00")]
        : [budget("Overall", "150.00", "2000.00", 7, "1850.00")],
    "GET /transactions": () => ({
      items: [
        {
          id: "t1",
          direction: "out",
          amount: sgd("42.00"),
          occurred_at: "2026-10-12T04:00:00Z",
          counterparty: "Noodle Hut",
          category_id: "food",
          notes: null,
          status: "confirmed",
          source: "web",
          deleted: false,
        },
      ],
      total: 12,
    }),
    "GET /ious": () => [],
    "GET /wallets": () => [{ id: "w2", kind: "savings" }],
  });
  return { asked, calls };
}

const open = (route: string) => renderWithProviders(<Dashboard me={me} onAsk={() => {}} />, route);

describe("the Money overview for a past month", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-02T04:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("shows that month's totals and categories and the comparison with the month before", async () => {
    const { asked } = serve();
    open("/accounting?month=2026-10");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Looking back");
    expect(screen.getByRole("group", { name: "Month" })).toHaveTextContent(/October.*2026/);
    // September is one of the chart's months, so it isn't fetched again.
    const line = await screen.findByText(/SGD.180\.00 less than September/);
    expect(line.textContent).toMatch(/^SGD.180\.00 less than September$/);
    // The headline says what was spent that month, with no budget left to speak of.
    expect(document.querySelector(".overview-headline")?.textContent).toMatch(/^SGD.2,140\.00 spent in October$/);
    expect(screen.queryByRole("link", { name: "Set a budget" })).toBeNull();
    expect(asked).toEqual(["?start=2026-10-01&end=2026-10-31"]);
    expect(within(screen.getByRole("region", { name: "Spent" })).getByText(/2,140\.00/)).toBeInTheDocument();
    expect(await within(screen.getByRole("region", { name: "Received" })).findByText(/5,200\.00/)).toBeInTheDocument();
    expect(await within(screen.getByRole("region", { name: "Saved" })).findByText(/19% of income/)).toBeInTheDocument();
    const went = screen.getByRole("region", { name: "Where it went" });
    expect(await within(went).findByRole("button", { name: /Dining Out: SGD.900\.00/ })).toBeInTheDocument();
    expect(within(went).getByRole("button", { name: /Transport: SGD.400\.00/ })).toBeInTheDocument();
  });

  it("opens the ledger for a category in that month", async () => {
    serve();
    open("/accounting?month=2026-10");
    const went = await screen.findByRole("region", { name: "Where it went" });
    await userEvent.click(await within(went).findByRole("button", { name: /Dining Out: SGD.900\.00/ }));
    const more = await within(went).findByRole("link", { name: "See all 12 in the ledger" });
    const href = new URL(more.getAttribute("href") ?? "", "https://example.test");
    expect(href.pathname).toBe("/accounting/ledger");
    expect(Object.fromEntries(href.searchParams)).toEqual({
      view: "out",
      start: "2026-10-01",
      end: "2026-10-31",
      category: "food",
    });
  });

  it("shows each budget that month against today's limits, over or under", async () => {
    serve();
    open("/accounting?month=2026-10");
    const block = await screen.findByRole("region", { name: "Budgets" });
    expect(block).toHaveTextContent("Against today's limits");
    const rows = await within(block).findAllByRole("listitem");
    expect(rows[0]).toHaveTextContent(/Overall.*SGD.2,140\.00 of SGD.2,000\.00.*107% used · Over by SGD.140\.00/s);
    expect(rows[1]).toHaveTextContent(/Dining Out.*90% used · SGD.100\.00 under/s);
  });

  it("leaves out what is only about now: the nudge, budget left, latest, who owes you", async () => {
    const { calls } = serve();
    open("/accounting?month=2026-10");
    await screen.findByText(/less than September/);
    for (const name of ["Latest", "Who owes you", "From Kaya"]) expect(screen.queryByRole("region", { name })).toBeNull();
    expect(screen.queryByText(/Budget left|Left to spend|Still due/)).toBeNull();
    expect(calls.some((c) => c.path === "/ious")).toBe(false);
    // Under the chart only "a usual month" is left.
    const card = screen.getByRole("region", { name: "Spending by month" });
    expect(card).toHaveTextContent("A usual month");
    expect(card).not.toHaveTextContent("Received");
  });

  it("fetches the month before when the chart doesn't reach it", async () => {
    const { asked } = serve();
    open("/accounting?month=2026-03");
    expect(await screen.findByText(/SGD.1,000\.00 more than February|less than February/)).toBeInTheDocument();
    expect(asked).toContain("?start=2026-03-01&end=2026-03-31");
    expect(asked).toContain("?start=2026-02-01&end=2026-02-28");
  });

  it("steps back and forward with the picker and with the chart's bars", async () => {
    serve();
    open("/accounting");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This month");
    expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Previous month" }));
    expect(screen.getByRole("group", { name: "Month" })).toHaveTextContent(/October.*2026/);
    expect(await screen.findByText(/SGD.180\.00 less than September/)).toBeInTheDocument();
    // A bar opens its month and marks it as the one shown.
    const bar = screen.getByRole("button", { name: /August 2026: SGD.2,600\.00/ });
    await userEvent.click(bar);
    expect(screen.getByRole("group", { name: "Month" })).toHaveTextContent(/August.*2026/);
    expect(bar).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /October 2026: SGD.2,140\.00/ })).toHaveAttribute("aria-pressed", "false");
    // The chart keeps its six months; this month's bar brings the page back to now.
    await userEvent.click(screen.getByRole("button", { name: /November 2026, so far/ }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This month");
    expect(await screen.findByRole("region", { name: "Latest" })).toBeInTheDocument();
  });

  it("falls back to this month for something that isn't a month, a future month, or one too far back", () => {
    serve();
    for (const route of ["/accounting?month=2026-13", "/accounting?month=2027-01", "/accounting?month=2020-01"]) {
      const view = open(route);
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This month");
      expect(screen.getByRole("group", { name: "Month" })).toHaveTextContent(/November.*2026/);
      view.unmount();
    }
  });
});
