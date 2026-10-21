import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Booking, FeedItem, Me, Portfolio, Setup, Spending, Summary, Today, TripDetail } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { Home, NEEDS_SHOWN } from "./Home";
import { clock, dayLines, nextBooking, nextToday, tripDay } from "./HomeCards";

const me: Me = {
  user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "csrf",
};
const sgd = (amount: string) => ({ amount, currency: "SGD" });

const item = (text: string, when: FeedItem["when"], over: Partial<FeedItem> = {}): FeedItem => ({
  department: "accounting",
  kind: "bill",
  text,
  link: "/accounting/budgets",
  urgent: when === "now",
  when,
  actions: [],
  ...over,
});

const setup = (done: boolean[] = [false, false, true, false], dismissed = false): Setup => ({
  dismissed,
  items: [
    { key: "payday", label: "Set your payday", done: done[0], link: "/accounting/budgets", ask: "Help me set my payday" },
    { key: "receipts", label: "Get receipts in automatically", done: done[1], link: "/settings/email", ask: "Help me get my receipts in from email automatically" },
    { key: "investments", label: "Add your stocks", done: done[2], link: "/investment", ask: "Help me add my stocks" },
    { key: "budget", label: "Set a monthly budget", done: done[3], link: "/accounting/budgets", ask: "Help me set a monthly budget" },
  ],
});

const summary: Summary = {
  start: "2026-10-01",
  end: "2026-10-31",
  currency: "SGD",
  totals: [{ direction: "out", total: sgd("412.00"), count: 9, converted: [], unconverted: [] }],
  by_category: [],
};
const spending: Spending = {
  currency: "SGD",
  months: [{ month: "2026-10-01", spent: sgd("412.00"), to_date: true }],
  last_month_to_date: sgd("500.00"),
  budget: null,
};

const empty: Portfolio = {
  holdings: [],
  totals: {
    value: null, cost: null, gain: null, gain_percent: null, day_change: null, day_percent: null, as_of: null, as_of_at: null,
    price_kind: "close", missing: [], realised: null, dividends: null, total_return: null,
  },
  draft: null,
  screenshots: false,
  prices: false,
};

const holding = (symbol: string) => ({
  symbol, quantity: "10", average_cost: { amount: "100", currency: "USD" }, cost: { amount: "1000", currency: "USD" }, updated_at: "2026-10-20T12:00:00Z",
  price: { amount: "120", currency: "USD" }, price_day: "2026-10-20", price_kind: "close" as const, price_at: null, value: { amount: "1200", currency: "USD" },
  gain: null, gain_percent: null, day_change: null, day_percent: null, value_home: sgd("1600.00"), earnings: null,
});

const held: Portfolio = {
  ...empty,
  holdings: [holding("NVDA")],
  totals: { ...empty.totals, value: sgd("1600.00"), day_change: sgd("-80.00"), day_percent: "-4.76", as_of: "2026-10-20", price_kind: "close" },
};

const mover = (symbol: string, day_percent: string) => ({
  symbol, held: true, price: "120.00", day_percent, price_kind: "live" as const, price_at: null, price_day: "2026-10-20", headline: null,
});
const session = (movers: ReturnType<typeof mover>[], kind: Today["session"] = "live"): Today => ({
  session: kind, day: "2026-10-20", change: sgd("-80.00"), percent: "-4.76", price_kind: "live", as_of_at: null, holds: true, movers, prices: true,
});

const booking = (over: Partial<Booking>): Booking => ({
  id: "b", trip_id: "t1", kind: "activity", title: "x", provider: null, starts: "2026-10-21", ends: null, segments: [], hotel: null, address: null,
  check_in: null, check_out: null, name: null, day: null, at: null, note: null, reference: null, booked_via: null, category: null, place_id: null,
  scheduled: true, cost: null, logged: false, manual: true, ...over,
});

