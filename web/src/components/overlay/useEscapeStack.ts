import { useEffect, useRef } from "react";

type Entry = { current: () => void };

const stack: Entry[] = [];

const onKey = (e: KeyboardEvent) => {
  if (e.key !== "Escape") return;
  // Only the newest handler hears it. A popover that calls stopPropagation on its own React keydown stops the native
  // event before it reaches window, so it never gets here: that Escape closed the popover, not what is under it.
  stack[stack.length - 1]?.current();
};

/**
 * Escape goes to the most recently registered handler only: a nested form or popover opened inside an overlay
 * closes first, then the overlay. One window listener serves them all. Registered while mounted (and `active`).
 */
export function useEscapeStack(handler: () => void, active = true): void {
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => {
    if (!active) return;
    const entry: Entry = { current: () => latest.current() };
    if (stack.length === 0) window.addEventListener("keydown", onKey);
    stack.push(entry);
    return () => {
      const at = stack.indexOf(entry);
      if (at >= 0) stack.splice(at, 1);
      if (stack.length === 0) window.removeEventListener("keydown", onKey);
    };
  }, [active]);
}
