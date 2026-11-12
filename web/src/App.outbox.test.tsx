import { QueryClient } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { enqueue, loadOutbox } from "./outbox";

const USER = "2";
const KEY = "0b1d6c3e-5a7f-4e21-9d84-3c2f1a6b7e90";
const member = { user: { telegram_user_id: 2, role: "member", home_currency: "SGD", timezone: "Asia/Singapore" }, csrf_token: "c" };
const entry = { direction: "out", amount: "4.80", currency: "SGD", date: "2026-11-12", counterparty: "Kopi Corner" };

/** Signed in as a member; every other request is answered with an empty list. Records the writes. */
function signedIn(post: () => Response = () => json({ id: "t1" })) {
  const writes: { path: string; key: string | undefined }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api/, "");
    if (init?.method === "POST" && path === "/transactions") {
      writes.push({ path, key: (init.headers as Record<string, string>)["Idempotency-Key"] });
      return post();
    }
    return json(path === "/me" ? member : []);
  });
  return writes;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function open(address = "/") {
  window.history.pushState({}, "", address);
  render(<App client={new QueryClient({ defaultOptions: { queries: { retry: false } } })} />);
}

const offline = (on: boolean) => {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(!on);
  act(() => void window.dispatchEvent(new Event(on ? "offline" : "online")));
};

beforeEach(() => localStorage.clear());
afterEach(() => window.history.pushState({}, "", "/"));

describe("the app with expenses saved on the phone", () => {
  it("sends what was saved when the app starts, with the key it was saved under", async () => {
    enqueue(USER, { key: KEY, body: entry });
    const writes = signedIn();
    open();
    await waitFor(() => expect(writes).toEqual([{ path: "/transactions", key: KEY }]));
    await waitFor(() => expect(loadOutbox(USER)).toEqual([]));
  });

  it("leaves it on the phone if the server can't be reached", async () => {
    enqueue(USER, { key: KEY, body: entry });
    const writes = signedIn(() => {
      throw new TypeError("Failed to fetch");
    });
    open();
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(loadOutbox(USER)).toHaveLength(1);
    expect(loadOutbox(USER)[0].failed).toBeUndefined();
  });

  it("shows a notice on every page while offline with something waiting, and takes it away when back online", async () => {
    enqueue(USER, { key: KEY, body: entry });
    enqueue(USER, { key: "9a8b7c6d-1111-4222-8333-444455556666", body: entry });
    const writes = signedIn();
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    open("/accounting/ledger");
    expect(await screen.findByText("You're offline. 2 expenses will sync when you're back.")).toBeInTheDocument();
    expect(writes).toHaveLength(0); // nothing is tried while offline

    // The notice is the shell's, so it follows the person to other pages.
    await userEvent.click(screen.getAllByRole("link", { name: "Settings" })[0]);
    expect(screen.getByText("You're offline. 2 expenses will sync when you're back.")).toBeInTheDocument();

    offline(false);
    await waitFor(() => expect(screen.queryByText(/You're offline/)).toBeNull());
    await waitFor(() => expect(writes).toHaveLength(2));
    await waitFor(() => expect(loadOutbox(USER)).toEqual([]));
  });

  it("says one expense, not 1 expenses", async () => {
    enqueue(USER, { key: KEY, body: entry });
    signedIn();
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    open();
    expect(await screen.findByText("You're offline. 1 expense will sync when you're back.")).toBeInTheDocument();
  });

  it("has no notice when online, or offline with nothing waiting", async () => {
    signedIn();
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    open();
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByText(/You're offline/)).toBeNull();
  });

  it("keeps a new entry saved offline: closes the sheet with a short message and shows it in the Ledger", async () => {
    const writes = signedIn();
    open("/accounting/ledger");
    await userEvent.click(await screen.findByRole("button", { name: "Add transaction" }));
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    await userEvent.type(screen.getByLabelText("Amount"), "4.80");
    await userEvent.type(screen.getByLabelText("Paid to"), "Kopi Corner");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved on this phone. It will sync when you're back online.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(writes).toHaveLength(0);
    expect(loadOutbox(USER)).toHaveLength(1);
    expect(await screen.findByText("Will sync")).toBeInTheDocument();
    expect(screen.getByText("Kopi Corner")).toBeInTheDocument();

    // Back online: it is sent with the key it was saved under, and the row goes.
    const key = loadOutbox(USER)[0].key;
    offline(false);
    await waitFor(() => expect(writes).toEqual([{ path: "/transactions", key }]));
    await waitFor(() => expect(screen.queryByText("Will sync")).toBeNull());
  });
});
