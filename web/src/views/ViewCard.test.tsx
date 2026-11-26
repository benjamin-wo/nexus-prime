import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testing";
import { ViewCard } from "./ViewCard";
import { viewPath } from "./paths";
import type { CardView } from "./types";

const sgd = (amount: string) => ({ amount, currency: "SGD" });
const answer = (kind: string, caption: string, summary: unknown, params: Record<string, unknown> = {}) => ({
  view_id: kind,
  kind,
  params,
  caption,
  summary,
});

const NOV = { month: "2026-11" };

function draw(view: CardView, handlers: Record<string, (body: unknown, url: URL) => unknown>, onOpen = vi.fn()) {
  const calls = mockApi(handlers);
  renderWithProviders(<ViewCard view={view} onOpen={onOpen} />);
  return { calls, onOpen };
}

describe("a card for each kind of view", () => {
  it("shows the month outlook with its in and out bars", async () => {
    draw(
      { kind: "finance.month_outlook", params: NOV, focus: true },
      {
        "GET /views/finance.month_outlook": () =>
          answer("finance.month_outlook", "Your outlook for November 2026", {
            status: "ok",
            received: sgd("5000.00"),
            spent: sgd("2100.50"),
            overall: sgd("2899.50"),
            headroom: sgd("900.00"),
            shortfall: null,
          }, NOV),
      },
    );
    const card = await screen.findByRole("region", { name: "Your outlook for November 2026" });
    expect(await within(card).findByText("Left at month end")).toBeInTheDocument();
    expect(within(card).getByText(/2,899\.50/)).toBeInTheDocument();
    expect(within(card).getByRole("img", { name: /Received SGD\s?5,000\.00, spent SGD\s?2,100\.50/ })).toBeInTheDocument();
    expect(within(card).getByText(/In · SGD\s?5,000\.00/)).toBeInTheDocument();
    expect(within(card).getByText(/Out · SGD\s?2,100\.50/)).toBeInTheDocument();
    expect(within(card).getByText("Room to spare")).toBeInTheDocument();
  });

  it("names a shortfall as short, in words", async () => {
    draw(
      { kind: "finance.month_outlook", params: NOV, focus: false },
      {
        "GET /views/finance.month_outlook": () =>
          answer("finance.month_outlook", "Your outlook", { status: "short", received: sgd("100"), spent: sgd("300"), overall: sgd("-200"), headroom: null, shortfall: sgd("200") }),
      },
    );
    expect(await screen.findByText("Short at month end")).toBeInTheDocument();
  });

  it("shows budgets with how much of each is used, over ones in words", async () => {
    draw(
      { kind: "finance.budgets", params: NOV, focus: false },
      {
        "GET /views/finance.budgets": () =>
          answer("finance.budgets", "Your budgets for November 2026", {
            count: 4,
            over: 1,
            budgets: [
              { name: "Dining", spent: sgd("240"), limit: sgd("200"), percent: 120 },
              { name: "Transport", spent: sgd("50"), limit: sgd("100"), percent: 50 },
              { name: "Fun", spent: sgd("10"), limit: sgd("100"), percent: 10 },
              { name: "Gifts", spent: sgd("0"), limit: sgd("100"), percent: 0 },
            ],
          }),
      },
    );
    const card = await screen.findByRole("region", { name: "Your budgets for November 2026" });
    expect(await within(card).findByText("120% used")).toBeInTheDocument();
    expect(within(card).queryByText("Gifts")).toBeNull(); // compact: the top three
    expect(within(card).getByText("1 more")).toBeInTheDocument();
  });

  it("shows spending by category, a bar and its rows", async () => {
    draw(
      { kind: "finance.spending", params: NOV, focus: true },
      {
        "GET /views/finance.spending": () =>
          answer("finance.spending", "Where your money went in November 2026", {
            spent: sgd("300"),
            count: 12,
            categories: [
              { name: "Dining", total: sgd("200") },
              { name: "Transport", total: sgd("100") },
            ],
          }),
      },
    );
    const card = await screen.findByRole("region", { name: "Where your money went in November 2026" });
    expect(await within(card).findByText("12 entries")).toBeInTheDocument();
    expect(within(card).getByRole("list", { name: "Spending by category" })).toBeInTheDocument();
    expect(card.querySelectorAll(".split-bar span")).toHaveLength(2);
  });

  it("shows a trip's budget", async () => {
    draw(
      { kind: "travel.trip_budget", params: { trip_id: "t1" }, focus: false },
      {
        "GET /views/travel.trip_budget": () =>
          answer("travel.trip_budget", "Your trip's budget", { budget: sgd("3000"), spent: sgd("1200"), left: sgd("1800"), percent: 40, to_spend: sgd("1500") }),
      },
    );
    const card = await screen.findByRole("region", { name: "Your trip's budget" });
    expect(await within(card).findByText("Left in the budget")).toBeInTheDocument();
    expect(within(card).getByText("40% spent")).toBeInTheDocument();
  });

  it("shows the portfolio with signed changes", async () => {
    draw(
      { kind: "invest.portfolio", params: {}, focus: false },
      {
        "GET /views/invest.portfolio": () =>
          answer("invest.portfolio", "Your portfolio", { holdings: 3, value: sgd("10000"), cost: sgd("9000"), gain: sgd("1000"), day_change: sgd("-50"), as_of: null }),
      },
    );
    const card = await screen.findByRole("region", { name: "Your portfolio" });
    expect(await within(card).findByText(/\+SGD\s?1,000/)).toBeInTheDocument();
    expect(within(card).getByText(/−SGD\s?50/)).toBeInTheDocument();
  });

  it("shows today's food and workout", async () => {
    draw(
      { kind: "health.today", params: {}, focus: true },
      {
        "GET /views/health.today": () =>
          answer("health.today", "Your day", { day: "2026-11-27", meals: 2, kcal: "1600", protein_g: "90", kcal_target: "2200", workout: { state: "planned", routine: "Push day", exercises: 5 } }),
      },
    );
    const card = await screen.findByRole("region", { name: "Your day" });
    expect(await within(card).findByText("2 logged")).toBeInTheDocument();
    expect(within(card).getByText(/about 1,600 kcal/)).toBeInTheDocument();
    expect(within(card).getByText("Push day")).toBeInTheDocument();
  });

  it("says today's food in words and no numbers in numbers-free mode", async () => {
    draw(
      { kind: "health.today", params: {}, focus: true },
      { "GET /views/health.today": () => answer("health.today", "Your day", { day: "2026-11-27", meals: 1 }) },
    );
    const card = await screen.findByRole("region", { name: "Your day" });
    expect(await within(card).findByText("1 logged")).toBeInTheDocument();
    expect(within(card).queryByText(/kcal/)).toBeNull();
    expect(within(card).queryByText(/\bg\b/)).toBeNull();
  });

  it("shows the weight trend with a sparkline", async () => {
    draw(
      { kind: "health.weight_trend", params: {}, focus: false },
      {
        "GET /views/health.weight_trend": () =>
          answer("health.weight_trend", "Your weight trend", { hidden: false, trend_words: "slowly down", trend_kg: "82.4", kg_a_week: "-0.3", weigh_ins: 3 }),
        "GET /health/weight": () => ({
          hidden: false,
          trend_words: "slowly down",
          points: [
            { date: "2026-11-10", scale_kg: "83.2", trend_kg: "83.0" },
            { date: "2026-11-17", scale_kg: "82.6", trend_kg: "82.7" },
            { date: "2026-11-24", scale_kg: "82.1", trend_kg: "82.4" },
          ],
        }),
        "GET /health/preferences": () => ({ unit: "kg" }),
      },
    );
    const card = await screen.findByRole("region", { name: "Your weight trend" });
    expect(await within(card).findByText(/82\.4 kg/)).toBeInTheDocument();
    expect(await within(card).findByRole("img", { name: "Weight trend, slowly down" })).toBeInTheDocument();
  });

  it("gives only the direction in words in numbers-free mode", async () => {
    draw(
      { kind: "health.weight_trend", params: {}, focus: false },
      { "GET /views/health.weight_trend": () => answer("health.weight_trend", "Your weight trend", { hidden: true, trend_words: "slowly down" }) },
    );
    const card = await screen.findByRole("region", { name: "Your weight trend" });
    expect(await within(card).findByText("Slowly down")).toBeInTheDocument();
    expect(card.querySelector("svg")).toBeNull();
    expect(within(card).queryByText(/kg/)).toBeNull();
  });

  it("resumes an open workout by opening its page", async () => {
    const user = userEvent.setup();
    const { onOpen } = draw(
      { kind: "health.workout", params: {}, focus: false },
      { "GET /views/health.workout": () => answer("health.workout", "Your workout", { state: "open", started_at: "2026-11-27T08:00:00Z" }) },
    );
    await user.click(await screen.findByRole("button", { name: "Resume" }));
    expect(onOpen).toHaveBeenCalledWith("/health/gym");
  });

  it("starts the planned routine with the same call as the Gym page, then opens it", async () => {
    const user = userEvent.setup();
    const routine = { id: "r1", name: "Push day", slots: [] };
    const calls = mockApi({
      "GET /views/health.workout": () => answer("health.workout", "Your workout", { state: "planned", routine: "Push day", exercises: 5 }),
      "GET /health/today": () => ({ routine, in_progress: null }),
      "POST /health/workouts": () => ({ id: "w1" }),
    });
    const onOpen = vi.fn();
    renderWithProviders(<ViewCard view={{ kind: "health.workout", params: {}, focus: false }} onOpen={onOpen} />);
    await user.click(await screen.findByRole("button", { name: "Start" }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith("/health/gym"));
    expect(calls.find((c) => c.method === "POST" && c.path === "/health/workouts")?.body).toEqual({ routine_id: "r1" });
  });

  it("has no Start on a rest day", async () => {
    draw(
      { kind: "health.workout", params: {}, focus: false },
      { "GET /views/health.workout": () => answer("health.workout", "Your workout", { state: "rest" }) },
    );
    await screen.findByText("Rest day");
    expect(screen.queryByRole("button", { name: "Start" })).toBeNull();
  });

  it("shows records", async () => {
    draw(
      { kind: "health.records", params: {}, focus: false },
      {
        "GET /views/health.records": () =>
          answer("health.records", "Your records", { records: [{ exercise: "Barbell bench press", heaviest_kg: "100", e1rm_kg: "112.5", sessions: 6 }] }),
        "GET /health/preferences": () => ({ unit: "kg" }),
      },
    );
    const card = await screen.findByRole("region", { name: "Your records" });
    expect(await within(card).findByText("Barbell bench press")).toBeInTheDocument();
    expect(within(card).getByText("6 sessions")).toBeInTheDocument();
  });
});

describe("how a card loads", () => {
  it("shows the frame's summary while the figures load, then the fresh ones", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    mockApi({
      "GET /views/invest.portfolio": async () => {
        await gate;
        return answer("invest.portfolio", "Your portfolio", { holdings: 3, value: sgd("10500"), cost: sgd("9000"), gain: sgd("1500"), day_change: null, as_of: null });
      },
    });
    renderWithProviders(
      <ViewCard
        view={{ kind: "invest.portfolio", params: {}, focus: false, caption: "Your portfolio", summary: { holdings: 3, value: sgd("10000"), cost: sgd("9000"), gain: sgd("1000"), day_change: null, as_of: null } }}
        onOpen={() => {}}
      />,
    );
    expect(await screen.findByText(/10,000/)).toBeInTheDocument();
    release();
    expect(await screen.findByText(/10,500/)).toBeInTheDocument();
  });

  it("says it couldn't load, with a Retry that fetches again", async () => {
    const user = userEvent.setup();
    let fail = true;
    mockApi({
      "GET /views/finance.budgets": () =>
        fail ? new Response(JSON.stringify({ detail: "no" }), { status: 500 }) : answer("finance.budgets", "Your budgets", { count: 0, over: 0, budgets: [] }),
    });
    renderWithProviders(<ViewCard view={{ kind: "finance.budgets", params: NOV, focus: false }} onOpen={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load this view.");
    fail = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No budgets set for this month.")).toBeInTheDocument();
  });

  it("sends the params as the query and Open gives the page's path", async () => {
    const user = userEvent.setup();
    const { calls, onOpen } = draw(
      { kind: "finance.budgets", params: NOV, focus: false },
      { "GET /views/finance.budgets": () => answer("finance.budgets", "Your budgets for November 2026", { count: 0, over: 0, budgets: [] }, NOV) },
    );
    await screen.findByRole("region", { name: "Your budgets for November 2026" });
    expect(calls[0]).toMatchObject({ method: "GET", path: "/views/finance.budgets" });
    await user.click(screen.getByRole("button", { name: "Open Your budgets for November 2026" }));
    expect(onOpen).toHaveBeenCalledWith("/accounting/budgets?month=2026-11");
  });

  it("waits to fetch a history card until it is scrolled to", async () => {
    let seen: ((entries: { isIntersecting: boolean }[]) => void) | undefined;
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: typeof seen) {
          seen = cb;
        }
        observe() {}
        disconnect() {}
      },
    );
    const calls = mockApi({ "GET /views/finance.budgets": () => answer("finance.budgets", "Your budgets", { count: 0, over: 0, budgets: [] }) });
    renderWithProviders(<ViewCard view={{ kind: "finance.budgets", params: NOV, focus: false }} lazy onOpen={() => {}} />);
    expect(screen.getByRole("region", { name: "Your budgets" })).toBeInTheDocument(); // the kind's name stands in for the caption
    expect(calls).toHaveLength(0);
    seen?.([{ isIntersecting: true }]);
    await waitFor(() => expect(calls).toHaveLength(1));
    vi.unstubAllGlobals();
  });
});

describe("where Open goes", () => {
  it.each([
    ["finance.month_outlook", { month: "2026-10" }, "/accounting?month=2026-10"],
    ["finance.spending", { month: "2026-10" }, "/accounting?month=2026-10"],
    ["finance.budgets", { month: "2026-10" }, "/accounting/budgets?month=2026-10"],
    ["travel.trip_budget", { trip_id: "abc" }, "/travel/trips/abc?tab=money"],
    ["invest.portfolio", {}, "/investment"],
    ["health.today", { day: "2026-11-20" }, "/health?day=2026-11-20"],
    ["health.today", {}, "/health"],
    ["health.weight_trend", {}, "/health?weight=trend"],
    ["health.workout", { state: "open" }, "/health/gym"],
    ["health.records", {}, "/health/gym/history"],
  ])("%s %j -> %s", (kind, params, path) => {
    expect(viewPath(kind, params)).toBe(path);
  });

  it("has no page for a kind it doesn't know", () => {
    expect(viewPath("finance.nothing", {})).toBeNull();
  });
});
