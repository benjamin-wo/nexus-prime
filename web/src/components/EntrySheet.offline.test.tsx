import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, Transaction } from "../api";
import { loadOutbox } from "../outbox";
import { mockApi, renderWithProviders } from "../testing";
import { EntrySheet } from "./EntrySheet";

const me: Me = {
  user: { telegram_user_id: 77, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};
const USER = "77";

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

beforeEach(() => localStorage.clear());

function setup(editing?: Transaction, post: () => unknown = () => saved) {
  const calls = mockApi({
    "GET /categories": () => [],
    "GET /wallets": () => [],
    "GET /transactions/suggestions": () => [],
    "POST /transactions": post,
    "POST /moves": () => saved,
    "PATCH /transactions/t9": () => saved,
  });
  const onSaved = vi.fn();
  const onQueued = vi.fn();
  const onClose = vi.fn();
  renderWithProviders(<EntrySheet me={me} editing={editing} onClose={onClose} onSaved={onSaved} onQueued={onQueued} />);
  return { calls, onSaved, onQueued, onClose };
}

async function fill(amount = "4.80", merchant = "Kopi Corner") {
  await userEvent.type(screen.getByLabelText("Amount"), amount);
  await userEvent.type(screen.getByLabelText("Paid to"), merchant);
}

const keysSent = () =>
  vi
    .mocked(fetch)
    .mock.calls.filter(([, init]) => init?.method === "POST")
    .map(([, init]) => (init?.headers as Record<string, string>)["Idempotency-Key"]);

const goOffline = () => vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);

describe("logging an expense with no connection", () => {
  it("sends a fresh key with a normal save", async () => {
    const { onSaved, onQueued } = setup();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [key] = keysSent();
    expect(key).toMatch(/^[0-9a-f-]{36}$/);
    expect(loadOutbox(USER)).toEqual([]);
    expect(onQueued).not.toHaveBeenCalled();
  });

  it("keeps the entry on the phone when the request never reaches the server, with the key it sent", async () => {
    const { onSaved, onQueued } = setup(undefined, () => {
      throw new TypeError("Failed to fetch");
    });
    // The mocked handler throwing makes fetch reject, as a dropped connection does.
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onQueued).toHaveBeenCalledTimes(1));
    expect(onSaved).not.toHaveBeenCalled();
    const [entry] = loadOutbox(USER);
    expect(loadOutbox(USER)).toHaveLength(1);
    expect(entry.key).toBe(keysSent()[0]);
    expect(entry.body).toMatchObject({ direction: "out", amount: "4.80", counterparty: "Kopi Corner", currency: "SGD" });
    expect(entry.failed).toBeUndefined();
  });

  it("does not even try when the phone says it is offline, and queues with a key", async () => {
    goOffline();
    const { calls, onQueued, onSaved } = setup();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onQueued).toHaveBeenCalledTimes(1));
    expect(onSaved).not.toHaveBeenCalled();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    expect(loadOutbox(USER)).toHaveLength(1);
    expect(loadOutbox(USER)[0].key).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("closes the sheet when no queued handler is given", async () => {
    goOffline();
    mockApi({ "GET /categories": () => [], "GET /wallets": () => [], "GET /transactions/suggestions": () => [] });
    const onClose = vi.fn();
    renderWithProviders(<EntrySheet me={me} onClose={onClose} onSaved={vi.fn()} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("uses the same key when the person saves again after a refusal", async () => {
    let refuse = true;
    const { onSaved } = setup(undefined, () => {
      if (!refuse) return saved;
      refuse = false;
      return new Response(JSON.stringify({ detail: "that category is gone" }), { status: 422 });
    });
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("that category is gone");
    expect(loadOutbox(USER)).toEqual([]); // a refusal is shown, never queued
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const [first, second] = keysSent();
    expect(second).toBe(first);
  });

  it("says so, and keeps the sheet open, when the phone can't keep it either", async () => {
    goOffline();
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    const { onQueued, onClose } = setup();
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/can't keep the entry for later/);
    expect(onQueued).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("does not queue a change to an entry: Save waits for a connection, with a plain note", async () => {
    goOffline();
    const { calls } = setup(saved);
    expect(await screen.findByText(/You're offline\. Changes to an entry need a connection/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    expect(loadOutbox(USER)).toEqual([]);
  });

  it("does not queue a transfer either", async () => {
    goOffline();
    setup();
    await userEvent.click(screen.getByRole("button", { name: "Transfer" }));
    expect(await screen.findByText(/You're offline\. Transfers need a connection/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("says nothing about being offline when online", async () => {
    setup(saved);
    await screen.findByText("Edit transaction");
    expect(screen.queryByText(/You're offline/)).toBeNull();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });
});
