import type { QueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore } from "react";

import { api, ApiError, type Me, type Transaction } from "./api";
import { onAppReturn } from "./refreshOnReturn";

/**
 * The outbox: expenses logged by hand with no connection, kept on the phone until they can be sent.
 *
 * Only a new money-in or money-out entry from the entry sheet is kept this way. Edits, deletes, transfers and
 * chat need the server (or the model) and are not queued. Each entry has a key made up when the sheet opened,
 * sent as `Idempotency-Key` on every attempt, so an entry whose reply was lost is recorded once however often it
 * is sent (see POST /transactions). Entries live in `localStorage`, one list per signed-in user. There is no
 * service worker: the app has to be open already.
 */

export type OutboxEntry = {
  /** The idempotency key. */
  key: string;
  /** The body of POST /transactions, as the sheet built it. */
  body: Record<string, unknown>;
  /** When it was saved on this phone (ISO). */
  savedAt: string;
  /** The server's reason, once it has refused the entry; it is then no longer sent until "Try again". */
  failed?: string;
};

const PREFIX = "nexus:outbox:";
/** While something waits, try again this often (the `online` event doesn't come when only the server is down). */
export const RETRY_MS = 60_000;
/** What a successful send makes stale. */
const STALE = ["transactions", "summary", "home", "budgets"];

/** Whose list: the signed-in person. */
export const outboxUser = (me: Me): string => String(me.user.telegram_user_id);

// --- storage ---------------------------------------------------------------------------------

const storageKey = (user: string) => PREFIX + user;

function read(user: string): string | null {
  try {
    return localStorage.getItem(storageKey(user));
  } catch {
    return null; // Storage can be blocked or missing: the outbox is just empty.
  }
}

function parse(raw: string | null): OutboxEntry[] {
  if (!raw) return [];
  try {
    const data: unknown = JSON.parse(raw);
    if (!Array.isArray(data)) return [];
    return data.filter(
      (e): e is OutboxEntry =>
        typeof e === "object" &&
        e !== null &&
        typeof e.key === "string" &&
        typeof e.body === "object" &&
        e.body !== null &&
        typeof e.savedAt === "string" &&
        (e.failed === undefined || typeof e.failed === "string"),
    );
  } catch {
    return [];
  }
}

const cache = new Map<string, { raw: string | null; entries: OutboxEntry[] }>();
const EMPTY: OutboxEntry[] = [];

/** What is waiting for this user, oldest first. The same array comes back until the stored list changes. */
export function loadOutbox(user: string): readonly OutboxEntry[] {
  const raw = read(user);
  const hit = cache.get(user);
  if (hit && hit.raw === raw) return hit.entries;
  const entries = raw ? parse(raw) : EMPTY;
  cache.set(user, { raw, entries });
  return entries;
}

const listeners = new Set<() => void>();
const changed = () => listeners.forEach((listener) => listener());

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // Another tab of the app changed the list.
  const onStorage = (event: StorageEvent) => event.key?.startsWith(PREFIX) && listener();
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** Store the list; false when this phone won't keep it (storage blocked or full). */
function save(user: string, entries: readonly OutboxEntry[]): boolean {
  try {
    if (entries.length === 0) localStorage.removeItem(storageKey(user));
    else localStorage.setItem(storageKey(user), JSON.stringify(entries));
  } catch {
    return false;
  }
  changed();
  return true;
}

function update(user: string, change: (entries: readonly OutboxEntry[]) => readonly OutboxEntry[]): boolean {
  return save(user, change(loadOutbox(user)));
}

/** Keep a new entry for later. False if it could not be kept; nothing is then queued. An entry with a key
 * already in the list replaces that one. */
export function enqueue(user: string, entry: { key: string; body: Record<string, unknown> }): boolean {
  const next: OutboxEntry = { key: entry.key, body: entry.body, savedAt: new Date().toISOString() };
  return update(user, (all) => [...all.filter((e) => e.key !== entry.key), next]);
}

/** Drop an entry (sent, or thrown away by the person). */
export function discard(user: string, key: string): void {
  update(user, (all) => all.filter((e) => e.key !== key));
}

