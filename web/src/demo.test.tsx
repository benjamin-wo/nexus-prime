import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import type { Me } from "./api";
import { DemoBanner } from "./components/DemoBanner";
import { ChatDrawer } from "./components/ChatDrawer";
import { Shell } from "./components/Shell";
import { messagesLeft, timeLeft } from "./demo";
import { mockApi, renderWithProviders } from "./testing";

const NOW = Date.parse("2026-11-02T10:00:00Z");
const after = (ms: number) => new Date(NOW + ms).toISOString();
const HOUR = 3_600_000;
const MINUTE = 60_000;

describe("the demo's time left", () => {
  it("counts whole hours down, never rounding up", () => {
    expect(timeLeft(after(23 * HOUR + 30 * MINUTE), NOW)).toBe("23 h");
    expect(timeLeft(after(24 * HOUR), NOW)).toBe("24 h");
    expect(timeLeft(after(HOUR), NOW)).toBe("1 h");
  });

  it("switches to minutes in the last hour", () => {
    expect(timeLeft(after(59 * MINUTE), NOW)).toBe("59 min");
    expect(timeLeft(after(42 * MINUTE), NOW)).toBe("42 min");
    expect(timeLeft(after(20_000), NOW)).toBe("1 min");
  });

  it("says a moment once it is up or unreadable", () => {
    expect(timeLeft(after(0), NOW)).toBe("a moment");
    expect(timeLeft(after(-HOUR), NOW)).toBe("a moment");
    expect(timeLeft("not a date", NOW)).toBe("a moment");
  });

  it("words the messages left", () => {
    expect(messagesLeft(5)).toBe("5 messages left");
    expect(messagesLeft(1)).toBe("1 message left");
    expect(messagesLeft(0)).toBe("0 messages left");
  });
});

