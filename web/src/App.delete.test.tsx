import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const member = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };
const kopi = {
  id: "t9",
  direction: "out",
  amount: { amount: "5.00", currency: "SGD" },
  occurred_at: "2026-10-12T04:00:00Z",
  counterparty: "Kopi Corner",
  category_id: null,
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
};

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

beforeEach(() => localStorage.clear());
afterEach(() => window.history.pushState({}, "", "/"));

describe("deleting an entry from its edit sheet", () => {
  it("closes the sheet, says so with Undo, and Undo restores it", async () => {
    const writes: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      const method = init?.method ?? "GET";
      if (method !== "GET") writes.push(`${method} ${path}`);
      if (path === "/me") return json(member);
      if (path === "/transactions" && method === "GET") return json({ items: [kopi], total: 1 });
      if (path === "/transactions/t9" && method === "DELETE") return json({ ...kopi, deleted: true });
      if (path === "/transactions/t9/restore") return json(kopi);
      return json([]);
    });
    window.history.pushState({}, "", "/accounting/ledger");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    await userEvent.click(await screen.findByRole("button", { name: "Kopi Corner" }));
    const sheet = await screen.findByRole("dialog", { name: "Edit transaction" });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Edit transaction" })).toBeNull());
    expect(sheet).not.toBeInTheDocument();
    expect(await screen.findByText("Deleted Kopi Corner.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText("Restored.")).toBeInTheDocument();
    expect(writes.filter((w) => w.includes("/transactions"))).toEqual(["DELETE /transactions/t9", "POST /transactions/t9/restore"]);
  });
});