function mark(user: string, key: string, failed: string | undefined): void {
  update(user, (all) =>
    all.map((e) => {
      if (e.key !== key) return e;
      const { failed: _old, ...rest } = e;
      return failed === undefined ? rest : { ...rest, failed };
    }),
  );
}

/** An entry that is still to be sent (not one the server refused). */
export const isWaiting = (entry: OutboxEntry): boolean => entry.failed === undefined;

// --- sending ---------------------------------------------------------------------------------

const running = new Map<string, Promise<number>>();

/** A refusal that would be refused again as it stands: the entry is marked failed with the server's words. Anything
 * else (no connection, a server error, a session that ended, "too busy") leaves it waiting for the next try. */
function isRefusal(e: unknown): e is ApiError {
  return (
    e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 401 && e.status !== 408 && e.status !== 429
  );
}

async function sendAll(user: string): Promise<number> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return 0;
  let sent = 0;
  const tried = new Set<string>();
  for (;;) {
    // The list is read afresh each time: it may have been added to, or an entry thrown away, meanwhile.
    const next = loadOutbox(user).find((e) => isWaiting(e) && !tried.has(e.key));
    if (!next) return sent;
    tried.add(next.key);
    try {
      await api<Transaction>("/transactions", { method: "POST", body: next.body, idempotencyKey: next.key });
      discard(user, next.key);
      sent += 1;
    } catch (e) {
      if (isRefusal(e)) mark(user, next.key, e.message);
      else return sent; // Still offline, or the server is struggling: keep the rest for the next try.
    }
  }
}

/**
 * Send what is waiting, one entry at a time, each with its own key. Never two sends of the same list at once:
 * a call while one is running gets that one's result. A sent entry is removed and the ledger, home, summary and
 * budgets are fetched again; one that couldn't reach the server stays; one the server refused stays marked
 * failed. Resolves to how many were sent.
 */
export function flushOutbox(user: string, client?: QueryClient): Promise<number> {
  const active = running.get(user);
  if (active) return active;
  const run = sendAll(user)
    .then((sent) => {
      if (sent > 0) for (const key of STALE) void client?.invalidateQueries({ queryKey: [key] });
      return sent;
    })
    .finally(() => running.delete(user));
  running.set(user, run);
  return run;
}

/** "Try again" on an entry the server refused. */
export function retryEntry(user: string, key: string, client?: QueryClient): Promise<number> {
  mark(user, key, undefined);
  return flushOutbox(user, client);
}

// --- keys ------------------------------------------------------------------------------------

/** A new random key (a version 4 UUID). `crypto.randomUUID` is missing from older WebViews and from pages not
 * served over https, so it falls back to random bytes. */
export function newKey(): string {
  const c: Crypto | undefined = globalThis.crypto;
  if (typeof c?.randomUUID === "function") return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof c?.getRandomValues === "function") c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

// --- hooks -----------------------------------------------------------------------------------

/** What is waiting for this user; renders again when it changes (here or in another tab). */
export function useOutbox(user: string): readonly OutboxEntry[] {
  return useSyncExternalStore(
    subscribe,
    () => loadOutbox(user),
    () => EMPTY,
  );
}

function subscribeOnline(listener: () => void): () => void {
  window.addEventListener("online", listener);
  window.addEventListener("offline", listener);
  return () => {
    window.removeEventListener("online", listener);
    window.removeEventListener("offline", listener);
  };
}

/** Whether the phone says it is online. (Online is only what the browser believes: a request can still fail.) */
export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine !== false,
    () => true,
  );
}

/** Sends the outbox when the app starts, when the phone comes back online, when the app is shown again, and
 * every minute while it is open. Mount it once for the signed-in user. */
export function useOutboxSync(user: string, client: QueryClient): void {
  useEffect(() => {
    const go = () => void flushOutbox(user, client);
    go();
    window.addEventListener("online", go);
    const stopReturn = onAppReturn(go);
    const timer = window.setInterval(go, RETRY_MS);
    return () => {
      window.removeEventListener("online", go);
      stopReturn();
      window.clearInterval(timer);
    };
  }, [user, client]);
}
