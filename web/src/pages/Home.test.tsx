import { useQuery } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, type Booking, type Budget, type FeedAction, type FeedItem, type Me, type Portfolio, type Setup, type Spending, type Summary, type Today, type TripDetail } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { Home, TODAY_SHOWN } from "./Home";
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
  budgets?: Budget[];
  history?: unknown[];
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
    "GET /budgets": () => answers.budgets ?? [],
    "GET /budgets/month": () => null,
    "GET /notifications/history": () => answers.history ?? [],
    "GET /investments": () => answers.portfolio ?? empty,
    "GET /investments/today": () => answers.today ?? session([]),
    "GET /travel/next": () => answers.next ?? null,
    "GET /setup": () => (answers.setup === null ? new Response("{}", { status: 403 }) : (answers.setup ?? setup([true, true, true, true]))),
    "POST /setup/dismiss": () => new Response(null, { status: 204 }),
  });
}

const renderHome = (onLog = vi.fn()) => renderWithProviders(<Home me={me} onLog={onLog} />);

const overallBudget = (limit: string): Budget => ({
  id: "b", category_id: null, name: "Overall", limit: sgd(limit), spent: sgd("412.00"), remaining: sgd("0"), percent: 41, unconverted: [],
});
const headlineOf = () => screen.findByRole("region", { name: "This month" });
/** Pretend it is 21 October, 11:00 in Singapore (10 days of the month to go), with timers left alone. */
const onThe21st = () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-21T03:00:00Z"));
};

afterEach(() => vi.useRealTimers());

describe("Home: the headline", () => {
  it("has no greeting, round buttons or panel: the date, the figure and one sentence", async () => {
    onThe21st();
    serve();
    const { container } = renderHome();
    const head = await headlineOf();
    expect(head).toHaveTextContent("Wednesday, 21 October");
    await waitFor(() => expect(head).toHaveTextContent("412.00"));
    expect(screen.queryByText(/Good (morning|afternoon|evening)/)).toBeNull();
    expect(container.querySelector(".round-btn, .hero, .hero-brief")).toBeNull();
    expect(screen.queryByRole("region", { name: "Nexus" })).toBeNull();
  });

  it("with no budget says what was spent and how that compares with last month by this date, in words", async () => {
    onThe21st();
    serve();
    renderHome();
    const head = await headlineOf();
    await waitFor(() => expect(head).toHaveTextContent("spent in October, 88.00 less than by this time in September."));
    expect(head.querySelector(".home-figure")).toHaveTextContent("412.00");
    expect(head.querySelector(".home-figure")).not.toHaveClass("is-over");
  });

  it("with an overall budget says what is left and what that comes to a day", async () => {
    onThe21st();
    serve({ budgets: [overallBudget("1000.00")] });
    renderHome();
    const head = await headlineOf();
    await waitFor(() => expect(head).toHaveTextContent("left for October. About 59 a day for the next 10 days, and 88.00 less spent than by this time in September."));
    expect(head.querySelector(".home-figure")).toHaveTextContent("588.00");
  });

  it("leaves the comparison out when last month's figure is not known", async () => {
    onThe21st();
    serve({ budgets: [overallBudget("1000.00")], spending: { ...spending, last_month_to_date: undefined as never } });
    renderHome();
    const head = await headlineOf();
    await waitFor(() => expect(head).toHaveTextContent("left for October. About 59 a day for the next 10 days."));
    expect(head).not.toHaveTextContent("September");
  });

  it("over the budget shows the figure in rose and says by how much, with no a-day clause", async () => {
    onThe21st();
    serve({ budgets: [overallBudget("300.00")] });
    renderHome();
    const head = await headlineOf();
    await waitFor(() => expect(head).toHaveTextContent("spent, over for October by 112.00"));
    expect(head.querySelector(".home-figure")).toHaveClass("is-over");
    expect(head).not.toHaveTextContent("a day");
  });

  it("on the last day of the month drops the a-day clause", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-31T03:00:00Z"));
    serve({ budgets: [overallBudget("1000.00")] });
    renderHome();
    const head = await headlineOf();
    await waitFor(() => expect(head).toHaveTextContent("left for October, with 88.00 less spent"));
    expect(head).not.toHaveTextContent("a day");
  });
});

