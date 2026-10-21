import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Me, Page, Transaction } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { Ledger } from "./Ledger";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};

// Made-up entries: one filed under a category, one not.
const tx = (over: Partial<Transaction>): Transaction => ({
  id: "t1",
  direction: "out",
  amount: { amount: "12.40", currency: "SGD" },
  occurred_at: "2026-10-12T04:00:00Z",
  counterparty: "Corner Cafe",
  category_id: "c1",
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
  ...over,
});

function setup(items: Transaction[] = [tx({}), tx({ id: "t2", counterparty: "Mystery shop", category_id: null })]) {
  const onAdd = vi.fn();
  const onEdit = vi.fn();
  mockApi({
    "GET /transactions": () => ({ items, total: items.length }) satisfies Page,
    "GET /categories": () => [{ id: "c1", name: "Dining Out" }],
    "GET /category-rules": () => [],
  });
  renderWithProviders(<Ledger me={me} onAdd={onAdd} onEdit={onEdit} />);
  /** The query strings of the transaction lists asked for so far. */
  const asked = () =>
    vi
      .mocked(fetch)
      .mock.calls.map(([input]) => new URL(String(input), "http://localhost"))
      .filter((u) => u.pathname === "/api/transactions")
      .map((u) => u.searchParams);
  return { onAdd, onEdit, asked };
}

describe("the Ledger header", () => {
  it("has a compact Add and a More menu, not the three big buttons", async () => {
    const { onAdd } = setup();
    await screen.findByText("Corner Cafe");
    const add = screen.getByRole("button", { name: "Add transaction" });
    expect(add).toHaveTextContent("Add");
    expect(add).not.toHaveTextContent("Add transaction");
    await userEvent.click(add);
    expect(onAdd).toHaveBeenCalledTimes(1);
    // Import and export wait inside More.
    expect(screen.queryByRole("link", { name: "Import statement" })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: "Export CSV" })).toBeNull();
  });

  it("opens More as a menu with Import statement and Export CSV, and closes it on Escape", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    const more = screen.getByRole("button", { name: "More" });
    expect(more).toHaveAttribute("aria-haspopup", "menu");
    expect(more).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(more);
    expect(more).toHaveAttribute("aria-expanded", "true");
    const menu = screen.getByRole("menu", { name: "More" });
    const items = within(menu).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Import statement", "Export CSV"]);
    expect(items[0]).toHaveAttribute("href", "/settings/import");
    expect(items[1]).toHaveAttribute("href", expect.stringMatching(/^\/api\/export\.csv\?/));
    expect(items[1]).toHaveAttribute("download");
    expect(items[0]).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).toHaveFocus();
  });

  it("closes More when something else is pressed", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("searchbox"));
    expect(screen.queryByRole("menu")).toBeNull();
  });
});

describe("the Ledger filters", () => {
  it("keeps the type tabs and one Dates control instead of the date chips", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    const show = screen.getByRole("group", { name: "Show" });
    expect(within(show).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "All",
      "Money out",
      "Money in",
      "Moves",
      "Pending",
    ]);
    const dates = screen.getByRole("combobox", { name: "Dates" });
    expect(within(dates).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All dates",
      "This month",
      "Last month",
      "Custom",
    ]);
    expect(dates).toHaveValue("any");
    expect(screen.queryByRole("group", { name: "When" })).toBeNull();
    expect(screen.queryByLabelText("From")).toBeNull();
  });

  it("filters to a month from Dates, and Custom dates shows the two date boxes", async () => {
    const { asked } = setup();
    await screen.findByText("Corner Cafe");
    const dates = screen.getByRole("combobox", { name: "Dates" });
    await userEvent.selectOptions(dates, "this");
    await waitFor(() => expect(asked().some((p) => p.get("start") && !p.get("end"))).toBe(true));
    await userEvent.selectOptions(dates, "last");
    await waitFor(() => expect(asked().some((p) => p.get("start") && p.get("end"))).toBe(true));
    expect(screen.queryByLabelText("From")).toBeNull();

    await userEvent.selectOptions(dates, "custom");
    expect(dates).toHaveValue("custom");
    const from = screen.getByLabelText("From");
    expect(from).toHaveValue(asked().at(-1)?.get("start"));
    expect(screen.getByLabelText("To")).toBeInTheDocument();
    await userEvent.clear(from);
    await waitFor(() => expect(asked().at(-1)?.get("start")).toBeNull());

    await userEvent.selectOptions(dates, "any");
    expect(screen.queryByLabelText("From")).toBeNull();
  });
});

describe("the Ledger rows", () => {
  it("name the category under the merchant, for the phone, and leave it out when there is none", async () => {
    setup();
    const cafe = (await screen.findByRole("button", { name: "Corner Cafe" })).closest("tr")!;
    const caption = cafe.querySelector("td.merchant .category-line");
    expect(caption).toHaveTextContent("Dining Out");
    // The merchant button comes first, then the category.
    expect(caption?.previousElementSibling).toBe(within(cafe).getByRole("button", { name: "Corner Cafe" }));
    const mystery = screen.getByRole("button", { name: "Mystery shop" }).closest("tr")!;
    expect(mystery.querySelector(".category-line")).toBeNull();
  });
});
