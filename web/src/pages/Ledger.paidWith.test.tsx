import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Me, Page, Transaction, Wallet } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { Ledger } from "./Ledger";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
  preferences: { track_cards: true },
};

const wallet = (over: Partial<Wallet>): Wallet => ({ id: "w", name: "Wallet", kind: "card", match_words: [], ...over });
const wallets: Wallet[] = [
  wallet({ id: "w-spending", name: "Main account", kind: "spending" }),
  wallet({ id: "w-invest", name: "Investments", kind: "investment" }),
  wallet({ id: "w-savings", name: "Savings", kind: "savings" }),
  wallet({ id: "w-citi", name: "Citi PremierMiles", last4: "4321" }),
  wallet({ id: "w-cash", name: "Cash", kind: "cash" }),
];

const tx = (over: Partial<Transaction>): Transaction => ({
  id: "t1",
  direction: "out",
  amount: { amount: "12.40", currency: "SGD" },
  occurred_at: "2026-10-12T04:00:00Z",
  counterparty: "Corner Cafe",
  category_id: null,
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
  ...over,
});

function setup(route = "/", who: Me = me) {
  const items = [
    tx({ paid_with: { id: "w-citi", name: "Citi PremierMiles", kind: "card", last4: "4321" } }),
    tx({ id: "t2", counterparty: "Mystery shop" }),
  ];
  mockApi({
    "GET /transactions": () => ({ items, total: items.length }) satisfies Page,
    "GET /categories": () => [],
    "GET /category-rules": () => [],
    "GET /wallets": () => wallets,
  });
  renderWithProviders(<Ledger me={who} onAdd={vi.fn()} onEdit={vi.fn()} />, route);
  /** The query strings of the transaction lists asked for so far. */
  const asked = () =>
    vi
      .mocked(fetch)
      .mock.calls.map(([input]) => new URL(String(input), "http://localhost"))
      .filter((u) => u.pathname === "/api/transactions")
      .map((u) => u.searchParams);
  return { asked };
}

/** Opens the filter sheet, where Paid with lives. */
const openFilters = () => userEvent.click(screen.getByRole("button", { name: /^Filter/ }));

describe("Paid with in the Ledger", () => {
  it("names the card under the merchant, only where one is set", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    const cafe = screen.getByText("Corner Cafe").closest("tr")!;
    expect(within(cafe).getByText("Citi PremierMiles ·· 4321")).toHaveClass("caption");
    expect(screen.getByText("Mystery shop").closest("tr")!).not.toHaveTextContent("··");
  });

  it("offers cards, Spending and Cash and Not set, never an investment or savings wallet", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    await openFilters();
    const select = screen.getByRole("combobox", { name: "Paid with" });
    await waitFor(() =>
      expect(Array.from((select as HTMLSelectElement).options).map((o) => o.text)).toEqual([
        "Any",
        "Citi PremierMiles ·· 4321",
        "Main account",
        "Cash",
        "Not set",
      ]),
    );
  });

  it("filters by the card picked, keeps it in the address and shows a chip that clears it", async () => {
    const { asked } = setup();
    await screen.findByText("Corner Cafe");
    expect(asked().at(-1)?.get("paid_with")).toBeNull();

    await openFilters();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Paid with" }), "w-citi");
    await waitFor(() => expect(asked().at(-1)?.get("paid_with")).toBe("w-citi"));
    const clear = await screen.findByRole("button", { name: "Show every card, not just Citi PremierMiles ·· 4321" });

    await userEvent.click(clear);
    await waitFor(() => expect(asked().at(-1)?.get("paid_with")).toBeNull());
    expect(screen.queryByRole("button", { name: /Show every card/ })).toBeNull();
  });

  it("filters to entries with no card from the Not set option", async () => {
    const { asked } = setup();
    await screen.findByText("Corner Cafe");
    await openFilters();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Paid with" }), "none");
    await waitFor(() => expect(asked().at(-1)?.get("paid_with")).toBe("none"));
    expect(await screen.findByRole("button", { name: "Show every card, not just entries with no card set" })).toBeVisible();
  });

  it("counts the card with the other filters, names its chip by the card, and Clear takes it off with the rest", async () => {
    const { asked } = setup("/?view=out&paid_with=w-citi");
    await waitFor(() => expect(asked().at(-1)?.get("paid_with")).toBe("w-citi"));
    expect(await screen.findByRole("button", { name: "Filter, 2 active" })).toBeVisible();
    const chips = screen.getByRole("group", { name: "Active filters" });
    expect(within(chips).getByText("Citi PremierMiles ·· 4321")).toBeVisible();

    await openFilters();
    const sheet = screen.getByRole("dialog", { name: "Filter transactions" });
    expect(within(sheet).getByRole("combobox", { name: "Paid with" })).toHaveValue("w-citi");
    await userEvent.click(within(sheet).getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(asked().at(-1)?.get("paid_with")).toBeNull());
    expect(asked().at(-1)?.get("direction")).toBeNull();
    expect(within(sheet).getByRole("combobox", { name: "Paid with" })).toHaveValue("");
    expect(screen.queryByRole("group", { name: "Active filters" })).toBeNull();

    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("menuitem", { name: "Export CSV" })).toHaveAttribute("href", "/api/export.csv?");
  });

  it("calls the Not set filter 'No card set' on its chip", async () => {
    setup("/?paid_with=none");
    const chips = await screen.findByRole("group", { name: "Active filters" });
    expect(within(chips).getByText("No card set")).toBeVisible();
  });

  it("starts filtered when the address names a card, and the export carries it too", async () => {
    const { asked } = setup("/?paid_with=w-citi");
    await waitFor(() => expect(asked().at(-1)?.get("paid_with")).toBe("w-citi"));
    expect(await screen.findByRole("button", { name: "Show every card, not just Citi PremierMiles ·· 4321" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("menuitem", { name: "Export CSV" })).toHaveAttribute(
      "href",
      "/api/export.csv?paid_with=w-citi",
    );
  });
});

describe("Ledger with card tracking off", () => {
  const simple: Me = { ...me, preferences: { track_cards: false } };

  it("has no Paid with filter and no card under the merchant", async () => {
    setup("/", simple);
    await screen.findByText("Corner Cafe");
    expect(screen.queryByRole("combobox", { name: "Paid with" })).toBeNull();
    expect(screen.getByText("Corner Cafe").closest("tr")!).not.toHaveTextContent("Citi PremierMiles");
    expect(screen.queryByText("Citi PremierMiles ·· 4321")).toBeNull();
  });

  it("ignores a ?paid_with= left in the address: no chip, nothing asked for", async () => {
    const { asked } = setup("/?paid_with=w-citi", simple);
    await screen.findByText("Corner Cafe");
    expect(screen.queryByText("Paid with")).toBeNull();
    expect(asked().every((p) => !p.has("paid_with"))).toBe(true);
    expect(screen.getByText("Mystery shop")).toBeVisible();
  });

  it("treats a missing preference as off", async () => {
    setup("/", { ...me, preferences: undefined });
    await screen.findByText("Corner Cafe");
    expect(screen.queryByRole("combobox", { name: "Paid with" })).toBeNull();
  });
});
