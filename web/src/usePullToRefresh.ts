import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

/** idle; the finger is pulling; pulled far enough that letting go refreshes; refreshing; just refreshed. */
export type PullStatus = "idle" | "pulling" | "ready" | "refreshing" | "done";

/** How far (px, after resistance) the page must be pulled before letting go refreshes. */
export const PULL_THRESHOLD = 64;
const PULL_MAX = 96;
/** The page sits this far down while refreshing, with the spinner in the gap. */
const PULL_HOLD = 48;
/** A pull shorter than this is a stray touch, not a pull. */
const SLOP = 8;
const RESISTANCE = 0.5;
/** The spinner shows at least this long, so a fast refresh still reads as one. */
const MIN_SPIN_MS = 500;
const DONE_MS = 900;

function show(area: HTMLElement, pull: number, dragging: boolean): void {
  area.classList.toggle("ptr-active", pull > 0);
  area.classList.toggle("ptr-drag", dragging);
  area.style.setProperty("--pull", `${pull}px`);
  area.style.setProperty("--pull-ratio", String(Math.min(1, pull / PULL_THRESHOLD)));
}

/**
 * Pull-to-refresh for a scrolling area: pulling down with one finger while it is scrolled to the top drags
 * the page down, and letting go past `PULL_THRESHOLD` calls `onRefresh`. A mostly sideways move, or one that
 * starts while the area is scrolled, is left to the page. The area gets `--pull` and `--pull-ratio` (and
 * the classes `ptr-active` and `ptr-drag`) for the stylesheet to draw the drag; nothing re-renders while the
 * finger moves, only the status changes.
 *
 * Off when `onRefresh` is undefined. `allowed` is asked at the start of each touch (the Mini App's swipe
 * settings may not be known when the page first renders). Returns the status, and `refresh` to run the
 * same refresh without the gesture (the keyboard's way in).
 */
export function usePullToRefresh(
  area: RefObject<HTMLElement | null>,
  onRefresh: (() => Promise<unknown>) | undefined,
  allowed: () => boolean = () => true,
): { status: PullStatus; refresh: () => void } {
  const [status, setStatus] = useState<PullStatus>("idle");
  const busy = useRef(false);
  const timer = useRef<number | undefined>(undefined);
  const latest = useRef({ onRefresh, allowed });
  useEffect(() => {
    latest.current = { onRefresh, allowed };
  });
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const refresh = useCallback(() => {
    const run = latest.current.onRefresh;
    const el = area.current;
    if (!run || !el || busy.current) return;
    busy.current = true;
    window.clearTimeout(timer.current);
    setStatus("refreshing");
    show(el, PULL_HOLD, false);
    const spin = new Promise((resolve) => window.setTimeout(resolve, MIN_SPIN_MS));
    void Promise.all([run().catch(() => undefined), spin]).then(() => {
      busy.current = false;
      setStatus("done");
      show(el, 0, false);
      // The page slides back up; the class is dropped once it has.
      timer.current = window.setTimeout(() => {
        el.classList.remove("ptr-active");
        setStatus("idle");
      }, DONE_MS);
    });
  }, [area]);

  const enabled = onRefresh !== undefined;
  useEffect(() => {
    const el = area.current;
    if (!el || !enabled) return;
    let startX = 0;
    let startY = 0;
    let tracking = false;
    let dragging = false;
    let pull = 0;
    let shown: PullStatus = "idle";
    const say = (next: PullStatus) => {
      if (next === shown) return;
      shown = next;
      setStatus(next);
    };
    const reset = () => {
      tracking = false;
      if (dragging) {
        dragging = false;
        show(el, 0, false);
        timer.current = window.setTimeout(() => el.classList.remove("ptr-active"), 260);
      }
      pull = 0;
      say("idle");
    };

    const onStart = (e: TouchEvent) => {
      tracking = false;
      if (busy.current || e.touches.length !== 1 || el.scrollTop > 0 || !latest.current.allowed()) return;
      window.clearTimeout(timer.current);
      tracking = true;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
    };
    const onMove = (e: TouchEvent) => {
      if (!tracking) return;
      if (e.touches.length !== 1 || el.scrollTop > 0) return reset();
      const dy = e.touches[0].clientY - startY;
      const dx = e.touches[0].clientX - startX;
      if (!dragging) {
        // Up, or more sideways than down, is the page's own scroll or swipe.
        if (dy < 0 || (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > SLOP)) {
          tracking = false;
          return;
        }
        if (dy < SLOP) return;
        dragging = true;
      }
      // Pulling down at the top would otherwise bounce or reload the page: take the gesture.
      if (e.cancelable) e.preventDefault();
      pull = Math.min(PULL_MAX, Math.max(0, (dy - SLOP) * RESISTANCE));
      show(el, pull, true);
      say(pull >= PULL_THRESHOLD ? "ready" : "pulling");
    };
    const onEnd = () => {
      if (!tracking) return;
      tracking = false;
      if (dragging && pull >= PULL_THRESHOLD) {
        dragging = false;
        shown = "idle";
        refresh();
      } else reset();
    };

    el.addEventListener("touchstart", onStart, { passive: true });
    el.addEventListener("touchmove", onMove, { passive: false });
    el.addEventListener("touchend", onEnd);
    el.addEventListener("touchcancel", reset);
    return () => {
      el.removeEventListener("touchstart", onStart);
      el.removeEventListener("touchmove", onMove);
      el.removeEventListener("touchend", onEnd);
      el.removeEventListener("touchcancel", reset);
      if (!busy.current) show(el, 0, false);
    };
  }, [area, enabled, refresh]);

  return { status, refresh };
}
