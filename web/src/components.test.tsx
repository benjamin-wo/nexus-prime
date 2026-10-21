import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ledgerParams, type Me, type Reply, type Transaction } from "./api";
import { Amount } from "./components/Amount";
import { brief, monthShare, notableMove, pace } from "./brief";
import { CategoryBars } from "./components/CategoryBars";
import { ChatDrawer } from "./components/ChatDrawer";
import { formatMoney } from "./format";
import { conversionNote } from "./pages/Dashboard";
import { Ledger } from "./pages/Ledger";
import { AddSheet } from "./pages/TripAdd";
import { readInitData } from "./telegram";
import { mockApi, renderWithProviders } from "./testing";

const me: Me = {
  user: { telegram_user_id: 1, role: "owner", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "csrf",
};

function tx(id: string, amount: string, counterparty: string): Transaction {
  return {
    id,
    direction: "out",
    amount: { amount, currency: "SGD" },
    occurred_at: "2026-09-27T04:00:00Z",
    counterparty,
    category_id: null,
    notes: null,
    status: "confirmed",
    source: "text",
    deleted: false,
  };
}

describe("Telegram Mini App", () => {
  it("reads the signed launch data from the URL fragment", () => {
    const data = "query_id=AAH&user=%7B%22id%22%3A1%7D&auth_date=1&hash=abc";
    const hash = `#${new URLSearchParams({ tgWebAppData: data, tgWebAppVersion: "8.0" })}`;
    expect(readInitData(hash)).toBe(data);
    expect(readInitData("")).toBeNull();
    expect(readInitData("#section")).toBeNull();
  });
});

describe("formatting", () => {
  it("formats money exactly from strings", () => {
    expect(formatMoney({ amount: "1234.5000", currency: "SGD" })).toMatch(/1,234\.50/);
    // Codes, never bare symbols: "$" would be ambiguous next to SGD.
    expect(formatMoney({ amount: "33.8", currency: "USD" })).toMatch(/USD\s?33\.80/);
    expect(formatMoney({ amount: "33.8", currency: "USD" })).not.toContain("$");
  });

  it("builds ledger query strings without empty values", () => {
    expect(ledgerParams({ direction: "out", search: "" }, { limit: 50 })).toBe("direction=out&limit=50");
  });
});

describe("foreign currency", () => {
  const usd: Transaction = { ...tx("u", "33.80", "Amazon"), amount: { amount: "33.8000", currency: "USD" } };

  it("leads with the home amount and keeps the original and dated rate", () => {
    renderWithProviders(
      <Amount
        tx={{
          ...usd,
          home: { amount: { amount: "43.6200", currency: "SGD" }, rate: "1.2905", rate_date: "2026-09-25" },
        }}
      />,
    );
    expect(screen.getByText(/SGD\s?43\.62/)).toBeInTheDocument();
    const caption = screen.getByTitle(/USD\s?33\.80 at 1\.2905, rate of .*2026/);
    expect(caption).toHaveTextContent(/USD\s?33\.80\s*at 1\.2905 · (25 Sep|Sep 25)$/);
    expect(screen.getByText(/25/)).toBeInTheDocument();
  });

  it("says so when no rate was available", () => {
    renderWithProviders(<Amount tx={{ ...usd, home: { amount: null, rate: null, rate_date: null } }} />);
    expect(screen.getByText(/USD\s?33\.80/)).toBeInTheDocument();
    expect(screen.getByText("No rate available to convert")).toBeInTheDocument();
  });

  it("describes what went into a converted total", () => {
    const base = { direction: "out" as const, total: { amount: "74.81", currency: "SGD" }, count: 3 };
    expect(conversionNote({ ...base, converted: [], unconverted: [] })).toBeUndefined();
    expect(
      conversionNote({
        ...base,
        converted: [{ amount: "50", currency: "USD" }],
        unconverted: [{ amount: "5000", currency: "JPY" }],
      }),
    ).toMatch(/^Includes USD\s?50\.00, converted\. JPY\s?5,000 left out: no rate$/);
  });
});

describe("CategoryBars", () => {
  it("labels every bar with text, not colour alone", () => {
    renderWithProviders(
      <CategoryBars
        rows={[
          { category_id: "a", category_name: "Food", total: { amount: "80", currency: "SGD" }, count: 4 },
          { category_id: null, category_name: null, total: { amount: "20", currency: "SGD" }, count: 1 },
        ]}
      />,
    );
    const list = screen.getByRole("list", { name: "Spending by category" });
    expect(within(list).getByText("Food")).toBeInTheDocument();
    expect(within(list).getByText("Uncategorised")).toBeInTheDocument();
    expect(within(list).getByText(/Food: .*80\.00 across 4 transactions/)).toBeInTheDocument();
  });

  it("has an empty state", () => {
    renderWithProviders(<CategoryBars rows={[]} />);
    expect(screen.getByText("No spending recorded in this period.")).toBeInTheDocument();
  });
});

describe("Ledger", () => {
  it("bulk deletes after confirming and can undo", async () => {
    const calls = mockApi({
      "GET /transactions": () => ({ items: [tx("t1", "5", "Kopi"), tx("t2", "9", "Grab")], total: 2 }),
      "GET /categories": () => [],
      "POST /transactions/bulk-delete": (body) => body,
      "POST /transactions/bulk-restore": (body) => body,
    });
    renderWithProviders(<Ledger me={me} onAdd={() => {}} onEdit={() => {}} />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: /Select Kopi/ }));
    await user.click(screen.getByRole("button", { name: "Delete selected" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Deleted 1 transaction.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/transactions/bulk-delete")?.body).toEqual({ ids: ["t1"] });

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/transactions/bulk-restore")).toBe(true));
    expect(await screen.findByText("Restored.")).toBeInTheDocument();
  });

  it("says when filters match nothing", async () => {
    mockApi({ "GET /transactions": () => ({ items: [], total: 0 }), "GET /categories": () => [] });
    renderWithProviders(<Ledger me={me} onAdd={() => {}} onEdit={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Money in" }));
    expect(await screen.findByText("Nothing matches these filters.")).toBeInTheDocument();
  });
});

describe("ChatDrawer", () => {
  it("shows confirmation buttons once and sends the press", async () => {
    const calls = mockApi({
      "POST /chat": () => [
        { text: "Delete Grab 12.00?", buttons: [[{ label: "Confirm", data: "hitl:abc:y" }, { label: "Cancel", data: "hitl:abc:n" }]] },
      ],
      "POST /chat/press": () => [{ text: "Deleted.", buttons: [] }],
    });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Message"), "delete the grab ride");
    await user.click(screen.getByRole("button", { name: "Send" }));
    await user.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(await screen.findByText("Deleted.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(calls.find((c) => c.path === "/chat/press")?.body).toEqual({ data: "hitl:abc:y" });
  });
});

describe("ChatDrawer while a reply is worked out", () => {
  it("shows Nexus typing, says it's still working after a while, and goes with the reply", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let answer: (replies: Reply[]) => void = () => {};
    mockApi({ "POST /chat": () => new Promise<Reply[]>((resolve) => (answer = resolve)) });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.type(screen.getByLabelText("Message"), "how much on food this month?");
    await user.click(screen.getByRole("button", { name: "Send" }));
    const typing = await screen.findByRole("status", { name: "Nexus is typing" });
    expect(typing).not.toHaveTextContent("Still working");
    act(() => vi.advanceTimersByTime(10_000));
    expect(typing).toHaveTextContent("Still working on it…");
    act(() => answer([{ text: "S$412 on food so far.", buttons: [] }]));
    expect(await screen.findByText("S$412 on food so far.")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Nexus is typing" })).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});

describe("ChatDrawer in browsers where scrollIntoView returns a promise", () => {
  it("keeps working across several messages", async () => {
    // Chrome 153+ returns a promise here; an effect must not hand it to React as a cleanup.
    Element.prototype.scrollIntoView = function () {
      return Promise.resolve() as unknown as void;
    };
    mockApi({ "POST /chat": () => [{ text: "Noted.", buttons: [] }] });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    for (const message of ["one", "two", "three"]) {
      await user.type(screen.getByLabelText("Message"), message);
      await user.click(screen.getByRole("button", { name: "Send" }));
      await screen.findByText(message);
    }
    expect(await screen.findAllByText("Noted.")).toHaveLength(3);
  });
});

describe("A trip's Type it in browsers where scrollIntoView returns a promise", () => {
  it("shows Nexus's reply and its buttons instead of crashing", async () => {
    Element.prototype.scrollIntoView = function () {
      return Promise.resolve() as unknown as void;
    };
    const calls = mockApi({
      "POST /chat": () => [{ text: "Add Hotel Ume, 2 nights, to your Tokyo trip?", buttons: [[{ label: "Confirm", data: "hitl:t:y" }]] }],
    });
    const trip = { id: "t1", destination: "Tokyo", start: "2026-11-10", end: "2026-11-15" } as unknown as import("./api").Trip;
    let changed = 0;
    renderWithProviders(
      <AddSheet trip={trip} preset={null} places={false} onScreenshot={() => {}} onChanged={() => (changed += 1)} onClose={() => {}} />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Type it" }));
    await user.type(screen.getByLabelText("Tell Nexus about a booking"), "Hotel Ume 13 to 15 Nov");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Add Hotel Ume, 2 nights, to your Tokyo trip?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/chat")?.body).toEqual({ message: expect.stringMatching(/^For my Tokyo trip \(.+\), add this: Hotel Ume 13 to 15 Nov$/) });
    expect(changed).toBe(1);
  });
});

describe("brief", () => {
  const sgd = (amount: string) => ({ amount, currency: "SGD" });
  const text = (parts: { text: string }[]) => parts.map((p) => p.text).join("");

  it("weighs the month against the budget, else last month", () => {
    const overall = { id: "b", category_id: null, name: "Overall", limit: sgd("1000"), spent: sgd("412"), remaining: sgd("588"), percent: 41, unconverted: [] };
    expect(text(brief({ spent: sgd("412"), overall }))).toMatch(/^You've spent SGD\s?412\.00 this month, SGD\s?588\.00 left in your budget\.$/);
    expect(text(brief({ spent: sgd("1200"), overall }))).toMatch(/SGD\s?200\.00 over your budget\.$/);
    expect(text(brief({ spent: sgd("300"), lastMonthToDate: sgd("400") }))).toMatch(/SGD\s?100\.00 less than by this time last month\.$/);
    expect(text(brief({}))).toMatch(/^Nothing needs you right now/);
  });

  it("says when less is left to spend than the budget shows, and only then", () => {
    const overall = { id: "b", category_id: null, name: "Overall", limit: sgd("2000"), spent: sgd("600"), remaining: sgd("1400"), percent: 30, unconverted: [] };
    const plan = (over: object = {}) => ({
      currency: "SGD",
      total_out: sgd("2600"),
      left_to_spend: sgd("1100"),
      still_due_out: sgd("1300"),
      income: sgd("5000"),
      budget_left: sgd("1400"),
      tighter: "left_to_spend" as const,
      plan_warning: null,
      skipped: [],
      ...over,
    });
    const said = text(brief({ overall, plan: plan() }));
    expect(said).toMatch(/^Left to spend is SGD\s?1,100\.00 after what's still due — less than your SGD\s?1,400\.00 budget left\.$/);
    const lit = brief({ overall, plan: plan() }).filter((p) => p.hl).map((p) => p.text);
    expect(lit).toEqual([expect.stringMatching(/1,100\.00/), expect.stringMatching(/1,400\.00/)]);
    // The budget is the tighter one, there is no overall budget, or there is no plan: nothing to add.
    expect(text(brief({ overall, plan: plan({ tighter: "budget", left_to_spend: sgd("1800") }) }))).toMatch(/^Nothing needs you/);
    expect(text(brief({ plan: plan() }))).toMatch(/^Nothing needs you/);
    expect(text(brief({ overall, plan: plan({ budget_left: null, tighter: null }) }))).toMatch(/^Nothing needs you/);
    expect(text(brief({ overall }))).toMatch(/^Nothing needs you/);
    // It sits before the rest of the brief.
    const needs = [{ department: "accounting", kind: "bill", text: "x", link: "/", urgent: false, when: "soon" as const, actions: [] }];
    expect(text(brief({ overall, plan: plan(), needs }))).toMatch(/budget left\. 1 thing needs you below\.$/);
  });

  describe("across areas", () => {
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

    it("adds one short market clause after the money, with the figure lit", () => {
      const move = notableMove(today([mover("NVDA", "-5.1")]));
      const parts = brief({ spent: sgd("300"), lastMonthToDate: sgd("400"), move });
      expect(text(parts)).toMatch(/^You've spent SGD\s?300\.00 this month, SGD\s?100\.00 less than by this time last month\. NVDA is down 5% today\.$/);
      expect(parts.filter((p) => p.hl).map((p) => p.text)).toEqual([expect.stringMatching(/300\.00/), expect.stringMatching(/100\.00/), "5%"]);
      expect(text(brief({ move: notableMove(today([mover("AMD", "4.4")])) }))).toBe("AMD is up 4% today.");
      // After the close, and before the next open, it says which session.
      expect(text(brief({ move: notableMove(today([mover("AMD", "4.4")], "closed_today")) }))).toBe("AMD rose 4% today.");
      expect(text(brief({ move: notableMove(today([mover("NVDA", "-5.1")], "previous")) }))).toBe("NVDA fell 5% in the last session.");
    });

    it("says money, then the market, then the trip, then what needs the person", () => {
      const move = notableMove(today([mover("NVDA", "-5.1")]));
      const trip = {
        trip: { destination: "Tokyo", status: "ongoing", day_number: 3, days: 6 },
        ready: { nights_without_stay: [] },
      } as unknown as Parameters<typeof brief>[0]["trip"];
      const needs = [{ department: "investment", kind: "plan_hit", text: "x", link: "/", urgent: true, when: "now" as const, actions: [] }];
      expect(text(brief({ spent: sgd("300"), move, trip, needs }))).toMatch(
        /^You've spent SGD\s?300\.00 this month\. NVDA is down 5% today\. You're on day 3 of 6 in Tokyo\. 1 thing needs you below\.$/,
      );
    });
  });

  it("only highlights the figures", () => {
    const parts = brief({ spent: sgd("10"), needs: [{ department: "accounting", kind: "bill", text: "x", link: "/", urgent: false, when: "soon" as const, actions: [] }] });
    expect(parts.filter((p) => p.hl).map((p) => p.text)).toEqual([expect.stringMatching(/10\.00/)]);
    expect(text(parts)).toMatch(/ 1 thing needs you below\.$/);
  });
});

describe("pace", () => {
  const sgd = (amount: string) => ({ amount, currency: "SGD" });
  const budget = (percent: number) => ({ id: "b", category_id: null, name: "Overall", limit: sgd("1000"), spent: sgd(String(percent * 10)), remaining: sgd("0"), percent, unconverted: [] });
  const midMonth = new Date("2026-10-16T04:00:00Z"); // 16 of 31 in Singapore: 52%

  it("works out how far through the month it is on the user's calendar", () => {
    expect(monthShare("Asia/Singapore", midMonth)).toBe(52);
    expect(monthShare("Asia/Singapore", new Date("2026-02-28T04:00:00Z"))).toBe(100);
    // 17:00 UTC on the 15th is already the 16th in Singapore.
    expect(monthShare("Asia/Singapore", new Date("2026-10-15T17:00:00Z"))).toBe(52);
    expect(monthShare("America/New_York", new Date("2026-10-15T17:00:00Z"))).toBe(48);
  });

  it("compares the share of the budget used with the share of the month gone", () => {
    const at = (percent: number) => pace({ overall: budget(percent), timezone: "Asia/Singapore", now: midMonth });
    expect(at(70)).toMatchObject({ label: "Ahead of pace", ahead: true, used: 70, detail: "70% of your budget used, 52% through the month" });
    expect(at(50)).toMatchObject({ label: "On pace", ahead: false });
    expect(at(40)).toMatchObject({ label: "Under pace", ahead: false });
  });

  it("falls back to last month by this date, and to nothing", () => {
    expect(pace({ lastMonthToDate: sgd("1200"), timezone: "Asia/Singapore", now: midMonth })?.detail).toMatch(/^Last month by now: SGD\s?1,200\.00$/);
    expect(pace({ lastMonthToDate: sgd("1200"), timezone: "Asia/Singapore", now: midMonth })?.label).toBeUndefined();
    expect(pace({ timezone: "Asia/Singapore", now: midMonth })).toBeNull();
  });
});
