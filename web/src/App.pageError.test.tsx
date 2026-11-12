import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// One page that always fails to render: the rest of the app has to carry on around it.
vi.mock("./pages/Ledger", () => ({
  Ledger: () => {
    throw new Error("ledger exploded");
  },
}));

const member = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    return new Response(JSON.stringify(path === "/me" ? member : []), { status: 200, headers: { "Content-Type": "application/json" } });
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

describe("a page that crashes", () => {
  it("is replaced in place, the shell stays, and another page recovers", async () => {
    window.history.pushState({}, "", "/accounting/ledger");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);

    expect(await screen.findByText("This page hit a problem.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    const rail = screen.getByRole("navigation", { name: "Main" });

    fireEvent.click(within(rail).getByRole("link", { name: "Home" }));
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
    expect(screen.queryByText("This page hit a problem.")).toBeNull();
  });
});
