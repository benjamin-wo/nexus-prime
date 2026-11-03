import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Me, Transaction, Wallet } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { EntrySheet } from "./EntrySheet";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};

const wallet = (over: Partial<Wallet>): Wallet => ({ id: "w", name: "Wallet", kind: "card", match_words: [], ...over });
const wallets: Wallet[] = [
  wallet({ id: "w-spending", name: "Spending", kind: "spending" }),
  wallet({ id: "w-invest", name: "Investments", kind: "investment" }),
  wallet({ id: "w-savings", name: "Savings", kind: "savings" }),
  wallet({ id: "w-citi", name: "Citi PremierMiles", last4: "4321", usual: true }),
  wallet({ id: "w-dbs", name: "DBS Altitude", last4: "8765" }),
  wallet({ id: "w-cash", name: "Cash", kind: "cash" }),
  wallet({ id: "w-other", name: "Wise", kind: "other" }),
];

const saved: Transaction = {
  id: "t9",
  direction: "out",
  amount: { amount: "5.00", currency: "SGD" },
  occurred_at: "2026-10-12T04:00:00Z",
  counterparty: "Kopi",
  category_id: null,
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
};

function setup(editing?: Transaction, list: Wallet[] = wallets) {
  const calls = mockApi({
    "GET /categories": () => [],
    "GET /wallets": () => list,
    "GET /transactions/suggestions": () => [],
    "POST /transactions": () => saved,
    "PATCH /transactions/t9": () => saved,
  });
  renderWithProviders(<EntrySheet me={me} editing={editing} onClose={vi.fn()} onSaved={vi.fn()} />);
  return calls;
}

const select = () => screen.getByRole("combobox", { name: "Paid with" }) as HTMLSelectElement;
const written = (calls: ReturnType<typeof mockApi>) =>
  calls.find((c) => c.path === "/transactions" || c.path === "/transactions/t9")?.body as Record<string, unknown>;

describe("Paid with in the entry sheet", () => {
  it("lists cards, Spending, Cash and Other wallets, then Not set, and never investment or savings", async () => {
    setup();
    await waitFor(() =>
      expect(Array.from(select().options).map((o) => o.text)).toEqual([
        "Citi PremierMiles ·· 4321",
        "DBS Altitude ·· 8765",
        "Spending",
        "Cash",
        "Wise",
        "Not set",
      ]),
    );
  });

  it("starts on the usual card and saves it without sending a choice nobody made", async () => {
    const calls = setup();
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.type(screen.getByLabelText("Amount"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toBeDefined());
    expect(written(calls)).not.toHaveProperty("paid_with_wallet_id");
  });

  it("sends the card picked, and null for Not set", async () => {
    const calls = setup();
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.selectOptions(select(), "w-dbs");
    await userEvent.type(screen.getByLabelText("Amount"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toMatchObject({ paid_with_wallet_id: "w-dbs" }));
  });

  it("sends null when Not set is picked over the usual card", async () => {
    const calls = setup();
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.selectOptions(select(), "");
    await userEvent.type(screen.getByLabelText("Amount"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toMatchObject({ paid_with_wallet_id: null }));
  });

  it("shows what an entry was paid with and changes it", async () => {
    const calls = setup({ ...saved, paid_with: { id: "w-dbs", name: "DBS Altitude", kind: "card", last4: "8765" } });
    await waitFor(() => expect(select().options.length).toBeGreaterThan(2));
    expect(select().value).toBe("w-dbs");
    await userEvent.selectOptions(select(), "w-cash");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toMatchObject({ paid_with_wallet_id: "w-cash" }));
  });

  it("starts on Not set for an old entry, even with a usual card", async () => {
    setup(saved);
    await waitFor(() => expect(select().options.length).toBeGreaterThan(1));
    expect(select().value).toBe("");
  });

  it("is not there for money in or a move", async () => {
    setup();
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.click(screen.getByRole("button", { name: "Money in" }));
    expect(screen.queryByLabelText("Paid with")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Move" }));
    expect(screen.queryByLabelText("Paid with")).toBeNull();
  });
});
