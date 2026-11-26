import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App, retryQuery } from "./App";
import { ApiError } from "./api";

const member = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };

/** Signed in as a member; every other request is answered with an empty list, so a page shows
 * its heading and little else. */
function signedIn() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    const body = path === "/me" ? member : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

/** Opens the app at an address and waits for the page whose heading is given. */
async function open(address: string, heading: string) {
  signedIn();
  window.history.pushState({}, "", address);
  render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  return screen.findByRole("heading", { name: heading, level: 1 });
}

afterEach(() => window.history.pushState({}, "", "/"));

describe("where pages live now", () => {
  it("sends / to Home at /app", async () => {
    // Only the address: Home itself needs more than this file's empty answers (Home.test.tsx).
    signedIn();
    window.history.pushState({}, "", "/");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    await waitFor(() => expect(window.location.pathname).toBe("/app"));
  });

  it("opens Budgets at /accounting/budgets", async () => {
    await open("/accounting/budgets", "Budgets");
    expect(window.location.pathname).toBe("/accounting/budgets");
    const tabs = screen.getByRole("navigation", { name: "Money pages" });
    expect(within(tabs).getByRole("link", { name: "Budgets" })).toHaveAttribute("aria-current", "page");
  });

  it.each(["/accounting/plan", "/plan", "/budgets"])("sends %s to Budgets", async (old) => {
    await open(old, "Budgets");
    expect(window.location.pathname).toBe("/accounting/budgets");
  });

  it.each(["/accounting/email", "/email"])("sends %s to Receipts by email, inside Settings", async (old) => {
    await open(old, "Receipts by email");
    expect(window.location.pathname).toBe("/settings/email");
    expect(screen.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "/settings");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("navigation", { name: "Money pages" })).toBeNull();
  });

  it.each(["/accounting/import", "/import"])("sends %s to Import a statement, inside Settings", async (old) => {
    await open(old, "Import a statement");
    expect(window.location.pathname).toBe("/settings/import");
    expect(screen.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "/settings");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });

  it("opens Notifications at /settings/notifications, inside Settings", async () => {
    await open("/settings/notifications", "Notifications");
    expect(screen.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "/settings");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("navigation", { name: "Money pages" })).toBeNull();
  });

  it.each([
    ["/settings/time-zone", "Time zone"],
    ["/settings/wallets", "Wallets"],
    ["/settings/data", "Download or delete"],
  ])("opens %s as its own page inside Settings", async (address, heading) => {
    await open(address, heading);
    expect(window.location.pathname).toBe(address);
    expect(screen.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "/settings");
    const rail = screen.getByRole("navigation", { name: "Main" });
    expect(within(rail).getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });

  it("sends an unknown Settings address back to the list", async () => {
    await open("/settings/nonsense", "Settings");
    expect(window.location.pathname).toBe("/settings");
  });

  it("keeps the other old addresses working", async () => {
    await open("/ledger", "Ledger");
    expect(window.location.pathname).toBe("/accounting/ledger");
  });

  it("opens the trade plans list at /investment/plans", async () => {
    await open("/investment/plans", "Trade plans");
    const tabs = screen.getByRole("navigation", { name: "Investment pages" });
    expect(within(tabs).getByRole("link", { name: "Trade plans" })).toHaveAttribute("aria-current", "page");
  });
});

