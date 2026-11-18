import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const member = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };
const sgd = (amount: string) => ({ amount, currency: "SGD" });
const dup = (id: string) => ({
  id,
  direction: "out",
  amount: sgd("6.38"),
  occurred_at: "2026-11-09T04:00:00Z",
  counterparty: "Pinduoduo",
  category_id: "shop",
  notes: null,
  status: "confirmed",
  source: "manual",
  deleted: false,
});
const summary = {
  start: "2026-11-01",
  end: "2026-11-30",
  currency: "SGD",
  totals: [
    { direction: "out", total: sgd("12.76"), count: 2, converted: [], unconverted: [] },
    { direction: "in", total: sgd("0.00"), count: 0, converted: [], unconverted: [] },
  ],
  by_category: [{ category_id: "shop", category_name: "Shopping", total: sgd("12.76"), count: 2 }],
};

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

beforeEach(() => localStorage.clear());
afterEach(() => window.history.pushState({}, "", "/"));

describe("deleting a duplicate from Where it went", () => {
  it("opens the edit sheet from a row, and the list follows the delete and the Undo", async () => {
    const gone = new Set<string>();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      const method = init?.method ?? "GET";
      if (path === "/me") return json(member);
      if (path === "/summary") return json(summary);
      if (path === "/spending/months") return json({ currency: "SGD", months: [], last_month_to_date: sgd("0.00"), budget: null });
      if (path === "/transactions" && method === "GET") {
        const items = ["t1", "t2"].filter((id) => !gone.has(id)).map(dup);
        return json({ items, total: items.length });
      }
      const one = path.match(/^\/transactions\/(t\d)(\/restore)?$/);
      if (one && method === "DELETE") gone.add(one[1]);
      if (one && one[2]) gone.delete(one[1]);
      if (one) return json(dup(one[1]));
      return json([]);
    });
    window.history.pushState({}, "", "/accounting");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    const went = await screen.findByRole("region", { name: "Where it went" });
    await userEvent.click(await within(went).findByRole("button", { name: /Shopping: SGD.12\.76/ }, { timeout: 5000 }));
    const rows = () => within(within(went).getByRole("list", { name: "Shopping transactions" })).queryAllByRole("button");
    await waitFor(() => expect(rows()).toHaveLength(2));

    await userEvent.click(rows()[0]);
    const sheet = await screen.findByRole("dialog", { name: "Edit transaction" });
    expect(within(sheet).getByLabelText("Amount")).toHaveValue("6.38");
    await userEvent.click(within(sheet).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Deleted Pinduoduo.")).toBeInTheDocument();
    await waitFor(() => expect(rows()).toHaveLength(1));

    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(rows()).toHaveLength(2));
  });
});
