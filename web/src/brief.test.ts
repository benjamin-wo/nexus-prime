import { describe, expect, it } from "vitest";

import type { Budget, BudgetMonth, FeedItem, TripDetail } from "./api";
import { dateLabel, forToday, headline, notableMove, type Part } from "./brief";

const sgd = (amount: string) => ({ amount, currency: "SGD" });
const text = (parts: Part[]) => parts.map((p) => p.text).join("");
const budget = (limit: string): Budget => ({
  id: "b", category_id: null, name: "Overall", limit: sgd(limit), spent: sgd("0"), remaining: sgd("0"), percent: 0, unconverted: [],
});
const need = (over: Partial<FeedItem> = {}): FeedItem => ({
  department: "accounting", kind: "bill", text: "Rent due tomorrow", link: "/accounting/budgets", urgent: false, when: "soon", actions: [], ...over,
});

describe("dateLabel", () => {
  it("is the weekday, day and month on the user's calendar", () => {
    expect(dateLabel("Asia/Singapore", new Date("2026-11-22T04:00:00Z"))).toBe("Sunday, 22 November");
    // 17:00 UTC is already the next day in Singapore.
    expect(dateLabel("Asia/Singapore", new Date("2026-11-22T17:00:00Z"))).toBe("Monday, 23 November");
  });
});

describe("headline", () => {
  const noon = new Date("2026-11-22T04:00:00Z"); // 22 November in Singapore: 8 days to go
  const at = (over: Omit<Parameters<typeof headline>[0], "timezone" | "now">) => headline({ timezone: "Asia/Singapore", now: noon, ...over });

  it("is null until the month's spending is known", () => {
    expect(at({})).toBeNull();
  });

  it("with a budget says what is left, a day's worth for the days to come, and the comparison in words", () => {
    const h = at({ spent: sgd("1000"), overall: budget("3000"), lastMonthToDate: sgd("1500") })!;
    expect(h).toMatchObject({ over: false, kind: "left", figure: sgd("2000") });
    expect(text(h.sentence)).toBe("left for November. About 250 a day for the next 8 days, and 500.00 less spent than by this time in October.");
    expect(h.sentence.filter((p) => p.hl).map((p) => p.text)).toEqual(["250", "500.00"]);
    // More is said in words too.
    expect(text(at({ spent: sgd("1000"), overall: budget("3000"), lastMonthToDate: sgd("900") })!.sentence)).toContain("100.00 more spent than by this time in October");
  });

  it("rounds a day's worth to whole units", () => {
    // 2000 left over 8 days is 250; 2001 is 250.125, still 250; 2003 is 250.375, still 250; 2005 is 250.6, 251.
    expect(text(at({ spent: sgd("995"), overall: budget("3000") })!.sentence)).toBe("left for November. About 251 a day for the next 8 days.");
  });

  it("leaves the comparison out when last month's figure is not known, or is the same", () => {
    expect(text(at({ spent: sgd("1000"), overall: budget("3000") })!.sentence)).not.toContain("October");
    expect(text(at({ spent: sgd("1000"), overall: budget("3000"), lastMonthToDate: sgd("1000") })!.sentence)).not.toContain("October");
  });

  it("drops the a-day clause on the last day, in the singular on the one before", () => {
    const last = headline({ spent: sgd("1000"), overall: budget("3000"), lastMonthToDate: sgd("1500"), timezone: "Asia/Singapore", now: new Date("2026-11-30T04:00:00Z") })!;
    expect(text(last.sentence)).toBe("left for November, with 500.00 less spent than by this time in October.");
    const before = headline({ spent: sgd("1000"), overall: budget("3000"), timezone: "Asia/Singapore", now: new Date("2026-11-29T04:00:00Z") })!;
    expect(text(before.sentence)).toBe("left for November. About 2,000 a day for the next day.");
  });

  it("when over the budget shows the spending in rose and says by how much", () => {
    const h = at({ spent: sgd("3214"), overall: budget("3000"), lastMonthToDate: sgd("3000") })!;
    expect(h).toMatchObject({ over: true, kind: "spent", figure: sgd("3214") });
    expect(text(h.sentence)).toBe("spent, over for November by 214.00, and 214.00 more spent than by this time in October.");
    expect(text(h.sentence)).not.toContain("a day");
  });

  it("with no budget says what was spent, and the comparison", () => {
    const h = at({ spent: sgd("412"), lastMonthToDate: sgd("500") })!;
    expect(h).toMatchObject({ over: false, kind: "spent", figure: sgd("412") });
    expect(text(h.sentence)).toBe("spent in November, 88.00 less than by this time in October.");
    expect(text(at({ spent: sgd("412") })!.sentence)).toBe("spent in November.");
  });

  it("names the month before January's as December", () => {
    const h = headline({ spent: sgd("10"), lastMonthToDate: sgd("5"), timezone: "Asia/Singapore", now: new Date("2027-01-10T04:00:00Z") })!;
    expect(text(h.sentence)).toBe("spent in January, 5.00 more than by this time in December.");
  });
});

