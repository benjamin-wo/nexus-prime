import { QueryClient } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  discard,
  enqueue,
  flushOutbox,
  isWaiting,
  loadOutbox,
  newKey,
  outboxUser,
  RETRY_MS,
  retryEntry,
  useOutboxSync,
} from "./outbox";
import { DEBOUNCE_MS, useRefreshOnReturn } from "./refreshOnReturn";
import { mockApi } from "./testing";

const USER = "42";
const KEY = "0b1d6c3e-5a7f-4e21-9d84-3c2f1a6b7e90";
const OTHER = "9a8b7c6d-1111-4222-8333-444455556666";
const body = (over: Record<string, unknown> = {}) => ({
  direction: "out",
  amount: "4.80",
  currency: "SGD",
  date: "2026-11-12",
  notes: null,
  counterparty: "Kopi Corner",
  category_id: null,
  ...over,
});

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

function reply(status: number, data: unknown = null): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

/** The Idempotency-Key header of each request made so far. */
const keysSent = () =>
  vi
    .mocked(fetch)
    .mock.calls.map(([, init]) => (init?.headers as Record<string, string> | undefined)?.["Idempotency-Key"]);

describe("keys", () => {
  it("makes a UUID, and a fresh one each time", () => {
    const a = newKey();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(newKey()).not.toBe(a);
  });

  it("still makes one where crypto.randomUUID is missing, with or without getRandomValues", () => {
    const shape = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
    vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => a.fill(255) });
    expect(newKey()).toMatch(shape);
    vi.stubGlobal("crypto", undefined);
    expect(newKey()).toMatch(shape);
    vi.unstubAllGlobals();
  });
});

describe("the stored list", () => {
  it("keeps entries with their key, body and time, oldest first, and one list per user", () => {
    expect(loadOutbox(USER)).toEqual([]);
    expect(enqueue(USER, { key: KEY, body: body() })).toBe(true);
    expect(enqueue(USER, { key: OTHER, body: body({ amount: "2" }) })).toBe(true);
    const list = loadOutbox(USER);
    expect(list.map((e) => e.key)).toEqual([KEY, OTHER]);
    expect(list[0].body).toEqual(body());
    expect(Number.isNaN(Date.parse(list[0].savedAt))).toBe(false);
    expect(loadOutbox("7")).toEqual([]);
    // The same list object until something changes, so a component can read it cheaply.
    expect(loadOutbox(USER)).toBe(list);
  });

  it("holds a key once: saving it again replaces the entry", () => {
    enqueue(USER, { key: KEY, body: body() });
    enqueue(USER, { key: KEY, body: body({ amount: "9" }) });
    expect(loadOutbox(USER)).toHaveLength(1);
    expect(loadOutbox(USER)[0].body.amount).toBe("9");
  });

  it("discards one entry and clears the storage when the last goes", () => {
    enqueue(USER, { key: KEY, body: body() });
    enqueue(USER, { key: OTHER, body: body() });
    discard(USER, KEY);
    expect(loadOutbox(USER).map((e) => e.key)).toEqual([OTHER]);
    discard(USER, OTHER);
    expect(loadOutbox(USER)).toEqual([]);
    expect(localStorage.getItem(`nexus:outbox:${USER}`)).toBeNull();
  });

  it("reads nothing, rather than failing, from damaged storage", () => {
    localStorage.setItem(`nexus:outbox:${USER}`, "{not json");
    expect(loadOutbox(USER)).toEqual([]);
    localStorage.setItem(`nexus:outbox:${USER}`, JSON.stringify({ key: KEY }));
    expect(loadOutbox(USER)).toEqual([]);
    localStorage.setItem(`nexus:outbox:${USER}`, JSON.stringify([{ key: 1 }, { key: KEY, body: {}, savedAt: "2026-11-12T00:00:00Z" }]));
    expect(loadOutbox(USER).map((e) => e.key)).toEqual([KEY]);
  });

  it("copes with storage that is unavailable: nothing is kept, and nothing throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("full", "QuotaExceededError");
    });
    expect(loadOutbox(USER)).toEqual([]);
    expect(enqueue(USER, { key: KEY, body: body() })).toBe(false);
    expect(() => discard(USER, KEY)).not.toThrow();
  });

  it("names the list by the signed-in person", () => {
    expect(outboxUser({ user: { telegram_user_id: 42 } } as never)).toBe("42");
  });
});