describe("Home: the date line", () => {
  it("has Log, a Settings link and, when Nexus has sent something, the bell; Log opens the entry sheet", async () => {
    serve({ history: [{ id: "n1", kind: "bill_reminder", level: "now", text: "Rent is due", link: null, status: "sent", created_at: "2026-10-20T01:00:00Z", sent_at: null, held_until: null }] });
    const onLog = vi.fn();
    renderHome(onLog);
    const head = await headlineOf();
    // A quick manual entry beside the chat, for when there's no time to chat.
    await userEvent.click(within(head).getByRole("button", { name: "Log expense" }));
    expect(onLog).toHaveBeenCalledOnce();
    expect(within(head).getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
    expect(await within(head).findByRole("link", { name: "Notifications" })).toHaveAttribute("href", "/settings/notifications");
  });

  it("has no bell when there is nothing to read", async () => {
    serve();
    renderHome();
    const head = await headlineOf();
    await waitFor(() => expect(head).toHaveTextContent("412.00"));
    expect(within(head).queryByRole("link", { name: "Notifications" })).toBeNull();
  });
});

/** Pretend the screen is (or isn't) phone-sized, i.e. matches the shell's bottom-bar query. */
function screenIs(phone: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: phone && query === "(max-width: 900px)",
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    })),
  );
}

describe("Home: no ask panel", () => {
  afterEach(() => vi.unstubAllGlobals());

  for (const phone of [false, true]) {
    it(`has no Just ask Nexus card, chips or typing box on a ${phone ? "phone" : "wide screen"}`, async () => {
      screenIs(phone);
      serve();
      const { container } = renderHome();
      await headlineOf();
      expect(screen.queryByRole("region", { name: "Just ask Nexus" })).toBeNull();
      expect(screen.queryByRole("group", { name: "Suggested questions" })).toBeNull();
      expect(screen.queryByRole("textbox")).toBeNull();
      expect(container.querySelector(".ask-input, #ask-input, .ask-dock, .home-docked, .ask-panel")).toBeNull();
    });
  }
});

