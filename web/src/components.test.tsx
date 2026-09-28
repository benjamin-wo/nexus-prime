import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ledgerParams, type Me, type Transaction } from "./api";
import { CategoryBars } from "./components/CategoryBars";
import { ChatDrawer } from "./components/ChatDrawer";
import { formatMoney } from "./format";
import { Ledger } from "./pages/Ledger";
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

describe("formatting", () => {
  it("formats money exactly from strings", () => {
    expect(formatMoney({ amount: "1234.5000", currency: "SGD" })).toMatch(/1,234\.50/);
  });

  it("builds ledger query strings without empty values", () => {
    expect(ledgerParams({ direction: "out", search: "" }, { limit: 50 })).toBe("direction=out&limit=50");
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
