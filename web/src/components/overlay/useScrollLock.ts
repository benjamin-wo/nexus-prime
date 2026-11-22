import { useEffect } from "react";

/** The class on <html> while any overlay is open; overlay.css holds the page still under it. */
export const LOCK_CLASS = "overlay-open";

let open = 0;

/** Locks the page's scroll while `active`. Counted: with two overlays open the lock stays until both have closed. */
export function useScrollLock(active = true): void {
  useEffect(() => {
    if (!active) return;
    open += 1;
    document.documentElement.classList.add(LOCK_CLASS);
    return () => {
      open -= 1;
      if (open <= 0) {
        open = 0;
        document.documentElement.classList.remove(LOCK_CLASS);
      }
    };
  }, [active]);
}
