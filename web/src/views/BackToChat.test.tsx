import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";

const member = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };
const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
const sgd = (amount: string) => ({ amount, currency: "SGD" });

// A chat with one line of Prime's that brought the budgets view; every other request is answered empty.
function signedIn() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    if (path === "/me") return json(member);
    if (path === "/config") return json({ bot_username: "b", views_enabled: true });
    if (path === "/chat/history")
      return json({
        lines: [{ id: 2, role: "nexus", text: "Here are your budgets.", channel: "web", at: "2026-11-27T01:00:01Z", views: [{ kind: "finance.budgets", params: { month: "2026-11" }, focus: true }] }],
        more: false,
        pending: null,
      });
    if (path === "/views/finance.budgets")
      return json({ view_id: "finance.budgets", kind: "finance.budgets", params: { month: "2026-11" }, caption: "Your budgets for November 2026", summary: { count: 1, over: 0, budgets: [{ name: "Dining", spent: sgd("10"), limit: sgd("100"), percent: 10 }] } });
    return json([]);
  });
}

function phone(matches: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches, addEventListener: () => {}, removeEventListener: () => {} }) as unknown as typeof window.matchMedia;
}

async function openChat() {
  window.history.pushState({}, "", "/settings/notifications");
  render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
  await screen.findByRole("heading", { name: "Notifications", level: 1 });
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
  return screen.findByRole("region", { name: "Your budgets for November 2026" });
}

afterEach(() => {
  window.history.pushState({}, "", "/");
  // @ts-expect-error jsdom has none
  delete window.matchMedia;
});

describe("Open from a card in the app", () => {
  it("on a phone closes the chat, shows the page and a Back to chat bar that reopens the chat where it was", async () => {
    phone(true);
    signedIn();
    await openChat();
    document.querySelector<HTMLElement>(".messages")!.scrollTop = 90;
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Your budgets for November 2026" }));

    await waitFor(() => expect(window.location.pathname + window.location.search).toBe("/accounting/budgets?month=2026-11"));
    expect(screen.queryByRole("dialog", { name: "Chat" })).toBeNull();
    await user.click(await screen.findByRole("button", { name: "← Back to chat" }));

    expect(await screen.findByRole("region", { name: "Your budgets for November 2026" })).toBeInTheDocument();
    await waitFor(() => expect(document.querySelector<HTMLElement>(".messages")!.scrollTop).toBe(90));
    expect(screen.queryByRole("button", { name: "← Back to chat" })).toBeNull();
    // The page stays where Open took it.
    expect(window.location.pathname).toBe("/accounting/budgets");
  });

  it("on a wide screen takes the page behind the chat, which stays open, with no Back bar", async () => {
    phone(false);
    signedIn();
    await openChat();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Open Your budgets for November 2026" }));

    await waitFor(() => expect(window.location.pathname + window.location.search).toBe("/accounting/budgets?month=2026-11"));
    expect(screen.getByRole("region", { name: "Your budgets for November 2026" })).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "← Back to chat" })).toBeNull();
  });
});