describe("notableMove", () => {
  const mover = (symbol: string, day_percent: string, held = true) => ({
    symbol, held, price: "131.50", day_percent, price_kind: "live" as const, price_at: null, price_day: "2026-09-28", headline: null,
  });
  const today = (movers: ReturnType<typeof mover>[], session: "live" | "closed_today" | "previous" = "live") => ({
    session, day: "2026-09-28", change: sgd("16.25"), percent: "0.96", price_kind: "live" as const, as_of_at: null, holds: true, movers, prices: true,
  });

  it("takes the held stock that moved most, when it moved by 3% or more", () => {
    expect(notableMove(today([mover("AMD", "1.2"), mover("NVDA", "-5.1")]))).toEqual({ symbol: "NVDA", percent: -5.1, session: "live" });
    expect(notableMove(today([mover("AMD", "2.9"), mover("NVDA", "-2.1")]))).toBeNull();
    expect(notableMove(today([mover("AMD", "3")]))).toMatchObject({ symbol: "AMD" });
    // A watched stock is not the user's, and no session is nothing to say.
    expect(notableMove(today([mover("AMD", "9", false)]))).toBeNull();
    expect(notableMove(undefined)).toBeNull();
    expect(notableMove(null)).toBeNull();
  });
});

describe("forToday", () => {
  const move = (percent: number, session: "live" | "closed_today" | "previous" = "live") => ({ symbol: "NVDA", percent, session });
  const trip = (status: "ongoing" | "upcoming", gaps = 0, days_until = 12) =>
    ({
      trip: { id: "t1", destination: "Tokyo", status, days_until, day_number: 3, days: 6 },
      ready: { nights_without_stay: Array.from({ length: gaps }, (_, i) => `2026-12-0${i + 1}`) },
    }) as unknown as TripDetail;

  it("has nothing for nothing", () => {
    expect(forToday({})).toEqual([]);
  });

  it("writes a market row from the move, by session", () => {
    expect(forToday({ move: move(-5.1) })[0]).toMatchObject({ title: "NVDA is down 5% today", word: "Look", link: "/investment/stocks/NVDA" });
    expect(forToday({ move: move(4.4, "closed_today") })[0].title).toBe("NVDA rose 4% today");
    expect(forToday({ move: move(-5.1, "previous") })[0].title).toBe("NVDA fell 5% in the last session");
  });

  it("writes a trip row: the next plan while it is on, lodging or a start close by while it is coming", () => {
    expect(forToday({ trip: trip("ongoing"), tripNext: { text: "Check in at Hotel Kumo", time: "15:00" } })[0]).toMatchObject({
      title: "Check in at Hotel Kumo", sub: "Tokyo, from 15:00", word: "Today", when: "today", link: "/travel/trips/t1",
    });
    expect(forToday({ trip: trip("ongoing"), tripNext: null })).toEqual([]);
    expect(forToday({ trip: trip("upcoming", 2) })[0]).toMatchObject({ title: "Tokyo still needs a place to stay", sub: "Starts in 12 days" });
    expect(forToday({ trip: trip("upcoming", 0, 1) })[0]).toMatchObject({ title: "Tokyo starts tomorrow" });
    // Far off and sorted out: nothing to do today.
    expect(forToday({ trip: trip("upcoming", 0, 12) })).toEqual([]);
  });

  it("puts what needs the person now first, then the trip and the market, then the rest in the server's order", () => {
    const rows = forToday({
      needs: [need({ text: "A soon" }), need({ text: "B now", when: "now" }), need({ text: "C today", when: "today" })],
      trip: trip("upcoming", 1),
      move: move(-5.1),
    });
    expect(rows.map((r) => r.title)).toEqual(["B now", "Tokyo still needs a place to stay", "NVDA is down 5% today", "A soon", "C today"]);
    expect(rows.find((r) => r.title === "C today")).toMatchObject({ word: "Today", when: "today" });
    expect(rows.find((r) => r.title === "B now")).toMatchObject({ word: "Look", when: "now", sub: "Money" });
  });

  it("says when less is left to spend than the budget shows, and when paying what is due tips it over", () => {
    const plan = (over: object = {}): BudgetMonth =>
      ({
        currency: "SGD", total_out: sgd("2600"), left_to_spend: sgd("1100"), still_due_out: sgd("1300"), income: sgd("5000"),
        budget_left: sgd("1400"), spending_due: sgd("300"), budget_left_after_due: sgd("1100"), tighter: "left_to_spend",
        plan_warning: null, skipped: [], ...over,
      }) as BudgetMonth;
    const overall = budget("2000");
    const tight = forToday({ overall, plan: plan() });
    expect(tight).toHaveLength(1);
    expect(tight[0].sub).toMatch(/^Left to spend is SGD\s?1,100\.00 after what's still due, below the SGD\s?1,400\.00 budget left\.$/);
    const over = forToday({ overall, plan: plan({ tighter: "budget", spending_due: sgd("515.95"), budget_left: sgd("373.44"), budget_left_after_due: sgd("-142.51") }) });
    expect(over[0].sub).toMatch(/^Once the SGD\s?515\.95 still due is paid you'll be SGD\s?142\.51 over\.$/);
    // Nothing to add: the budget is the tighter one, there is no budget, or no plan.
    expect(forToday({ overall, plan: plan({ tighter: "budget" }) })).toEqual([]);
    expect(forToday({ plan: plan() })).toEqual([]);
    expect(forToday({ overall })).toEqual([]);
  });

  it("never says how many things there are", () => {
    const rows = forToday({ needs: [need(), need({ text: "Other" })], trip: trip("upcoming", 2), move: move(-5.1) });
    for (const r of rows) expect(`${r.title} ${r.sub ?? ""} ${r.word}`).not.toMatch(/\bthings?\b|\d+ (items|things)/);
  });
});
