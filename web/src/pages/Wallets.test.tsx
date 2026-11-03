import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Me, Wallet } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { WalletsSection } from "./Wallets";

const me: Me = {
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};

const wallet = (over: Partial<Wallet>): Wallet => ({ id: "w", name: "Wallet", kind: "card", match_words: [], ...over });
const wallets: Wallet[] = [
  wallet({ id: "w-spending", name: "Spending", kind: "spending" }),
  wallet({ id: "w-cash", name: "Cash", kind: "cash" }),
  wallet({ id: "w-card", name: "Citi PremierMiles", issuer: "Citi", product: "PremierMiles", network: "visa", last4: "4321" }),
];

function setup() {
  const calls = mockApi({
    "GET /wallets": () => wallets,
    "GET /wallets/likely-moves": () => [],
    "GET /wallets/w-spending/spend": () => ({ month: "2026-11", total: { amount: "0.0000", currency: "SGD" }, count: 0 }),
    "GET /wallets/w-cash/spend": () => ({ month: "2026-11", total: { amount: "60.0000", currency: "SGD" }, count: 1 }),
    "GET /wallets/w-card/spend": () => ({ month: "2026-11", total: { amount: "1240.0000", currency: "SGD" }, count: 38 }),
    "PATCH /wallets/w-card": () => wallets[2],
    "PUT /wallets/usual-card": () => undefined,
  });
  renderWithProviders(<WalletsSection me={me} />);
  return calls;
}

describe("Wallets: card details", () => {
  it("shows a card with its last four digits and its details, and Cash without a Delete", async () => {
    setup();
    await userEvent.click(await screen.findByText("Manage"));
    const list = await screen.findByRole("list", { name: "Your wallets" });
    const card = within(list).getByRole("heading", { name: "Citi PremierMiles ·· 4321" }).closest("li")!;
    expect(card).toHaveTextContent("Citi · PremierMiles · Visa");
    const cash = within(list).getByRole("heading", { name: "Cash" }).closest("li")!;
    expect(within(cash).getByRole("button", { name: "Edit" })).toBeVisible();
    expect(within(cash).queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("keeps the last 4 digits of a pasted number and says so", async () => {
    const calls = setup();
    await userEvent.click(await screen.findByText("Manage"));
    const list = await screen.findByRole("list", { name: "Your wallets" });
    await userEvent.click(within(within(list).getByRole("heading", { name: /Citi/ }).closest("li")!).getByRole("button", { name: "Edit" }));

    const form = screen.getByRole("form", { name: "Edit Citi PremierMiles" });
    const last4 = within(form).getByLabelText("Last 4 digits");
    expect(last4).toHaveAttribute("inputmode", "numeric");
    expect(screen.queryByText("Only the last 4 digits are kept.")).toBeNull();
    await userEvent.clear(last4);
    await userEvent.click(last4);
    await userEvent.paste("1357 2468 1357 8765");
    expect(last4).toHaveValue("8765");
    expect(screen.getByText("Only the last 4 digits are kept.")).toBeVisible();

    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({ last4: "8765", issuer: "Citi", network: "visa" }));
  });

  it("sets and clears the usual card", async () => {
    const calls = setup();
    const usual = await screen.findByRole("combobox", { name: /Usual card/ });
    await waitFor(() => expect(within(usual).getAllByRole("option")).toHaveLength(4));
    expect(within(usual).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "None",
      "Citi PremierMiles ·· 4321",
      "Spending",
      "Cash",
    ]);
    await userEvent.selectOptions(usual, "w-card");
    await waitFor(() => expect(calls.find((c) => c.path === "/wallets/usual-card")?.body).toEqual({ wallet_id: "w-card" }));
    await userEvent.selectOptions(usual, "");
    await waitFor(() => expect(calls.filter((c) => c.path === "/wallets/usual-card").at(-1)?.body).toEqual({ wallet_id: null }));
  });

  it("says what each card paid for this month and links to the ledger for it", async () => {
    setup();
    const group = await screen.findByRole("group", { name: "Spend by card" });
    expect(await within(group).findByText("SGD 1,240.00 this month · 38 purchases")).toBeVisible();
    expect(await within(group).findByText("SGD 60.00 this month · 1 purchase")).toBeVisible();
    expect(within(group).getByRole("link", { name: "See in ledger for Citi PremierMiles ·· 4321" })).toHaveAttribute(
      "href",
      "/accounting/ledger?paid_with=w-card",
    );
  });
});