describe("sending", () => {
  it("sends each entry with its own key and body, in order, and removes what was recorded", async () => {
    enqueue(USER, { key: KEY, body: body() });
    enqueue(USER, { key: OTHER, body: body({ amount: "2" }) });
    const calls = mockApi({ "POST /transactions": () => ({ id: "t1" }) });
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    expect(await flushOutbox(USER, client)).toBe(2);

    expect(calls.map((c) => c.path)).toEqual(["/transactions", "/transactions"]);
    expect(calls[0].body).toEqual(body());
    expect(calls[1].body).toEqual(body({ amount: "2" }));
    expect(keysSent()).toEqual([KEY, OTHER]);
    expect(loadOutbox(USER)).toEqual([]);
    const stale = invalidate.mock.calls.map(([filters]) => (filters?.queryKey as string[])[0]);
    expect(stale).toEqual(expect.arrayContaining(["transactions", "summary", "home", "budgets"]));
  });

  it("keeps an entry that could not reach the server, and the ones behind it, without marking it failed", async () => {
    enqueue(USER, { key: KEY, body: body() });
    enqueue(USER, { key: OTHER, body: body() });
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const client = new QueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    expect(await flushOutbox(USER, client)).toBe(0);

    expect(fetch).toHaveBeenCalledTimes(1); // it stops at the first: the rest would fail the same way
    expect(loadOutbox(USER).map((e) => [e.key, e.failed])).toEqual([
      [KEY, undefined],
      [OTHER, undefined],
    ]);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("keeps an entry on a server error or a ended session, to try again later", async () => {
    enqueue(USER, { key: KEY, body: body() });
    for (const status of [500, 502, 401, 429]) {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(reply(status, { detail: "nope" }));
      await flushOutbox(USER);
      expect(loadOutbox(USER).map((e) => e.failed)).toEqual([undefined]);
    }
  });

  it("marks an entry the server refuses as failed with its words, and carries on with the next", async () => {
    enqueue(USER, { key: KEY, body: body({ amount: "0" }) });
    enqueue(USER, { key: OTHER, body: body() });
    const answers = [reply(422, { detail: "amount must be above zero" }), reply(200, { id: "t2" })];
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => answers.shift() as Response);

    expect(await flushOutbox(USER)).toBe(1);

    const left = loadOutbox(USER);
    expect(left.map((e) => e.key)).toEqual([KEY]);
    expect(left[0].failed).toBe("amount must be above zero");
    expect(isWaiting(left[0])).toBe(false);
  });

  it("does not send a failed entry again until Try again, which sends it with the same key", async () => {
    enqueue(USER, { key: KEY, body: body() });
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(reply(400, { detail: "no such category" }));
    await flushOutbox(USER);
    expect(fetch).toHaveBeenCalledTimes(1);

    // The next flush (the phone came back online, say) leaves it alone.
    vi.mocked(fetch).mockResolvedValue(reply(200, { id: "t1" }));
    expect(await flushOutbox(USER)).toBe(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(loadOutbox(USER)[0].failed).toBe("no such category");

    expect(await retryEntry(USER, KEY)).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(keysSent()).toEqual([KEY, KEY]);
    expect(loadOutbox(USER)).toEqual([]);
  });

  it("never sends the same entry twice at once", async () => {
    enqueue(USER, { key: KEY, body: body() });
    let release: (r: Response) => void = () => {};
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>((resolve) => (release = resolve)));

    const first = flushOutbox(USER);
    const second = flushOutbox(USER);
    const third = flushOutbox(USER);
    expect(second).toBe(first);
    expect(third).toBe(first);
    await act(async () => {
      release(reply(200, { id: "t1" }));
      await first;
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(await first).toBe(1);

    // Once it is done, a new flush is a new run (with nothing left to send).
    expect(await flushOutbox(USER)).toBe(0);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("picks up an entry added while it is sending", async () => {
    enqueue(USER, { key: KEY, body: body() });
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => {
      if (loadOutbox(USER).length === 1) enqueue(USER, { key: OTHER, body: body() });
      return reply(200, { id: "t" });
    });
    expect(await flushOutbox(USER)).toBe(2);
    expect(keysSent()).toEqual([KEY, OTHER]);
  });

  it("sends nothing while the browser says it is offline", async () => {
    enqueue(USER, { key: KEY, body: body() });
    const fetched = vi.spyOn(globalThis, "fetch");
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    expect(await flushOutbox(USER)).toBe(0);
    expect(fetched).not.toHaveBeenCalled();
    expect(loadOutbox(USER)).toHaveLength(1);
  });
});

function Sync({ client }: { client: QueryClient }) {
  useOutboxSync(USER, client);
  useRefreshOnReturn(client);
  return null;
}

describe("when it is sent", () => {
  it("on start, when the phone comes back online, when the app is shown again, and on a timer", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout", "Date"] });
    enqueue(USER, { key: KEY, body: body() });
    const calls = mockApi({ "POST /transactions": () => ({ id: "t" }) });
    const client = new QueryClient();
    render(<Sync client={client} />);

    // On start.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(loadOutbox(USER)).toEqual([]);

    // Back online.
    enqueue(USER, { key: OTHER, body: body() });
    await act(async () => {
      window.dispatchEvent(new Event("online"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(2);

    // The app shown again.
    enqueue(USER, { key: newKey(), body: body() });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DEBOUNCE_MS + 10);
      Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
      document.dispatchEvent(new Event("visibilitychange"));
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(3);

    // Still open a minute later with something waiting (the server was down, say).
    enqueue(USER, { key: newKey(), body: body() });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RETRY_MS);
    });
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(4);
    expect(loadOutbox(USER)).toEqual([]);
  });
});
