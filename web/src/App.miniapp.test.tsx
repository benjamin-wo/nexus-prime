import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

// Opened inside Telegram: the launch data is there, as the Mini App's start-up would have read it.
vi.mock("./telegram", async (original) => ({
  ...(await original<typeof import("./telegram")>()),
  initData: "user=%7B%22id%22%3A3%7D&hash=ok",
}));

const guest = { user: { telegram_user_id: 3, role: "guest", home_currency: "SGD", timezone: "Asia/Singapore", display_name: "Gus L." }, csrf_token: "c" };

/** Signed out until the Mini App sign-in; every request is recorded as "METHOD /path" with its body. */
function signedOut(): { path: string; body: unknown }[] {
  const calls: { path: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    const method = init?.method ?? "GET";
    calls.push({ path: `${method} ${path}`, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (path === "/auth/webapp") return new Response(JSON.stringify({ ...guest, joined_trip: "t9" }), { status: 200, headers: { "Content-Type": "application/json" } });
    if (path === "/me") return new Response(JSON.stringify({ detail: "not signed in" }), { status: 401 });
    return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return calls;
}

afterEach(() => window.history.pushState({}, "", "/"));

describe("signing in from inside Telegram", () => {
  it("sends the trip invite in the address along with the launch data", async () => {
    const calls = signedOut();
    window.history.pushState({}, "", "/trip-invite/tok123");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    await waitFor(() => expect(calls.some((c) => c.path === "POST /auth/webapp")).toBe(true));
    expect(calls.find((c) => c.path === "POST /auth/webapp")?.body).toEqual({ init_data: "user=%7B%22id%22%3A3%7D&hash=ok", trip_invite: "tok123" });
  });

  it("sends only the launch data anywhere else", async () => {
    const calls = signedOut();
    window.history.pushState({}, "", "/travel");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    await waitFor(() => expect(calls.some((c) => c.path === "POST /auth/webapp")).toBe(true));
    expect(calls.find((c) => c.path === "POST /auth/webapp")?.body).toEqual({ init_data: "user=%7B%22id%22%3A3%7D&hash=ok" });
  });

  it("explains a refused trip invite in the app instead of sending them to a browser", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      if (path === "/auth/webapp") return new Response(JSON.stringify({ detail: "this trip invite is invalid, used or expired" }), { status: 403, headers: { "Content-Type": "application/json" } });
      return new Response(JSON.stringify({ detail: "not signed in" }), { status: 401 });
    });
    window.history.pushState({}, "", "/trip-invite/tok123");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    expect(await screen.findByRole("heading", { name: "You've been invited to a trip" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("That invite couldn't be used.");
    expect(screen.queryByRole("button", { name: "Open in browser" })).toBeNull();
  });
});
