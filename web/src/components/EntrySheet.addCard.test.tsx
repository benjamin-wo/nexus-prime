import { screen, waitFor, within } from "@testing-library/react";
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
const spending = wallet({ id: "w-spending", name: "Spending", kind: "spending" });
const cash = wallet({ id: "w-cash", name: "Cash", kind: "cash" });
const citi = wallet({ id: "w-citi", name: "Citi PremierMiles", last4: "4321" });
const dbs = wallet({ id: "w-dbs", name: "DBS Altitude", last4: "8765" });

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

type Handlers = Parameters<typeof mockApi>[0];

function setup(list: Wallet[], editing?: Transaction, extra: Handlers = {}) {
  let current = list;
  const calls = mockApi({
    "GET /categories": () => [],
    "GET /wallets": () => current,
    "GET /transactions/suggestions": () => [],
    "POST /transactions": () => saved,
    "PATCH /transactions/t9": () => saved,
    "POST /wallets": (body) => {
      const b = body as Record<string, string>;
      const made = wallet({ id: "w-new", name: b.name, issuer: b.issuer, product: b.product, last4: b.last4 });
      current = [...current, made];
      return made;
    },
    "PUT /wallets/usual-card": () => null,
    ...extra,
  });
  renderWithProviders(<EntrySheet me={me} editing={editing} onClose={vi.fn()} onSaved={vi.fn()} />);
  return calls;
}

const select = () => screen.getByRole("combobox", { name: "Paid with" }) as HTMLSelectElement;
const optionTexts = () => Array.from(select().options).map((o) => o.text);
const written = (calls: ReturnType<typeof mockApi>) =>
  calls.find((c) => c.path === "/transactions" || c.path === "/transactions/t9")?.body as Record<string, unknown>;
const newCard = () => screen.getByRole("form", { name: "New card" });
const noNewCard = () => expect(screen.queryByRole("form", { name: "New card" })).toBeNull();

async function save(amount = "5") {
  await userEvent.type(screen.getByLabelText("Amount"), amount);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
}

describe("Paid with defaults for a new expense with no usual card", () => {
  it("starts on the only card, still offers Not set, and sends the card since the server won't pick it", async () => {
    const calls = setup([spending, cash, citi]);
    await waitFor(() => expect(select().value).toBe("w-citi"));
    expect(optionTexts()).toEqual(["Citi PremierMiles ·· 4321", "Spending", "Cash", "Not set", "+ Add a card…"]);
    await save();
    await waitFor(() => expect(written(calls)).toMatchObject({ paid_with_wallet_id: "w-citi" }));
  });

  it("sends null when Not set is picked over the only card", async () => {
    const calls = setup([spending, cash, citi]);
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.selectOptions(select(), "Not set");
    await save();
    await waitFor(() => expect(written(calls)).toMatchObject({ paid_with_wallet_id: null }));
  });

  it("does not guess between several cards: Which card? stays selected and no card is sent", async () => {
    const calls = setup([spending, citi, dbs, cash]);
    await waitFor(() => expect(optionTexts()).toContain("DBS Altitude ·· 8765"));
    expect(select().value).toBe("");
    expect(select().selectedOptions[0].text).toBe("Which card?");
    expect(optionTexts()).not.toContain("Not set");
    await save();
    await waitFor(() => expect(written(calls)).toBeDefined());
    expect(written(calls)).not.toHaveProperty("paid_with_wallet_id");
  });

  it("with no cards at all (cash is not a card), asks for a credit card to add later and sends none", async () => {
    const calls = setup([spending, cash]);
    await waitFor(() => expect(optionTexts()).toContain("Cash"));
    expect(select().value).toBe("");
    expect(select().selectedOptions[0].text).toBe("Credit card (add details later)");
    await save();
    await waitFor(() => expect(written(calls)).toBeDefined());
    expect(written(calls)).not.toHaveProperty("paid_with_wallet_id");
  });

  it("with a usual card, starts on it and sends nothing so the server applies it", async () => {
    const calls = setup([spending, { ...citi, usual: true }, dbs, cash]);
    await waitFor(() => expect(select().value).toBe("w-citi"));
    expect(select().selectedOptions[0].text).toBe("Citi PremierMiles ·· 4321");
    await save();
    await waitFor(() => expect(written(calls)).toBeDefined());
    expect(written(calls)).not.toHaveProperty("paid_with_wallet_id");
  });

  it("keeps showing Not set for an old entry, with the only card or several", async () => {
    setup([spending, citi, dbs, cash], saved);
    await waitFor(() => expect(optionTexts()).toContain("DBS Altitude ·· 8765"));
    expect(select().selectedOptions[0].text).toBe("Not set");
  });
});

