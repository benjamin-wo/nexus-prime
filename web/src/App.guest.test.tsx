import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "./App";

/** Sign in as a guest, answer the trip routes with no trips, record every request. */
function asGuest(): string[] {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    calls.push(`${init?.method ?? "GET"} ${path}`);
    const me = { user: { telegram_user_id: 3, role: "guest", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };
    const body = path === "/me" ? me : path.startsWith("/travel/") ? [] : { detail: "guests can only open the trips they are on" };
    const status = path === "/me" || path.startsWith("/travel/") ? 200 : 403;
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

describe("the app for a guest", () => {
  it("sends every other address to Travel and never asks for anything outside the trip routes", async () => {
    const calls = asGuest();
    window.history.pushState({}, "", "/accounting/ledger");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    expect(await screen.findByRole("heading", { name: "Trips" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/travel");
    expect(screen.queryByRole("button", { name: "Ask Nexus" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
    // Home, runs, notifications, chat and the rest are the full app's, which a guest never loads.
    const outside = calls.filter((c) => !/^GET \/(me|config)$/.test(c) && !/^\w+ \/travel\//.test(c));
    expect(outside).toEqual([]);
  });
});