describe("Home: For today", () => {
  const many = (n: number) =>
    Array.from({ length: n }, (_, i) => item(`Thing ${i + 1}`, i < 2 ? "now" : i < 4 ? "today" : "soon", { kind: `k${i}`, department: i % 2 ? "investment" : "travel" }));
  const region = () => screen.findByRole("region", { name: "For today" });

  it("shows the first five, and See all opens the rest in place", async () => {
    serve({ home: many(8) });
    renderHome();
    const today = await region();
    await waitFor(() => expect(within(today).getAllByRole("listitem")).toHaveLength(TODAY_SHOWN));
    expect(within(today).getByText("Thing 1")).toBeInTheDocument();
    expect(within(today).queryByText("Thing 6")).toBeNull();
    const more = within(today).getByRole("button", { name: "See all 8" });
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(more);
    expect(within(today).getAllByRole("listitem")).toHaveLength(8);
    expect(within(today).getByText("Thing 8")).toBeInTheDocument();
    const fewer = within(today).getByRole("button", { name: "Show fewer" });
    expect(fewer).toHaveAttribute("aria-expanded", "true");
    await userEvent.setup().click(fewer);
    expect(within(today).getAllByRole("listitem")).toHaveLength(TODAY_SHOWN);
  });

  it("has no See all for five or fewer", async () => {
    serve({ home: many(5) });
    renderHome();
    const today = await region();
    await waitFor(() => expect(within(today).getAllByRole("listitem")).toHaveLength(5));
    expect(within(today).queryByRole("button", { name: /See all/ })).toBeNull();
  });

  it("says Nothing for today. when there is nothing, and not before it has loaded", async () => {
    serve();
    renderHome();
    const today = await region();
    expect(today).not.toHaveTextContent("Nothing for today.");
    expect(await within(today).findByText("Nothing for today.")).toBeInTheDocument();
    expect(within(today).queryByRole("listitem")).toBeNull();
  });

  it("has no icon tile or badge; a word at the right says how soon, and the sub-line names the area", async () => {
    serve({ home: many(5) });
    const { container } = renderHome();
    const today = await region();
    const rows = await within(today).findAllByRole("listitem");
    await waitFor(() => expect(rows).toHaveLength(5));
    expect(container.querySelector(".row-icon, .badge, .badge-now")).toBeNull();
    // now: its word in the warning colour (is-now) and the area underneath
    expect(within(rows[0]).getByText("Look")).toHaveClass("is-now");
    expect(rows[0]).toHaveTextContent("Travel");
    expect(rows[1]).toHaveTextContent("Investment");
    // today: "Today" quietly, in place of a figure
    expect(within(rows[2]).getByText("Today")).toHaveClass("is-today");
    // soon: a plain Look; the row is a link to where it is settled
    expect(within(rows[4]).getByText("Look")).toHaveClass("is-soon");
    expect(within(rows[4]).getByRole("link")).toHaveAttribute("href", "/accounting/budgets");
    expect(within(today).queryByText("Now")).toBeNull();
  });

  it("writes the market and the trip as rows, from the user's own figures, and none says how many things there are", async () => {
    serve({ home: [item("Rent due tomorrow", "soon")], today: session([mover("NVDA", "-5.1")]), next: trip("upcoming") });
    renderHome();
    const today = await region();
    expect(await within(today).findByText("NVDA is down 5% today")).toBeInTheDocument();
    expect(within(today).getByText("Rent due tomorrow")).toBeInTheDocument();
    expect(today).not.toHaveTextContent(/\bthings? need/);
    expect(within(today).getByRole("link", { name: /NVDA is down 5% today/ })).toHaveAttribute("href", "/investment/stocks/NVDA");
    // The trip is 12 days away with nothing missing: not a row of today's.
    expect(today).not.toHaveTextContent("Tokyo");
  });

  it("keeps an item's first action as its word at the right, a text button that settles it there", async () => {
    const actions = [{ key: "went", label: "It went through", method: "POST", path: "/bills/m1/paid" }];
    const calls = mockApi({
      "GET /home": () => [item("Your IBKR top-up hasn't shown up", "soon", { actions })],
      "POST /bills/m1/paid": () => null,
    });
    renderHome();
    const button = await screen.findByRole("button", { name: "It went through" });
    expect(button).toHaveClass("btn-ghost");
    expect(button).not.toHaveClass("btn-primary");
    await userEvent.setup().click(button);
    await waitFor(() => expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/bills/m1/paid"]));
  });

  it("keeps a second action reachable as a quieter text button", async () => {
    const paid: FeedAction = { key: "paid", label: "Mark paid", method: "POST", path: "/bills/b1/paid" };
    const later: FeedAction = { key: "later", label: "Remind me later today", method: "POST", path: "/bills/b1/snooze" };
    mockApi({ "GET /home": () => [item("Rent due tomorrow", "soon", { actions: [paid, later] })] });
    renderHome();
    const first = await screen.findByRole("button", { name: "Mark paid" });
    const second = screen.getByRole("button", { name: "Remind me later today" });
    expect(first).toHaveClass("today-word");
    expect(second).toHaveClass("today-quiet");
    expect(first.closest("li")).toHaveClass("today-multi");
  });
});

describe("Home: buttons that settle an item", () => {
  const post = (calls: ReturnType<typeof mockApi>) => calls.filter((c) => c.method === "POST");

  it("sends an action's body as JSON, and sends none when it has none", async () => {
    const merge: FeedAction = { key: "merge", label: "Same one", method: "POST", path: "/transactions/t1/merge", body: { other_id: "t2" } };
    const log: FeedAction = { key: "log", label: "Log it", method: "POST", path: "/email/e1/log", body: {} };
    const skip: FeedAction = { key: "skip", label: "Skip", method: "POST", path: "/email/e1/skip", body: null };
    const calls = mockApi({
      "GET /home": () => [
        item("Grab, 23.40 SGD, may be logged twice", "soon", { kind: "duplicates", actions: [merge] }),
        item("Grab receipt, 18.90 SGD, from your email", "soon", { kind: "email", actions: [log, skip] }),
      ],
      "POST /transactions/t1/merge": () => ({ kept: {}, removed: {} }),
      "POST /email/e1/log": () => new Response(null, { status: 204 }),
      "POST /email/e1/skip": () => new Response(null, { status: 204 }),
    });
    renderHome();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Same one" }));
    await waitFor(() => expect(post(calls)).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: "Log it" }));
    await waitFor(() => expect(post(calls)).toHaveLength(2));
    await user.click(screen.getByRole("button", { name: "Skip" }));
    await waitFor(() => expect(post(calls)).toHaveLength(3));
    expect(post(calls).map((c) => [c.path, c.body])).toEqual([
      ["/transactions/t1/merge", { other_id: "t2" }],
      ["/email/e1/log", {}],
      ["/email/e1/skip", undefined],
    ]);
  });

  it("shows what the API said, for a moment, once the item is settled", async () => {
    const paid: FeedAction = { key: "paid", label: "Mark paid", method: "POST", path: "/bills/b1/paid?due=2026-10-23" };
    let settled = false;
    mockApi({
      "GET /home": () => (settled ? [] : [item("Rent (1,800.00 SGD) due tomorrow", "soon", { actions: [paid] })]),
      "POST /bills/b1/paid": () => {
        settled = true;
        return { message: "Marked Rent (23 Oct) as paid and logged 1,800.00 SGD in this month's spending.", logged: true };
      },
    });
    renderHome();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Mark paid" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Marked Rent (23 Oct) as paid and logged 1,800.00 SGD");
    await waitFor(() => expect(screen.queryByRole("button", { name: "Mark paid" })).toBeNull());
    await userEvent.setup().click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows nothing extra when the response has no message", async () => {
    const snooze: FeedAction = { key: "snooze", label: "Remind me later", method: "POST", path: "/bills/b1/snooze" };
    const calls = mockApi({
      "GET /home": () => [item("Rent due tomorrow", "soon", { actions: [snooze] })],
      "POST /bills/b1/snooze": () => new Response(null, { status: 204 }),
    });
    renderHome();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Remind me later" }));
    await waitFor(() => expect(post(calls)).toHaveLength(1));
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("fetches again what shows it: Home, the Email page and the ledger with its duplicates", async () => {
    const skip: FeedAction = { key: "skip", label: "Skip", method: "POST", path: "/email/e1/skip" };
    const calls = mockApi({
      "GET /home": () => [item("Grab receipt, 18.90 SGD, from your email", "soon", { kind: "email", actions: [skip] })],
      "GET /email": () => ({ emails: [] }),
      "GET /transactions/probe": () => ({ items: [], total: 0 }),
      "POST /email/e1/skip": () => new Response(null, { status: 204 }),
    });
    // The Email page and the ledger are not on Home; their data is in the same cache.
    function Elsewhere() {
      useQuery({ queryKey: ["email"], queryFn: () => api("/email") });
      useQuery({ queryKey: ["transactions", "page"], queryFn: () => api("/transactions/probe") });
      return null;
    }
    renderWithProviders(
      <>
        <Home me={me} onLog={vi.fn()} />
        <Elsewhere />
      </>,
    );
    const user = userEvent.setup();
    const count = (path: string) => calls.filter((c) => c.method === "GET" && c.path === path).length;
    await user.click(await screen.findByRole("button", { name: "Skip" }));
    await waitFor(() => expect(post(calls)).toHaveLength(1));
    await waitFor(() => expect([count("/home"), count("/email"), count("/transactions/probe")]).toEqual([2, 2, 2]));
  });

  it("says so when a button's request fails, and keeps the item", async () => {
    const log: FeedAction = { key: "log", label: "Log it", method: "POST", path: "/email/e1/log", body: {} };
    mockApi({
      "GET /home": () => [item("Grab receipt, 18.90 SGD, from your email", "soon", { kind: "email", actions: [log] })],
      "POST /email/e1/log": () => new Response(JSON.stringify({ detail: "that email was already dealt with" }), { status: 409 }),
    });
    renderHome();
    await userEvent.setup().click(await screen.findByRole("button", { name: "Log it" }));
    // The cards whose requests the test leaves unmocked say so too: this alert is the one in For today.
    expect(await within(await screen.findByRole("region", { name: "For today" })).findByRole("alert")).toHaveTextContent("that email was already dealt with");
    expect(screen.getByRole("button", { name: "Log it" })).toBeEnabled();
  });
});

