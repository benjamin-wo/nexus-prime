import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ledgerParams, type Me, type Transaction } from "./api";
import { Amount } from "./components/Amount";
import { brief } from "./brief";
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
      <AddSheet trip={trip} preset={{ kind: "hotel" }} places={false} onScreenshot={() => {}} onForm={() => {}} onChanged={() => (changed += 1)} onClose={() => {}} />,
    );
    const user = userEvent.setup();
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

  it("only highlights the figures", () => {
    const parts = brief({ spent: sgd("10"), needs: [{ department: "accounting", kind: "bill", text: "x", link: "/", urgent: false }] });
    expect(parts.filter((p) => p.hl).map((p) => p.text)).toEqual([expect.stringMatching(/10\.00/)]);
    expect(text(parts)).toMatch(/ 1 thing needs you below\.$/);
  });
});
