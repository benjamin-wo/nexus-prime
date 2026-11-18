import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Transaction } from "../api";
import { EditTransactionProvider } from "../editTransaction";
import { mockApi, renderWithProviders } from "../testing";
import { CategoryTransactions } from "./CategoryTransactions";

const tx = (id: string, amount: string, counterparty: string): Transaction => ({
  id,
  direction: "out",
  amount: { amount, currency: "SGD" },
  occurred_at: "2026-11-09T04:00:00Z",
  counterparty,
  category_id: "food",
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
});

const pick = { category: "food", start: "2026-11-01", end: "2026-11-30" };
const serve = () =>
  mockApi({ "GET /transactions": () => ({ items: [tx("t1", "6.38", "Pinduoduo"), tx("t2", "6.38", "Pinduoduo")], total: 2 }) });

describe("a category's transactions", () => {
  it("opens the edit sheet for the row tapped, when the app can edit", async () => {
    serve();
    const onEdit = vi.fn();
    renderWithProviders(
      <EditTransactionProvider onEdit={onEdit}>
        <CategoryTransactions pick={pick} name="Dining Out" timezone="Asia/Singapore" />
      </EditTransactionProvider>,
    );
    const list = await screen.findByRole("list", { name: "Dining Out transactions" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    const buttons = within(list).getAllByRole("button", { name: /^Edit Pinduoduo, SGD.6\.38, / });
    expect(buttons).toHaveLength(2);
    await userEvent.click(buttons[1]);
    expect(onEdit).toHaveBeenCalledTimes(1);
    expect(onEdit.mock.calls[0][0]).toMatchObject({ id: "t2", counterparty: "Pinduoduo" });
    // The link to the ledger is still there.
    expect(screen.getByRole("link", { name: "Open in the ledger" })).toBeInTheDocument();
  });

  it("only reads, with nothing to edit them with", async () => {
    serve();
    renderWithProviders(<CategoryTransactions pick={pick} name="Dining Out" timezone="Asia/Singapore" />);
    const list = await screen.findByRole("list", { name: "Dining Out transactions" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(within(list).queryAllByRole("button")).toHaveLength(0);
    expect(within(list).getAllByText("Pinduoduo")).toHaveLength(2);
  });
});