describe("Home: when a load fails", () => {
  const failing = (status = 500) => new Response(JSON.stringify({ detail: "boom" }), { status });

  it("never says Nothing for today. when what is for today could not be loaded, and Retry fetches it again", async () => {
    let up = false;
    mockApi({
      "GET /home": () => (up ? [item("Rent due tomorrow", "soon")] : failing()),
      "GET /runs": () => [],
      "GET /summary": () => summary,
      "GET /spending/months": () => spending,
      "GET /budgets": () => [],
      "GET /budgets/month": () => null,
      "GET /investments": () => empty,
      "GET /investments/today": () => session([]),
      "GET /travel/next": () => null,
      "GET /setup": () => setup([true, true, true, true]),
    });
    renderHome();
    const needs = await screen.findByRole("region", { name: "For today" });
    expect(await within(needs).findByRole("alert")).toHaveTextContent("Couldn't load what's for today.");
    const hero = screen.getByRole("region", { name: "This month" });
    await waitFor(() => expect(hero).toHaveTextContent("412.00"));
    expect(screen.queryByText("Nothing for today.")).toBeNull();
    up = true;
    await userEvent.setup().click(within(needs).getByRole("button", { name: "Retry" }));
    expect(await within(needs).findByText("Rent due tomorrow")).toBeInTheDocument();
  });

  it("says so, with a Retry, where the month's money and the other cards would be", async () => {
    mockApi({
      "GET /home": () => [],
      "GET /runs": () => [],
      "GET /summary": () => failing(),
      "GET /spending/months": () => spending,
      "GET /budgets": () => [],
      "GET /budgets/month": () => null,
      "GET /investments": () => failing(),
      "GET /investments/today": () => session([]),
      "GET /travel/next": () => failing(),
      "GET /setup": () => setup([true, true, true, true]),
    });
    renderHome();
    const money = await screen.findByRole("region", { name: "Money this month" });
    expect(await within(money).findByRole("alert")).toHaveTextContent("Couldn't load this month's spending.");
    expect(within(money).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(money).not.toHaveTextContent("Loading…");
    const hero = screen.getByRole("region", { name: "This month" });
    expect(within(hero).getByRole("alert")).toHaveTextContent("Couldn't load this month's spending.");
    expect(hero).not.toHaveTextContent("…");
    const portfolio = screen.getByRole("region", { name: "Portfolio today" });
    expect(await within(portfolio).findByRole("alert")).toHaveTextContent("Couldn't load your portfolio.");
    expect(portfolio).not.toHaveTextContent("No holdings yet.");
    const trip = screen.getByRole("region", { name: "Next trip" });
    expect(await within(trip).findByRole("alert")).toHaveTextContent("Couldn't load your next trip.");
    expect(trip).not.toHaveTextContent("No trip coming up.");
  });
});

describe("Home: Get started", () => {
  it("is the one first-run card, under For today, with the steps the person has left", async () => {
    mockApi({
      "GET /home": () => [item("Rent due tomorrow", "soon")],
      "GET /config": () => ({ bot_username: "made_up_bot" }),
      "GET /transactions": () => ({ items: [], total: 0 }),
      "GET /setup": () => setup([false, false, true, false]),
    });
    renderHome();
    const card = await screen.findByRole("region", { name: "Get started" });
    expect(within(card).getAllByRole("listitem")).toHaveLength(4);
    const needs = await screen.findByRole("region", { name: "For today" });
    expect(needs.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The old checklist is gone: no second card, no "Get set up".
    expect(screen.queryByRole("region", { name: "Get set up" })).toBeNull();
  });

  it("is not shown once dismissed, once everything is done, or when the server refuses", async () => {
    const answers: (Setup | null)[] = [setup(undefined, true), setup([true, true, true, true]), null];
    for (const answer of answers) {
      mockApi({
        "GET /home": () => [],
        "GET /runs": () => [],
        "GET /summary": () => summary,
        "GET /spending/months": () => spending,
        "GET /budgets": () => [],
        "GET /budgets/month": () => null,
        "GET /investments": () => empty,
        "GET /investments/today": () => session([]),
        "GET /travel/next": () => null,
        "GET /config": () => ({ bot_username: "made_up_bot" }),
        "GET /transactions": () => ({ items: [], total: 1 }),
        "GET /setup": () => (answer === null ? new Response("{}", { status: 403 }) : answer),
      });
      const { unmount } = renderHome();
      await screen.findByRole("region", { name: "For today" });
      // Everything Home asks has answered once the glance cards have.
      await waitFor(() => expect(screen.getByRole("region", { name: "Money this month" })).toHaveTextContent("SGD"));
      expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
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
    expect(card).toHaveTextContent(/Teahouse in Asakusa.*Next.*14:00/s);
    expect(card).not.toHaveTextContent("Market walk");
    expect(card).toHaveTextContent(/Spent today.*SGD.300\.00 a day left in your budget.*SGD.42\.00/s);
    expect(card).toHaveTextContent(/ZZ13 NRT → SIN.*Next booking.*(24 Oct|Oct 24)/s);
    expect(card.querySelector("svg")).toBeNull(); // no leading icons
    // It leads For today, and the Next trip card gives way to it.
    const needs = screen.getByRole("region", { name: "For today" });
    expect(card.compareDocumentPosition(needs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Next trip" })).toBeNull();
    // What is next today is also a row of For today, with the trip as its sub-line.
    expect(within(needs).getByRole("link", { name: /Teahouse in Asakusa/ })).toHaveAttribute("href", "/travel/trips/t1");
    expect(needs).toHaveTextContent("Tokyo, from 14:00");
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

describe("Home: what moved to Money", () => {
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

describe("Home: the order of the sections", () => {
  const order = (names: string[]) => {
    const tops = names.map((n) => screen.getByRole("region", { name: n }));
    for (let i = 1; i < tops.length; i++)
      expect(tops[i - 1].compareDocumentPosition(tops[i]) & Node.DOCUMENT_POSITION_FOLLOWING, `${names[i - 1]} before ${names[i]}`).toBeTruthy();
  };
  const running = [{ id: "r1", title: "Plan for NVDA", status: "running", steps_done: 1, steps_total: 3, progress: "reading the news", error: null }];

  it("is the headline, the trip, For today, Working on, Get started, then Money, Portfolio and Next trip's place", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-21T03:00:00Z"));
    mockApi({
      "GET /home": () => [item("Rent due tomorrow", "soon")],
      "GET /runs": () => running,
      "GET /summary": () => summary,
      "GET /spending/months": () => spending,
      "GET /budgets": () => [],
      "GET /budgets/month": () => null,
      "GET /investments": () => held,
      "GET /investments/today": () => session([]),
      "GET /travel/next": () => trip("ongoing"),
      "GET /config": () => ({ bot_username: "made_up_bot" }),
      "GET /transactions": () => ({ items: [], total: 0 }),
      "GET /setup": () => setup([false, false, true, false]),
    });
    renderHome();
    await screen.findByRole("region", { name: "Get started" });
    await screen.findByRole("region", { name: "Working on" });
    await screen.findByRole("region", { name: "Day 3 in Tokyo" });
    order(["This month", "Day 3 in Tokyo", "For today", "Working on", "Get started", "Money this month", "Portfolio today"]);
    expect(screen.queryByRole("region", { name: "Next trip" })).toBeNull();
  });

  it("shows Next trip last when no trip is on, and leaves out Working on and Get started when there is none", async () => {
    serve({ next: trip("upcoming") });
    renderHome();
    await screen.findByRole("region", { name: "Next trip" });
    order(["This month", "For today", "Money this month", "Portfolio today", "Next trip"]);
    expect(screen.queryByRole("region", { name: "Working on" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Get started" })).toBeNull();
  });

  it("gives a run a title, a progress line, a thin bar and Cancel", async () => {
    const calls = mockApi({
      "GET /home": () => [],
      "GET /runs": () => running,
      "POST /runs/r1/cancel": () => null,
    });
    renderHome();
    const working = await screen.findByRole("region", { name: "Working on" });
    await within(working).findByText("Plan for NVDA");
    expect(working).toHaveTextContent("1/3 · reading the news");
    expect(within(working).getByRole("progressbar", { name: "Plan for NVDA progress" })).toHaveAttribute("aria-valuenow", "33");
    await userEvent.setup().click(within(working).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/runs/r1/cancel")).toBe(true));
  });
});