describe("Add a card from the entry sheet", () => {
  it("adds a card, selects it, keeps what was typed, and saves the expense with it", async () => {
    const calls = setup([spending, { ...dbs, usual: true }, cash]);
    await waitFor(() => expect(select().value).toBe("w-dbs"));
    await userEvent.type(screen.getByLabelText("Amount"), "8.40");
    await userEvent.type(screen.getByLabelText("Paid to"), "Kopi");

    await userEvent.selectOptions(select(), "+ Add a card…");
    expect(select().value).toBe("w-dbs");
    const form = within(newCard());
    await userEvent.type(form.getByLabelText("Bank"), "Citi");
    await userEvent.type(form.getByLabelText("Card"), "PremierMiles");
    await userEvent.selectOptions(form.getByLabelText("Network"), "Visa");
    await userEvent.type(form.getByLabelText("Last 4 digits"), "0000 0000 0000 4321");
    expect(form.getByLabelText("Last 4 digits")).toHaveValue("4321");
    expect(form.getByText("Only the last 4 digits are kept.")).toBeTruthy();
    await userEvent.click(form.getByLabelText("Make this my usual card"));
    await userEvent.click(form.getByRole("button", { name: "Add card" }));

    await waitFor(noNewCard);
    expect(calls.find((c) => c.method === "POST" && c.path === "/wallets")?.body).toEqual({
      name: "Citi PremierMiles",
      kind: "card",
      match_words: [],
      issuer: "Citi",
      product: "PremierMiles",
      network: "visa",
      last4: "4321",
    });
    expect(calls.find((c) => c.path === "/wallets/usual-card")?.body).toEqual({ wallet_id: "w-new" });
    await waitFor(() => expect(select().value).toBe("w-new"));
    expect(screen.getByLabelText("Amount")).toHaveValue("8.40");
    expect(screen.getByLabelText("Paid to")).toHaveValue("Kopi");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(written(calls)).toMatchObject({ paid_with_wallet_id: "w-new", counterparty: "Kopi" }));
  });

  it("names a card with nothing said just Card, and leaves the usual card alone unless ticked", async () => {
    const calls = setup([spending, cash]);
    await waitFor(() => expect(optionTexts()).toContain("Cash"));
    await userEvent.selectOptions(select(), "+ Add a card…");
    await userEvent.click(within(newCard()).getByRole("button", { name: "Add card" }));
    await waitFor(noNewCard);
    expect(calls.find((c) => c.method === "POST" && c.path === "/wallets")?.body).toMatchObject({ name: "Card", kind: "card" });
    expect(calls.some((c) => c.path === "/wallets/usual-card")).toBe(false);
    await waitFor(() => expect(select().value).toBe("w-new"));
  });

  it("Cancel closes the form, returns the select to what it was, and keeps what was typed", async () => {
    const calls = setup([spending, citi, dbs, cash]);
    await waitFor(() => expect(optionTexts()).toContain("DBS Altitude ·· 8765"));
    await userEvent.type(screen.getByLabelText("Amount"), "8.40");
    await userEvent.selectOptions(select(), "w-dbs");
    await userEvent.selectOptions(select(), "+ Add a card…");
    await userEvent.type(within(newCard()).getByLabelText("Bank"), "Citi");
    await userEvent.click(within(newCard()).getByRole("button", { name: "Cancel new card" }));
    noNewCard();
    expect(select().value).toBe("w-dbs");
    expect(screen.getByLabelText("Amount")).toHaveValue("8.40");
    expect(calls.some((c) => c.method === "POST" && c.path === "/wallets")).toBe(false);
  });

  it("Cancel returns an untouched select to Which card?", async () => {
    setup([spending, citi, dbs, cash]);
    await waitFor(() => expect(optionTexts()).toContain("DBS Altitude ·· 8765"));
    await userEvent.selectOptions(select(), "+ Add a card…");
    await userEvent.click(within(newCard()).getByRole("button", { name: "Cancel new card" }));
    noNewCard();
    expect(select().selectedOptions[0].text).toBe("Which card?");
  });

  it("shows an error in the form and keeps it open", async () => {
    setup([spending, { ...citi, usual: true }, cash], undefined, {
      "POST /wallets": () => new Response(JSON.stringify({ detail: "a wallet with that name already exists" }), { status: 409 }),
    });
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.selectOptions(select(), "+ Add a card…");
    await userEvent.click(within(newCard()).getByRole("button", { name: "Add card" }));
    expect(await within(newCard()).findByRole("alert")).toHaveTextContent("a wallet with that name already exists");
    expect(select().value).toBe("w-citi");
  });

  it("does not save the entry while the form is open; Enter in a box adds the card, not the entry", async () => {
    const calls = setup([spending, { ...citi, usual: true }, cash]);
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.type(screen.getByLabelText("Amount"), "5");
    await userEvent.selectOptions(select(), "+ Add a card…");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(within(newCard()).getByLabelText("Bank"), "Citi{Enter}");
    await waitFor(noNewCard);
    expect(calls.some((c) => c.method === "POST" && c.path === "/transactions")).toBe(false);
  });

  it("Escape closes only the form", async () => {
    const calls = setup([spending, { ...citi, usual: true }, cash]);
    await waitFor(() => expect(select().value).toBe("w-citi"));
    await userEvent.selectOptions(select(), "+ Add a card…");
    await userEvent.keyboard("{Escape}");
    noNewCard();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });
});