/** A trip with a stay, a plan this morning and one this afternoon, and a flight home. */
function trip(status: "upcoming" | "ongoing", over: Partial<TripDetail> = {}): TripDetail {
  const ongoing = status === "ongoing";
  return {
    trip: {
      id: "t1", destination: "Tokyo", start: ongoing ? "2026-10-19" : "2026-11-02", end: ongoing ? "2026-10-24" : "2026-11-06", days: ongoing ? 6 : 5,
      currency: "JPY", budget: sgd("2400.00"), companions: [], set_aside: null, planned: {}, status, days_until: ongoing ? 0 : 12,
      day_number: ongoing ? 3 : null, notes: null, day_labels: {}, stops: [], split_evenly: true, role: "owner", owner_name: "Ben",
    },
    bookings: [
      booking({ id: "stay", kind: "hotel", title: "Hotel Kumo", hotel: "Hotel Kumo", starts: "2026-10-19", check_in: "2026-10-19", check_out: "2026-10-24" }),
      booking({ id: "am", title: "Market walk", starts: "2026-10-21", at: "09:00" }),
      booking({ id: "pm", title: "Teahouse in Asakusa", starts: "2026-10-21", at: "14:00" }),
      booking({
        id: "home", kind: "flight", title: "ZZ13 NRT → SIN", starts: "2026-10-24",
        segments: [{ number: "ZZ13", origin: "NRT", destination: "SIN", departs: "2026-10-24T18:10", arrives: "2026-10-25T00:20" }],
      }),
    ],
    ready: { nights_without_stay: [], has_transport: true, has_budget: true, done: 3, total: 3 },
    spending: {
      spent: sgd("900.00"), left: sgd("1500.00"), percent: 37, before: sgd("0"), today: sgd("42.00"), per_day: null, per_day_left: sgd("300.00"),
      categories: [], unconverted: 0,
    },
    ...over,
  } as unknown as TripDetail;
}

type Answers = {
  home?: FeedItem[];
  setup?: Setup | null;
  portfolio?: Portfolio;
  today?: Today;
  next?: TripDetail | null;
  spending?: Spending;
};

function serve(answers: Answers = {}) {
  return mockApi({
    "GET /home": () => answers.home ?? [],
    "GET /runs": () => [],
    "GET /summary": () => summary,
    "GET /spending/months": () => answers.spending ?? spending,
    "GET /budgets": () => [],
    "GET /budgets/month": () => null,
    "GET /investments": () => answers.portfolio ?? empty,
    "GET /investments/today": () => answers.today ?? session([]),
    "GET /travel/next": () => answers.next ?? null,
    "GET /setup": () => (answers.setup === null ? new Response("{}", { status: 403 }) : (answers.setup ?? setup([true, true, true, true]))),
    "POST /setup/dismiss": () => new Response(null, { status: 204 }),
  });
}

const renderHome = (onAsk = vi.fn()) => renderWithProviders(<Home me={me} onAsk={onAsk} onLog={() => {}} />);

afterEach(() => vi.useRealTimers());

describe("Home: the brief", () => {
  it("speaks for money, the market and the trip, then points at the list below", async () => {
    serve({
      home: [item("Rent due tomorrow", "soon")],
      today: session([mover("NVDA", "-5.1")]),
      next: trip("upcoming"),
    });
    renderHome();
    const hero = await screen.findByRole("region", { name: "Nexus" });
    await waitFor(() => expect(hero).toHaveTextContent("NVDA is down 5% today."));
    expect(hero).toHaveTextContent(/NVDA is down 5% today\. Your Tokyo trip is in 12 days\. 1 thing needs you below\./);
  });

  it("leaves the market out when nothing moved much", async () => {
    serve({ today: session([mover("NVDA", "1.1")]) });
    renderHome();
    const hero = await screen.findByRole("region", { name: "Nexus" });
    await waitFor(() => expect(hero).toHaveTextContent("Nothing needs you right now."));
    expect(hero).not.toHaveTextContent("NVDA");
  });
});

