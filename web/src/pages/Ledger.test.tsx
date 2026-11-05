import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

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

function setup(items: Transaction[] = [tx({}), tx({ id: "t2", counterparty: "Mystery shop", category_id: null })], route = "/") {
  const onAdd = vi.fn();
  const onEdit = vi.fn();
  mockApi({
    "GET /transactions": () => ({ items, total: items.length }) satisfies Page,
    "GET /categories": () => [{ id: "c1", name: "Dining Out" }],
    "GET /category-rules": () => [],
  });
  renderWithProviders(<Ledger me={me} onAdd={onAdd} onEdit={onEdit} />, route);
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

/** Opens the filter sheet from the one Filter button. */
const openSheet = async () => {
  await userEvent.click(screen.getByRole("button", { name: /^Filter/ }));
  return screen.getByRole("dialog", { name: "Filter transactions" });
};

describe("the Ledger filters", () => {
  it("is one row, a search and a Filter button, with no chips or counts while nothing is set", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    expect(screen.getByRole("searchbox", { name: "Search merchant or notes" })).toBeInTheDocument();
    const filter = screen.getByRole("button", { name: "Filter" });
    expect(filter).toHaveAttribute("aria-haspopup", "dialog");
    expect(filter).not.toHaveTextContent(/\d/);
    // The type, the dates and the card are in the sheet, not on the page.
    expect(screen.queryByRole("group", { name: "Show" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: "Dates" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Active filters" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens a labelled dialog with the type tabs and one Dates control", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    const sheet = await openSheet();
    expect(sheet).toHaveAttribute("aria-modal", "true");
    const show = within(sheet).getByRole("group", { name: "Show" });
    expect(within(show).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "All",
      "Money out",
      "Money in",
      "Transfers",
      "Pending",
    ]);
    const dates = within(sheet).getByRole("combobox", { name: "Dates" });
    expect(within(dates).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "All dates",
      "This month",
      "Last month",
      "Custom",
    ]);
    expect(dates).toHaveValue("any");
    expect(within(sheet).queryByLabelText("From")).toBeNull();
    // This sign-in does not track cards.
    expect(within(sheet).queryByRole("combobox", { name: "Paid with" })).toBeNull();
  });

  it("moves focus into the sheet, closes on Escape and gives focus back to the Filter button", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    const button = screen.getByRole("button", { name: "Filter" });
    const sheet = await openSheet();
    expect(sheet).toContainElement(document.activeElement as HTMLElement);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button).toHaveFocus();

    // The close button does the same.
    await openSheet();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button).toHaveFocus();
  });

  it("filters by type from the sheet: the count badge, a chip and the list follow, and the chip takes it off", async () => {
    const { asked } = setup();
    await screen.findByText("Corner Cafe");
    const sheet = await openSheet();
    await userEvent.click(within(sheet).getByRole("button", { name: "Money out" }));
    expect(within(sheet).getByRole("button", { name: "Money out" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(asked().at(-1)?.get("direction")).toBe("out"));
    // The Show N button counts what the filters match.
    const show = await within(sheet).findByRole("button", { name: "Show 2 transactions" });
    await userEvent.click(show);
    expect(screen.queryByRole("dialog")).toBeNull();

    const filter = screen.getByRole("button", { name: "Filter, 1 active" });
    expect(filter).toHaveTextContent("1");
    const chips = screen.getByRole("group", { name: "Active filters" });
    expect(within(chips).getByText("Money out")).toBeVisible();

    await userEvent.click(within(chips).getByRole("button", { name: "Show all types, not just Money out" }));
    await waitFor(() => expect(asked().at(-1)?.get("direction")).toBeNull());
    expect(screen.queryByRole("group", { name: "Active filters" })).toBeNull();
    expect(screen.getByRole("button", { name: "Filter" })).toBeInTheDocument();
  });

  it("filters to a month from Dates, and Custom dates shows the two date boxes", async () => {
    const { asked } = setup();
    await screen.findByText("Corner Cafe");
    const sheet = await openSheet();
    const dates = within(sheet).getByRole("combobox", { name: "Dates" });
    await userEvent.selectOptions(dates, "this");
    await waitFor(() => expect(asked().some((p) => p.get("start") && !p.get("end"))).toBe(true));
    await userEvent.selectOptions(dates, "last");
    await waitFor(() => expect(asked().some((p) => p.get("start") && p.get("end"))).toBe(true));
    expect(within(sheet).queryByLabelText("From")).toBeNull();
    // A usual range is a chip under its own name.
    expect(within(screen.getByRole("group", { name: "Active filters" })).getByText("Last month")).toBeInTheDocument();

    await userEvent.selectOptions(dates, "custom");
    expect(dates).toHaveValue("custom");
    const from = within(sheet).getByLabelText("From");
    expect(from).toHaveValue(asked().at(-1)?.get("start"));
    expect(within(sheet).getByLabelText("To")).toBeInTheDocument();
    await userEvent.clear(from);
    await waitFor(() => expect(asked().at(-1)?.get("start")).toBeNull());

    await userEvent.selectOptions(dates, "any");
    expect(within(sheet).queryByLabelText("From")).toBeNull();
    expect(screen.queryByRole("group", { name: "Active filters" })).toBeNull();
  });

  it("counts a date range once, names its chip by the dates, and the chip clears it", async () => {
    const { asked } = setup([tx({})], "/?start=2026-10-03&end=2026-10-09");
    await screen.findByText("Corner Cafe");
    await waitFor(() => expect(asked().at(-1)?.get("start")).toBe("2026-10-03"));
    expect(asked().at(-1)?.get("end")).toBe("2026-10-09");
    expect(screen.getByRole("button", { name: "Filter, 1 active" })).toBeInTheDocument();
    const chips = screen.getByRole("group", { name: "Active filters" });
    expect(within(chips).getByText("2026-10-03 to 2026-10-09")).toBeInTheDocument();
    await userEvent.click(within(chips).getByRole("button", { name: "Show all dates" }));
    await waitFor(() => expect(asked().at(-1)?.get("start")).toBeNull());
    expect(asked().at(-1)?.get("end")).toBeNull();
    expect(screen.queryByRole("group", { name: "Active filters" })).toBeNull();
  });

  it("starts filtered by type, dates and category from the address, with a chip and a count for each", async () => {
    const { asked } = setup(undefined, "/?view=out&start=2026-10-01&end=2026-10-31&category=c1");
    await screen.findByText("Corner Cafe");
    await waitFor(() => expect(asked().at(-1)?.get("direction")).toBe("out"));
    const last = asked().at(-1)!;
    expect(last.get("start")).toBe("2026-10-01");
    expect(last.get("end")).toBe("2026-10-31");
    expect(last.get("category_id")).toBe("c1");
    expect(screen.getByRole("button", { name: "Filter, 3 active" })).toBeInTheDocument();
    const chips = screen.getByRole("group", { name: "Active filters" });
    expect(within(chips).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual([
      "Show all types, not just Money out",
      "Show all dates",
      "Show every category, not just Dining Out",
    ]);
  });

  it("clears every filter with Clear and leaves the search alone", async () => {
    const { asked } = setup(undefined, "/?view=out&category=c1");
    await screen.findByText("Corner Cafe");
    await userEvent.type(screen.getByRole("searchbox"), "cafe");
    await waitFor(() => expect(asked().at(-1)?.get("search")).toBe("cafe"));
    const sheet = await openSheet();
    await userEvent.selectOptions(within(sheet).getByRole("combobox", { name: "Dates" }), "this");
    expect(screen.getByRole("button", { name: "Filter, 3 active" })).toBeInTheDocument();

    await userEvent.click(within(sheet).getByRole("button", { name: "Clear" }));
    await waitFor(() => {
      const last = asked().at(-1)!;
      expect(last.get("direction")).toBeNull();
      expect(last.get("start")).toBeNull();
      expect(last.get("category_id")).toBeNull();
      expect(last.get("search")).toBe("cafe");
    });
    expect(screen.getByRole("button", { name: "Filter" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Active filters" })).toBeNull();
    expect(within(sheet).getByRole("button", { name: "Clear" })).toBeDisabled();
    expect(screen.getByRole("searchbox")).toHaveValue("cafe");
  });

  it("keeps the type in the export link, and the count and Select where they were", async () => {
    setup();
    await screen.findByText("Corner Cafe");
    expect(screen.getByText("2 transactions")).toBeInTheDocument();
    const sheet = await openSheet();
    await userEvent.click(within(sheet).getByRole("button", { name: "Money in" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("menuitem", { name: "Export CSV" })).toHaveAttribute("href", "/api/export.csv?direction=in");
    await userEvent.keyboard("{Escape}");

    await userEvent.click(screen.getByRole("button", { name: "Select" }));
    expect(screen.getByRole("button", { name: "Done" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Corner Cafe/ }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
  });
});

describe("the Ledger rows", () => {
  it("name the category and the date in one line under the merchant, and leave the category out when there is none", async () => {
    setup();
    const cafe = (await screen.findByRole("button", { name: "Corner Cafe" })).closest("tr")!;
    const meta = cafe.querySelector("td.merchant .tx-meta")!;
    expect(meta.querySelector(".category-line")).toHaveTextContent("Dining Out");
    expect(meta.querySelector(".date-line")).toHaveTextContent(/Oct/);
    // The merchant button comes first, then that one line.
    expect(meta.previousElementSibling).toBe(within(cafe).getByRole("button", { name: "Corner Cafe" }));
    const mystery = screen.getByRole("button", { name: "Mystery shop" }).closest("tr")!;
    expect(mystery.querySelector(".category-line")).toBeNull();
    expect(mystery.querySelector(".tx-meta .date-line")).toBeInTheDocument();
  });

  it("put the receipt link in that line, still a link to the receipt", async () => {
    setup([tx({ has_receipt: true })]);
    const row = (await screen.findByRole("button", { name: "Corner Cafe" })).closest("tr")!;
    const link = within(row).getByRole("link", { name: "Receipt" });
    expect(link.closest(".tx-meta")).not.toBeNull();
    expect(link).toHaveAttribute("href", expect.stringContaining("/transactions/t1/receipt"));
  });

  it("open the entry from the merchant button", async () => {
    const { onEdit } = setup();
    await userEvent.click(await screen.findByRole("button", { name: "Corner Cafe" }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: "t1" }));
  });
});

describe("the floating Add", () => {
  /** A stand-in for the browser's IntersectionObserver that lets a test say whether the header's Add is in view. */
  function watchHeader() {
    let callback: IntersectionObserverCallback = () => {};
    const observe = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: IntersectionObserverCallback) {
          callback = cb;
        }
        observe = observe;
        disconnect = vi.fn();
      },
    );
    return {
      observe,
      show: (inView: boolean) =>
        act(() => callback([{ isIntersecting: inView } as IntersectionObserverEntry], {} as IntersectionObserver)),
    };
  }

  afterEach(() => vi.unstubAllGlobals());

  it("appears only once the header's Add is out of view, and adds like it", async () => {
    const header = watchHeader();
    const { onAdd } = setup();
    await screen.findByText("Corner Cafe");
    expect(header.observe).toHaveBeenCalledWith(screen.getByRole("button", { name: "Add transaction" }));
    expect(screen.queryByRole("button", { name: "Add a transaction" })).toBeNull();

    header.show(false);
    const floating = screen.getByRole("button", { name: "Add a transaction" });
    // The header's button keeps its own name, so neither doubles the other.
    expect(screen.getAllByRole("button", { name: "Add transaction" })).toHaveLength(1);
    await userEvent.click(floating);
    expect(onAdd).toHaveBeenCalledTimes(1);

    header.show(true);
    expect(screen.queryByRole("button", { name: "Add a transaction" })).toBeNull();
  });
});