describe("the demo banner", () => {
  beforeEach(() => sessionStorage.clear());

  it("says what the demo is and how long it has left", () => {
    render(<DemoBanner expiresAt={new Date(Date.now() + 23.5 * HOUR).toISOString()} onSignIn={() => {}} />);
    const bar = screen.getByRole("region", { name: "Demo account" });
    expect(bar).toHaveTextContent("Demo · made-up data · resets in 23 h · Sign in with Telegram to use your own");
  });

  it("signs the demo out from the Telegram link", async () => {
    const out = vi.fn();
    render(<DemoBanner expiresAt={new Date(Date.now() + HOUR).toISOString()} onSignIn={out} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign in with Telegram" }));
    expect(out).toHaveBeenCalledTimes(1);
  });

  it("can be dismissed, and stays dismissed for the session", async () => {
    const expires = new Date(Date.now() + HOUR).toISOString();
    const first = render(<DemoBanner expiresAt={expires} onSignIn={() => {}} />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Dismiss demo notice" }));
    expect(screen.queryByRole("region", { name: "Demo account" })).toBeNull();
    first.unmount();
    render(<DemoBanner expiresAt={expires} onSignIn={() => {}} />);
    expect(screen.queryByRole("region", { name: "Demo account" })).toBeNull();
  });
});

const member = (demo?: Me["demo"]): Me => ({
  user: { telegram_user_id: 1, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" },
  csrf_token: "c",
  demo,
});

describe("the shell in a demo", () => {
  beforeEach(() => sessionStorage.clear());

  const shell = (me: Me) =>
    render(
      <MemoryRouter>
        <Shell me={me} onOpenChat={() => {}} onLogout={() => {}}>
          <p>Page</p>
        </Shell>
      </MemoryRouter>,
    );

  it("shows the banner only when me.demo is set", () => {
    shell(member({ expires_at: new Date(Date.now() + 5 * HOUR).toISOString(), messages_left: 5 }));
    expect(screen.getByRole("region", { name: "Demo account" })).toHaveTextContent("resets in 5 h");
  });

  it("shows no banner for a real user", () => {
    shell(member(null));
    expect(screen.queryByRole("region", { name: "Demo account" })).toBeNull();
  });
});

describe("the chat drawer", () => {
  it("offers suggestions when the chat is empty, and tapping one sends it", async () => {
    const calls = mockApi({
      "GET /chat/history": () => ({ lines: [], more: false, pending: null }),
      "POST /chat": () => [{ text: "Dining is at 60%.", buttons: [] }],
    });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const group = await screen.findByRole("group", { name: "Suggestions" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "How's my dining budget?",
      "Plan Saturday in Kyoto",
      "I spent 12.50 on lunch at Kopi Corner",
      "What moved in my portfolio today?",
    ]);
    await userEvent.setup().click(within(group).getByRole("button", { name: "Plan Saturday in Kyoto" }));
    expect(await screen.findByText("Dining is at 60%.")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/chat")?.body).toEqual({ message: "Plan Saturday in Kyoto" });
    expect(screen.queryByRole("group", { name: "Suggestions" })).toBeNull();
  });

  it("has no suggestions once there is a conversation", async () => {
    mockApi({
      "GET /chat/history": () => ({
        lines: [{ id: 1, role: "user", text: "hi", channel: "web", at: "2026-09-28T02:00:00Z" }],
        more: false,
        pending: null,
      }),
    });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    expect(await screen.findByText("hi")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Suggestions" })).toBeNull();
  });

  it("says how many messages are left in a demo, and nothing otherwise", async () => {
    mockApi({ "GET /chat/history": () => ({ lines: [], more: false, pending: null }) });
    renderWithProviders(
      <ChatDrawer demo={{ expires_at: after(HOUR), messages_left: 3 }} onClose={() => {}} onChanged={() => {}} />,
    );
    expect(await screen.findByText("3 messages left")).toBeInTheDocument();
  });

  it("shows no count to a real user", async () => {
    mockApi({ "GET /chat/history": () => ({ lines: [], more: false, pending: null }) });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    await screen.findByRole("group", { name: "Suggestions" });
    expect(screen.queryByText(/messages? left/)).toBeNull();
  });
});

describe("the /demo page", () => {
  const signedOut = (demo: (() => Response) | Record<string, unknown>) => {
    let started = false;
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      const method = init?.method ?? "GET";
      calls.push(`${method} ${path}`);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
      if (path === "/demo") {
        if (typeof demo === "function") {
          const answer = demo();
          if (answer.ok) started = true;
          return answer;
        }
        started = true;
        return json(demo);
      }
      if (path === "/me") {
        if (!started) return json({ detail: "not signed in" }, 401);
        return json({ ...member({ expires_at: after(23 * HOUR), messages_left: 5 }) });
      }
      if (path === "/config") return json({ bot_username: "nexus_test_bot" });
      return json({ detail: "not mocked" }, 404);
    });
    return calls;
  };
  const open = (address = "/demo") => {
    window.history.pushState({}, "", address);
    return render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  };
  afterEach(() => window.history.pushState({}, "", "/"));

  it("sets up a demo, then goes to Home with the banner", async () => {
    const calls = signedOut({ expires_at: after(23 * HOUR) });
    open();
    expect(await screen.findByRole("region", { name: "Demo account" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
    expect(calls.filter((c) => c === "POST /demo")).toHaveLength(1);
  });

  it("says the demo is resting on a 403 and offers Telegram sign-in", async () => {
    signedOut(() => new Response(JSON.stringify({ detail: "demo_off" }), { status: 403, headers: { "Content-Type": "application/json" } }));
    open();
    expect(await screen.findByRole("heading", { name: "The demo is resting right now" })).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector(".tg-login script")).not.toBeNull());
    expect(window.location.pathname).toBe("/demo");
  });

  it("says there were too many demos from this network on a 429", async () => {
    signedOut(() => new Response(JSON.stringify({ detail: "slow down" }), { status: 429, headers: { "Content-Type": "application/json" } }));
    open();
    expect(await screen.findByText("Too many demos from this network — try again in a bit.")).toBeInTheDocument();
  });

  it("offers a retry after a network error", async () => {
    let tries = 0;
    const calls = signedOut(() => {
      tries += 1;
      if (tries === 1) throw new TypeError("Failed to fetch");
      return new Response(JSON.stringify({ expires_at: after(23 * HOUR) }), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    open();
    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(calls.filter((c) => c === "POST /demo")).toHaveLength(1);
    await userEvent.setup().click(retry);
    expect(await screen.findByRole("region", { name: "Demo account" })).toBeInTheDocument();
    expect(calls.filter((c) => c === "POST /demo")).toHaveLength(2);
  });

  it("does not start a demo for someone already signed in", async () => {
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      calls.push(`${init?.method ?? "GET"} ${path}`);
      return new Response(JSON.stringify(path === "/me" ? member(null) : { detail: "not mocked" }), {
        status: path === "/me" ? 200 : 404,
        headers: { "Content-Type": "application/json" },
      });
    });
    open();
    expect((await screen.findAllByRole("link", { name: "Settings" })).length).toBeGreaterThan(0);
    expect(window.location.pathname).toBe("/");
    expect(calls).not.toContain("POST /demo");
    expect(screen.queryByRole("region", { name: "Demo account" })).toBeNull();
  });
});

describe("the sign-in page", () => {
  const signedOut = () =>
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
      const body = path === "/config" ? { bot_username: "nexus_test_bot" } : { detail: "not signed in" };
      return new Response(JSON.stringify(body), { status: path === "/config" ? 200 : 401, headers: { "Content-Type": "application/json" } });
    });
  afterEach(() => window.history.pushState({}, "", "/"));

  it("leads with the demo, with Telegram sign-in under it", async () => {
    signedOut();
    window.history.pushState({}, "", "/login");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    const demo = await screen.findByRole("link", { name: "Try the live demo" });
    expect(demo).toHaveAttribute("href", "/demo");
    expect(screen.getByText(/personal finance and travel assistant/)).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector(".tg-login script")).not.toBeNull());
  });

  it("keeps an invite link as it was", async () => {
    signedOut();
    window.history.pushState({}, "", "/invite/tok1");
    render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
    expect(await screen.findByText("You've been invited. Sign in with Telegram to accept.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Try the live demo" })).toBeNull();
  });
});
