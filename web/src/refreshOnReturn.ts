import type { Query, QueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { withMiniApp } from "./telegram";

/** Hidden for longer than this and everything on screen is refetched, fresh or not. */
export const LONG_PAUSE_MS = 5 * 60_000;
/** One return fires several events (Telegram's `activated`, `visibilitychange`, `focus`): the first one
 * refreshes and the rest within this window are ignored. */
export const DEBOUNCE_MS = 1000;

/** Money data is always refetched on a return, however recently it was fetched. Reference data (trip photos,
 * places, weather, merchant suggestions) keeps its own `staleTime`: it is only refetched once stale. */
const MONEY = new Set([
  "transactions",
  "summary",
  "ious",
  "budgets",
  "bills",
  "salary",
  "wallets",
  "home",
  "spending-months",
  "cashflow",
  "investments",
  "subscriptions",
  "category-explanation",
  "runs",
]);

const isMoney = (query: Query) => typeof query.queryKey[0] === "string" && MONEY.has(query.queryKey[0]);

/** Stale by the clock, not by the observer's last answer: that only updates on a timer, and a WebView that was
 * in the background may not have run it yet when the app is shown again. */
function isStale(query: Query): boolean {
  return query.observers.some((observer) => {
    const time = observer.options.staleTime;
    return query.isStaleByTime(typeof time === "function" ? time(query) : time);
  });
}

/** Refetch what is on screen (never what no page is showing). `everything` ignores `staleTime`; otherwise money
 * data and anything stale is refetched. A fetch already under way is left to finish, not restarted. */
export function refetchActive(client: QueryClient, everything: boolean): Promise<void> {
  return client.refetchQueries(
    { type: "active", predicate: (query) => everything || isMoney(query) || isStale(query) },
    { cancelRefetch: false },
  );
}

/**
 * Brings the screen up to date when the app comes back to the front. Telegram's Mini App on a phone often
 * gets no window `focus` when it is left in the background and reopened, so React Query's own refetch on focus
 * can't be relied on. Listens to:
 *
 * - Telegram's `activated` (Bot API 8.0+) and `deactivated`;
 * - `visibilitychange` (a tab or WebView shown again), and `pagehide`/`pageshow` for a page restored from the
 *   back-forward cache;
 * - `focus`, for browsers that give nothing else.
 *
 * After more than `LONG_PAUSE_MS` away everything active is refetched; after a short one, money data and
 * anything stale.
 */
export function useRefreshOnReturn(client: QueryClient): void {
  useEffect(() => {
    let hiddenAt: number | null = null;
    let lastRefresh = -Infinity;

    const away = () => {
      hiddenAt ??= Date.now();
    };
    const back = () => {
      const now = Date.now();
      if (now - lastRefresh < DEBOUNCE_MS) return;
      lastRefresh = now;
      const long = hiddenAt !== null && now - hiddenAt > LONG_PAUSE_MS;
      hiddenAt = null;
      void refetchActive(client, long);
    };

    const onVisibility = () => (document.visibilityState === "hidden" ? away() : back());
    // A focus event can arrive while the page is still hidden: that isn't a return.
    const onFocus = () => document.visibilityState !== "hidden" && back();
    const onPageShow = (event: PageTransitionEvent) => event.persisted && back();

    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", away);
    window.addEventListener("pageshow", onPageShow);
    window.addEventListener("focus", onFocus);
    let leave = () => {};
    const stop = withMiniApp((app) => {
      app.onEvent?.("deactivated", away);
      app.onEvent?.("activated", back);
      leave = () => {
        app.offEvent?.("deactivated", away);
        app.offEvent?.("activated", back);
      };
    });
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", away);
      window.removeEventListener("pageshow", onPageShow);
      window.removeEventListener("focus", onFocus);
      stop();
      leave();
    };
  }, [client]);
}
