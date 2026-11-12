import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, Page, Transaction } from "../api";
import { discard, enqueue, loadOutbox } from "../outbox";
import { mockApi, renderWithProviders } from "../testing";
import { Ledger } from "./Ledger";

const me: Me = {
  user: { telegram_user_id: 5, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
};
const USER = "5";
const KEY = "0b1d6c3e-5a7f-4e21-9d84-3c2f1a6b7e90";
const OTHER = "9a8b7c6d-1111-4222-8333-444455556666";

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

const saved = (over: Record<string, unknown> = {}) => ({
  direction: "out",
  amount: "4.80",
  currency: "SGD",
  date: "2026-11-12",
  counterparty: "Kopi Corner",
  ...over,
});

function setup(items: Transaction[] = [tx({})], route = "/") {
  mockApi({
    "GET /transactions": () => ({ items, total: items.length }) satisfies Page,
    "GET /categories": () => [],
    "GET /category-rules": () => [],
    "GET /wallets": () => [],
    "POST /transactions": () => tx({ id: "t2" }),
  });
  renderWithProviders(<Ledger me={me} onAdd={vi.fn()} onEdit={vi.fn()} />, route);
}

beforeEach(() => localStorage.clear());

/** What the outbox stores for an entry the server refused. */
function markFailedForTest(user: string, key: string, message: string) {
  const name = `nexus:outbox:${user}`;
  const list = JSON.parse(localStorage.getItem(name) ?? "[]") as { key: string }[];
  localStorage.setItem(name, JSON.stringify(list.map((e) => (e.key === key ? { ...e, failed: message } : e))));
}

describe("expenses saved on the phone, in the Ledger", () => {
  it("shows each at the top with a Will sync chip, above the recorded ones", async () => {
    enqueue(USER, { key: KEY, body: saved() });
    setup();
    await screen.findByText("Corner Cafe");
    const waiting = screen.getByRole("list", { name: "Saved on this phone, waiting to sync" });
    const row = within(waiting).getByRole("listitem");
    expect(row).toHaveTextContent("Kopi Corner");
    expect(row).toHaveTextContent("Will sync");
    expect(row).toHaveTextContent("−SGD 4.80");
    expect(row).toHaveTextContent("Saved on this phone");
    expect(within(row).queryByRole("button", { name: "Try again" })).toBeNull();
    // Above the table in the page.
    expect(waiting.compareDocumentPosition(screen.getByRole("table")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows nothing when nothing is waiting, and nothing from another person's phone list", async () => {
    enqueue("6", { key: KEY, body: saved() });
    setup();
    await screen.findByText("Corner Cafe");
    expect(screen.queryByText("Will sync")).toBeNull();
    expect(screen.queryByRole("list", { name: /waiting to sync/ })).toBeNull();
  });

  it("shows them on an empty ledger instead of the empty-state line", async () => {
    enqueue(USER, { key: KEY, body: saved() });
    setup([]);
    expect(await screen.findByText("Kopi Corner")).toBeInTheDocument();
    expect(screen.queryByText(/No transactions yet/)).toBeNull();
  });

  it("shows money in too, and leaves them out of a narrowing filter", async () => {
    enqueue(USER, { key: KEY, body: saved({ direction: "in", counterparty: "Aunt May", amount: "20" }) });
    setup([tx({})], "/?view=out");
    await screen.findByText("Corner Cafe");
    expect(screen.queryByText("Aunt May")).toBeNull();
  });

  it("shows money in with a plus", async () => {
    enqueue(USER, { key: KEY, body: saved({ direction: "in", counterparty: "Aunt May", amount: "20" }) });
    setup();
    expect(await screen.findByText("Aunt May")).toBeInTheDocument();
    expect(screen.getByText("+SGD 20.00")).toBeInTheDocument();
  });

  it("goes when it is sent", async () => {
    enqueue(USER, { key: KEY, body: saved() });
    setup();
    await screen.findByText("Kopi Corner");
    discard(USER, KEY);
    await waitFor(() => expect(screen.queryByText("Kopi Corner")).toBeNull());
  });

  it("lets the person discard one", async () => {
    enqueue(USER, { key: KEY, body: saved() });
    enqueue(USER, { key: OTHER, body: saved({ counterparty: "Mala Stall" }) });
    setup();
    await screen.findByText("Mala Stall");
    const row = screen.getByText("Kopi Corner").closest("li") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Discard" }));
    await waitFor(() => expect(screen.queryByText("Kopi Corner")).toBeNull());
    expect(screen.getByText("Mala Stall")).toBeInTheDocument();
    expect(loadOutbox(USER).map((e) => e.key)).toEqual([OTHER]);
  });

  it("shows the server's reason on a refused one, with Try again and Discard", async () => {
    enqueue(USER, { key: KEY, body: saved() });
    markFailedForTest(USER, KEY, "that category was deleted");
    setup();
    await screen.findByText("Corner Cafe");
    const row = screen.getByText("Kopi Corner").closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Couldn't sync");
    expect(row).toHaveTextContent("that category was deleted");
    expect(within(row).getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Discard" })).toBeInTheDocument();
  });

  it("sends a refused one again, with its key, on Try again", async () => {
    enqueue(USER, { key: KEY, body: saved() });
    markFailedForTest(USER, KEY, "that category was deleted");
    setup();
    await screen.findByText("Kopi Corner");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.queryByText("Kopi Corner")).toBeNull());
    const post = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "POST");
    expect((post?.[1]?.headers as Record<string, string>)["Idempotency-Key"]).toBe(KEY);
  });
});
