import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App, savedMessage } from "./App";

const member = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };
const kopi = {
  id: "t9",
  direction: "out",
  amount: { amount: "5.50", currency: "SGD" },
  occurred_at: "2026-10-12T04:00:00Z",
  counterparty: "Kopi Stall",
  category_id: null,
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Signed in as a member with one expense in the ledger; records every write. */
function signedIn(patch?: () => Response) {
  const writes: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    const method = init?.method ?? "GET";
    if (method !== "GET") writes.push(`${method} ${path}`);
    if (path === "/me") return json(member);
    if (path === "/transactions" && method === "GET") return json({ items: [kopi], total: 1 });
    if (path === "/transactions" && method === "POST") return json(kopi, 201);
    if (path === "/transactions/t9" && method === "PATCH") return patch ? patch() : json(kopi);
    if (path === "/transactions/t9" && method === "DELETE") return json({ ...kopi, deleted: true });
    return json([]);
  });
  return writes;
}

function open() {
  window.history.pushState({}, "", "/accounting/ledger");
  render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
}

beforeEach(() => localStorage.clear());
afterEach(() => window.history.pushState({}, "", "/"));

describe("saving an entry", () => {
  it("says what was logged with Undo, and Undo deletes it", async () => {
    const writes = signedIn();
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Add transaction" }));
    await userEvent.type(screen.getByLabelText("Amount"), "5.50");
    await userEvent.type(screen.getByLabelText("Paid to"), "Kopi Stall");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Logged SGD 5.50 · Kopi Stall.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Removed Kopi Stall.")).toBeInTheDocument();
    expect(writes.filter((w) => w.includes("/transactions"))).toEqual(["POST /transactions", "DELETE /transactions/t9"]);
  });

  it("says Saved for a change, with no Undo", async () => {
    signedIn();
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Kopi Stall" }));
    await screen.findByRole("dialog", { name: "Edit transaction" });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("keeps the rule offer in the same line, beside Undo, when a category change suggests one", async () => {
    const suggestion = { question: "Always file “kopi stall” under Dining Out?", pattern: "kopi stall", category_id: "c1", replaces_category_id: null };
    signedIn(() => json({ ...kopi, rule_suggestion: suggestion }));
    open();
    await userEvent.click(await screen.findByRole("button", { name: "Kopi Stall" }));
    await screen.findByRole("dialog", { name: "Edit transaction" });
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    const toast = await screen.findByText("Saved. Always file “kopi stall” under Dining Out?");
    expect(toast).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save rule" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit transaction" })).toBeNull());
  });
});

describe("the saved message", () => {
  const tx = { ...kopi, direction: "out" as const } as never;
  // The money is formatted with a no-break space after the currency.
  const plain = (text: string) => text.replace(/\u00a0/g, " ");
  it("names the amount and where, and leaves out a missing merchant", () => {
    expect(plain(savedMessage(tx, true))).toBe("Logged SGD 5.50 · Kopi Stall.");
    expect(plain(savedMessage({ ...(tx as object), counterparty: null } as never, true))).toBe("Logged SGD 5.50.");
    expect(savedMessage(tx, false)).toBe("Saved.");
  });
});