describe("Health", () => {
  /** Signed in with Health on and agreed to; the library has one exercise. */
  function withHealth() {
    const me = { ...member, preferences: { track_cards: false, show_health: true } };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      const body =
        path === "/me" ? me : path === "/health/consent" ? { consented_at: "2026-11-20T08:00:00Z" } : path === "/health/today" ? { routine: null, in_progress: null } : path === "/health/day" ? { date: "2026-11-24", hidden: false, meals: [], totals: null, targets_kcal: null, remaining: null, safety: { suspended: false, signposts: [], new_signals: [], check_in: null } } : path === "/health/weight" ? { hidden: false, trend_words: "steady", points: [], trend_kg: null, rate_kg_per_week: null, rate_pct_per_week: null, rate_text: null, last_weigh_in: null } : path === "/health/preferences" ? { unit: "kg" } : path === "/health/volume" ? { week_start: "2026-11-23", muscles: [] } : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
  }

  it("opens each page under Health, with its four tabs, and the menu has Health when it is on", async () => {
    withHealth();
    window.history.pushState({}, "", "/health/gym/library");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    expect(await screen.findByRole("heading", { name: "Library", level: 1 })).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: "Health pages" });
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["Today", "Food", "Weight", "Gym"]);
    expect(within(tabs).getByRole("link", { name: "Gym" })).toHaveAttribute("aria-current", "page");
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Health" })).toHaveAttribute("aria-current", "page");
    expect(within(screen.getByRole("navigation", { name: "Main (mobile)" })).getByRole("link", { name: "Health" })).toBeInTheDocument();
    const gym = screen.getByRole("navigation", { name: "Gym pages" });
    expect(within(gym).getAllByRole("link").map((l) => l.textContent)).toEqual(["Workout", "Routines", "Library", "History"]);
    fireEvent.click(within(gym).getByRole("link", { name: "History" }));
    expect(await screen.findByRole("heading", { name: "History", level: 1 })).toBeInTheDocument();
    fireEvent.click(within(gym).getByRole("link", { name: "Routines" }));
    expect(await screen.findByRole("heading", { name: "Routines", level: 1 })).toBeInTheDocument();
    fireEvent.click(within(gym).getByRole("link", { name: "Workout" }));
    expect(await screen.findByRole("button", { name: "Start an empty workout" })).toBeInTheDocument();
    fireEvent.click(within(tabs).getByRole("link", { name: "Food" }));
    expect(await screen.findByRole("heading", { name: "Food", level: 1 })).toBeInTheDocument();
    fireEvent.click(within(tabs).getByRole("link", { name: "Weight" }));
    expect(await screen.findByRole("heading", { name: "Weight", level: 1 })).toBeInTheDocument();
    fireEvent.click(within(tabs).getByRole("link", { name: "Today" }));
    expect(await screen.findByRole("heading", { name: "Health", level: 1 })).toBeInTheDocument();
  });

  it("sends the old Gym addresses to their new place", async () => {
    withHealth();
    window.history.pushState({}, "", "/health/history");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    expect(await screen.findByRole("heading", { name: "History", level: 1 })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/health/gym/history");
  });

  it("opens by link before it is in the menu, on the consent screen", async () => {
    await open("/health", "Health");
    expect(screen.getByRole("button", { name: "Turn on Health" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Main" })).queryByRole("link", { name: "Health" })).toBeNull();
  });
});

describe("an address that matches no page", () => {
  it("says so, keeps the shell, and links back to Home", async () => {
    await open("/no/such/page", "This page doesn't exist");
    expect(window.location.pathname).toBe("/no/such/page");
    expect(screen.getByText("It may have moved, or the link is old.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Home" })).toHaveAttribute("href", "/app");
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
  });

  it("leaves for Home by its link", async () => {
    await open("/nope", "This page doesn't exist");
    fireEvent.click(screen.getByRole("link", { name: "Back to Home" }));
    expect(window.location.pathname).toBe("/app");
    expect(screen.queryByRole("heading", { name: "This page doesn't exist" })).toBeNull();
  });
});

describe("which failed queries are tried again", () => {
  it.each([400, 403, 404, 422])("not a %s", (status) => {
    expect(retryQuery(0, new ApiError(status, "no"))).toBe(false);
  });

  it("a dropped connection or a server error, twice", () => {
    for (const error of [new ApiError(0, "offline"), new ApiError(503, "down"), new TypeError("x")]) {
      expect(retryQuery(0, error)).toBe(true);
      expect(retryQuery(1, error)).toBe(true);
      expect(retryQuery(2, error)).toBe(false);
    }
  });
});