describe("Home: Needs you", () => {
  const many = (n: number) =>
    Array.from({ length: n }, (_, i) => item(`Thing ${i + 1}`, i < 2 ? "now" : i < 4 ? "today" : "soon", { kind: `k${i}`, department: i % 2 ? "investment" : "travel" }));

  it("shows the top five, and Show all opens the rest in place", async () => {
    serve({ home: many(8) });
    renderHome();
    const needs = await screen.findByRole("region", { name: "Needs you" });
    await waitFor(() => expect(within(needs).getAllByRole("listitem")).toHaveLength(NEEDS_SHOWN));
    expect(within(needs).getByText("Thing 1")).toBeInTheDocument();
    expect(within(needs).queryByText("Thing 6")).toBeNull();
    const more = within(needs).getByRole("button", { name: "Show all (8)" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(more);
    expect(within(needs).getAllByRole("listitem")).toHaveLength(8);
    expect(within(needs).getByText("Thing 8")).toBeInTheDocument();
    const fewer = within(needs).getByRole("button", { name: "Show fewer" });
    expect(fewer).toHaveAttribute("aria-expanded", "true");
    await userEvent.setup().click(fewer);
    expect(within(needs).getAllByRole("listitem")).toHaveLength(NEEDS_SHOWN);
  });

  it("has no Show all for five or fewer", async () => {
    serve({ home: many(5) });
    renderHome();
    const needs = await screen.findByRole("region", { name: "Needs you" });
    await waitFor(() => expect(within(needs).getAllByRole("listitem")).toHaveLength(5));
    expect(within(needs).queryByRole("button", { name: /Show all/ })).toBeNull();
  });

  it("marks what needs you now in words, says Today quietly, and names the area", async () => {
    serve({ home: many(5) });
    renderHome();
    const needs = await screen.findByRole("region", { name: "Needs you" });
    const rows = await within(needs).findAllByRole("listitem");
    await waitFor(() => expect(rows).toHaveLength(5));
    // now: the marker, the alert styling and the area
    expect(within(rows[0]).getByText("Now")).toBeInTheDocument();
    expect(within(rows[0]).getByRole("link")).toHaveClass("urgent");
    expect(rows[0]).toHaveTextContent("Travel");
    expect(rows[1]).toHaveTextContent("Investment");
    // today: no marker, "Today" in the caption
    expect(within(rows[2]).queryByText("Now")).toBeNull();
    expect(rows[2]).toHaveTextContent("Travel · Today");
    expect(within(rows[2]).getByRole("link")).not.toHaveClass("urgent");
    // soon: neither
    expect(within(rows[4]).queryByText("Now")).toBeNull();
    expect(rows[4]).not.toHaveTextContent("Today");
    expect(within(rows[4]).getByRole("link")).toHaveAttribute("href", "/accounting/budgets");
  });

  it("keeps an item's buttons, which settle it there", async () => {
    const actions = [{ key: "went", label: "It went through", method: "POST", path: "/bills/m1/paid" }];
    const calls = mockApi({
      "GET /home": () => [item("Your IBKR top-up hasn't shown up", "soon", { actions })],
      "POST /bills/m1/paid": () => null,
    });
    renderHome();
    const button = await screen.findByRole("button", { name: "It went through" });
    expect(button).toHaveClass("btn-primary");
    await userEvent.setup().click(button);
    await waitFor(() => expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/bills/m1/paid"]));
  });
});

describe("Home: Get set up", () => {
  it("lists every step: done ones ticked, the rest with a way in", async () => {
    const onAsk = vi.fn();
    serve({ setup: setup() });
    renderHome(onAsk);
    const card = await screen.findByRole("region", { name: "Get set up" });
    const steps = within(card).getAllByRole("listitem");
    expect(steps).toHaveLength(4);
    expect(card).toHaveTextContent("3 steps left.");
    expect(within(steps[2]).getByText("Done")).toBeInTheDocument();
    expect(within(steps[2]).queryByRole("link")).toBeNull();
    expect(within(steps[0]).getByRole("link", { name: /^Set up\s?Set your payday$/ })).toHaveAttribute("href", "/accounting/budgets");
    expect(within(steps[3]).getByRole("link", { name: /Set up/ })).toHaveAttribute("href", "/accounting/budgets");
    // Every step can also be asked of Nexus, as a plain request for help.
    expect(within(steps[2]).queryByRole("button")).toBeNull();
    const user = userEvent.setup();
    await user.click(within(steps[1]).getByRole("button", { name: /Ask Nexus/ }));
    expect(onAsk).toHaveBeenCalledWith("Help me get my receipts in from email automatically");
    await user.click(within(steps[0]).getByRole("button", { name: /Ask Nexus/ }));
    expect(onAsk).toHaveBeenCalledWith("Help me set my payday");
  });

  it("counts one step left in the singular", async () => {
    serve({ setup: setup([true, true, true, false]) });
    renderHome();
    expect(await screen.findByRole("region", { name: "Get set up" })).toHaveTextContent("One step left.");
  });

  it("Hide puts it away: it asks the server, fetches the list again and the card goes", async () => {
    let dismissed = false;
    const calls = mockApi({
      "GET /home": () => [],
      "GET /setup": () => setup(undefined, dismissed),
      "POST /setup/dismiss": () => {
        dismissed = true;
        return new Response(null, { status: 204 });
      },
    });
    renderHome();
    const card = await screen.findByRole("region", { name: "Get set up" });
    await userEvent.setup().click(within(card).getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Get set up" })).toBeNull());
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/setup/dismiss"]);
    expect(calls.filter((c) => c.path === "/setup")).toHaveLength(2);
  });

  it("says so when it can't hide, and stays", async () => {
    mockApi({
      "GET /home": () => [],
      "GET /setup": () => setup(),
      "POST /setup/dismiss": () => new Response(JSON.stringify({ detail: "Try again in a minute" }), { status: 429 }),
    });
    renderHome();
    const card = await screen.findByRole("region", { name: "Get set up" });
    await userEvent.setup().click(within(card).getByRole("button", { name: "Hide" }));
    expect(await within(card).findByRole("alert")).toHaveTextContent("Try again in a minute");
    expect(within(card).getByRole("button", { name: "Hide" })).toBeEnabled();
  });

  it("is not shown once dismissed, once everything is done, or when the server refuses", async () => {
    for (const answer of [setup(undefined, true), setup([true, true, true, true]), setup([true, true, true, true], true), null]) {
      serve({ setup: answer });
      const { unmount } = renderHome();
      await screen.findByRole("region", { name: "Needs you" });
      // Everything Home asks has answered once the glance cards have.
      await waitFor(() => expect(screen.getByRole("region", { name: "Money this month" })).toHaveTextContent("SGD"));
      expect(screen.queryByRole("region", { name: "Get set up" })).toBeNull();
      unmount();
      vi.restoreAllMocks();
    }
  });
});

describe("Home: trip mode", () => {
  it("leads with the day, what is next, today's spending and the next booking for a trip that is on", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T03:00:00Z")); // 11:00 in Singapore
    serve({ next: trip("ongoing") });
    renderHome();
    const card = await screen.findByRole("region", { name: "Day 3 in Tokyo" });
    expect(within(card).getByRole("link", { name: "Open trip" })).toHaveAttribute("href", "/travel/trips/t1");
    // The morning walk is behind; the afternoon one is next.
    expect(card).toHaveTextContent("14:00 · Teahouse in Asakusa");
    expect(card).not.toHaveTextContent("Market walk");
    expect(card).toHaveTextContent(/Spent today.*SGD.42\.00.*SGD.300\.00 a day left in your budget/s);
    expect(card).toHaveTextContent(/Next booking.*ZZ13 NRT → SIN.*(24 Oct|Oct 24)/s);
    // It leads Needs you, and the Next trip card gives way to it.
    const needs = screen.getByRole("region", { name: "Needs you" });
    expect(card.compareDocumentPosition(needs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Next trip" })).toBeNull();
    expect(screen.getByRole("region", { name: "Nexus" })).toHaveTextContent("You're on day 3 of 6 in Tokyo.");
  });

  it("leaves out what the trip's data does not have", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T03:00:00Z"));
    const detail = trip("ongoing", { spending: null, bookings: [booking({ id: "stay", kind: "hotel", hotel: "Hotel Kumo", starts: "2026-10-19", check_in: "2026-10-19", check_out: "2026-10-24" })] });
    serve({ next: detail });
    renderHome();
    const card = await screen.findByRole("region", { name: "Day 3 in Tokyo" });
    expect(card).toHaveTextContent("Nothing planned today.");
    expect(card).not.toHaveTextContent("Spent today");
    expect(card).not.toHaveTextContent("Next booking");
  });

  it("is not shown for a trip that has not started, which is the Next trip card instead", async () => {
    serve({ next: trip("upcoming") });
    renderHome();
    const next = await screen.findByRole("region", { name: "Next trip" });
    await waitFor(() => expect(next).toHaveTextContent("Tokyo in 12 days"));
    expect(next).toHaveTextContent(/(2 Nov|Nov 2) to (6 Nov|Nov 6)/);
    expect(screen.queryByRole("region", { name: /^Day \d+ in/ })).toBeNull();
  });

  it("is not shown for a trip that is over", async () => {
    const finished = trip("upcoming");
    finished.trip.status = "finished";
    serve({ next: finished });
    renderHome();
    const next = await screen.findByRole("region", { name: "Next trip" });
    await waitFor(() => expect(next).toHaveTextContent("No trip coming up."));
    expect(screen.queryByRole("region", { name: /^Day \d+ in/ })).toBeNull();
  });
});

describe("a trip's day on Home", () => {
  it("reads the day from the trip's own count", () => {
    expect(tripDay(trip("ongoing").trip)).toBe("2026-10-21");
  });

  it("lists the day's plans in order, with a stay the trip leaves that morning", () => {
    const detail = trip("ongoing");
    expect(dayLines(detail, "2026-10-21").map((l) => [l.time, l.text])).toEqual([
      ["09:00", "Market walk"],
      ["14:00", "Teahouse in Asakusa"],
    ]);
    expect(dayLines(detail, "2026-10-24").map((l) => [l.time, l.text])).toEqual([
      [null, "Check out of Hotel Kumo"],
      ["18:10", "Flight NRT → SIN"],
    ]);
    // A flight on the day it only lands.
    const landing = trip("ongoing", { days: [{ day: "2026-10-25", order: ["home"], notes: [] }] });
    expect(dayLines(landing, "2026-10-25")[0]).toMatchObject({ time: "00:20", text: "Land SIN" });
  });

  it("picks the next thing with a time still to come, else one with no time, else nothing", () => {
    const lines = [
      { id: "a", time: null, text: "Check in" },
      { id: "b", time: "09:00", text: "Walk" },
      { id: "c", time: "14:00", text: "Tea" },
    ];
    expect(nextToday(lines, "08:00")?.id).toBe("b");
    expect(nextToday(lines, "09:00")?.id).toBe("b");
    expect(nextToday(lines, "09:01")?.id).toBe("c");
    expect(nextToday(lines, "15:00")?.id).toBe("a");
    expect(nextToday(lines.slice(1), "15:00")).toBeNull();
    expect(nextToday([], "08:00")).toBeNull();
  });

  it("finds the next flight, train or stay after today", () => {
    const detail = trip("ongoing");
    expect(nextBooking(detail, "2026-10-21")?.id).toBe("home");
    expect(nextBooking(detail, "2026-10-24")).toBeNull();
  });

  it("tells the time in the user's zone", () => {
    expect(clock("Asia/Singapore", new Date("2026-10-21T03:05:00Z"))).toBe("11:05");
    expect(clock("Asia/Singapore", new Date("2026-10-20T16:00:00Z"))).toBe("00:00");
  });
});

describe("Home: at a glance", () => {
  it("says what is empty in one line", async () => {
    serve({ spending: { ...spending, last_month_to_date: undefined as never } });
    renderHome();
    const portfolio = await screen.findByRole("region", { name: "Portfolio today" });
    await waitFor(() => expect(portfolio).toHaveTextContent("No holdings yet."));
    expect(within(portfolio).getByRole("link", { name: "Add your stocks" })).toHaveAttribute("href", "/investment");
    const trip = screen.getByRole("region", { name: "Next trip" });
    await waitFor(() => expect(trip).toHaveTextContent("No trip coming up."));
    expect(within(trip).getByRole("link", { name: "Plan a trip" })).toHaveAttribute("href", "/travel");
    const money = screen.getByRole("region", { name: "Money this month" });
    await waitFor(() => expect(money).toHaveTextContent("SGD"));
    expect(money).toHaveTextContent("Set a budget on the Budgets page");
  });

  it("shows the month against last month by this date when there is no budget", async () => {
    serve();
    renderHome();
    const money = await screen.findByRole("region", { name: "Money this month" });
    await waitFor(() => expect(money).toHaveTextContent(/SGD.412\.00/));
    expect(money).toHaveTextContent(/Last month by now: SGD.500\.00/);
    expect(within(money).queryByRole("meter")).toBeNull();
    expect(within(money).getByRole("link", { name: "Details" })).toHaveAttribute("href", "/accounting");
  });

  it("shows the month against the overall budget when there is one", async () => {
    mockApi({
      "GET /home": () => [],
      "GET /summary": () => summary,
      "GET /budgets": () => [
        { id: "b", category_id: null, name: "Overall", limit: sgd("1000.00"), spent: sgd("412.00"), remaining: sgd("588.00"), percent: 41, unconverted: [] },
      ],
    });
    renderHome();
    const money = await screen.findByRole("region", { name: "Money this month" });
    const meter = await within(money).findByRole("meter", { name: "Budget used" });
    expect(meter).toHaveAttribute("aria-valuenow", "41");
    expect(money).toHaveTextContent(/41% of your budget used, \d+% through the month/);
    expect(money).toHaveTextContent(/On pace|Under pace|Ahead of pace/);
  });

  it("shows the portfolio's value in the home currency, its change and when the prices are from", async () => {
    serve({ portfolio: held });
    renderHome();
    const card = await screen.findByRole("region", { name: "Portfolio today" });
    await waitFor(() => expect(card).toHaveTextContent(/SGD.1,600\.00/));
    expect(card).toHaveTextContent(/−SGD.80\.00 \(−4\.76%\)/);
    expect(card.querySelector(".down")).not.toBeNull();
    expect(card).toHaveTextContent("Close of");
    expect(within(card).getByRole("link", { name: "Open" })).toHaveAttribute("href", "/investment");
  });
});

describe("Home: what moved to Accounting", () => {
  it("has no spending chart, budgets list or Today card", async () => {
    serve({ portfolio: held, today: session([mover("NVDA", "-5.1")]) });
    renderHome();
    await screen.findByRole("region", { name: "Portfolio today" });
    await waitFor(() => expect(screen.getByRole("region", { name: "Money this month" })).toHaveTextContent("SGD"));
    expect(screen.queryByRole("list", { name: "Spending by month" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Budgets this month" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Biggest movers" })).toBeNull();
  });
});
