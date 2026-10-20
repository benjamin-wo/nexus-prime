import type { PriceKind } from "./api";

/** How often a page showing live prices asks again while the US market is open. */
export const LIVE_REFRESH_MS = 60_000;

/** The `refetchInterval` rule for a page that shows prices: every minute while the price it was
 * last given is live and the page is in view, else not at all (a close doesn't change, and a
 * hidden page can wait for focus, which refetches). Pass the kind from the last response. */
export function livePolling(
  kind: PriceKind | null | undefined,
  visibility: DocumentVisibilityState = document.visibilityState,
): number | false {
  return kind === "live" && visibility === "visible" ? LIVE_REFRESH_MS : false;
}
