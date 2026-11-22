import { type RefObject, useEffect, useRef } from "react";

/** Fields an overlay puts the cursor in as it opens. A file input is skipped: it is
 * a hidden control behind a button, not somewhere to type. */
export const FIELD = "input:not([type=hidden]):not([type=file]):not(:disabled), select:not(:disabled), textarea:not(:disabled)";

const TABBABLE =
  'a[href], button:not(:disabled), input:not([type=hidden]):not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

/**
 * Focus for an overlay: it goes to the first field (inside `initialFocus`, a selector for the part to look in, or for the field itself;
 * default the whole panel) unless a child already took it, else to the dialog itself (`initialFocus: "dialog"`
 * always means the dialog). With `modal`, Tab and Shift+Tab wrap inside the panel. On close focus returns to
 * what had it before, if that is still on the page.
 */
export function useFocusManagement({
  panel,
  modal,
  initialFocus,
}: {
  panel: RefObject<HTMLElement | null>;
  modal: boolean;
  initialFocus?: string;
}): void {
  // Read while rendering, before any child's effect can move the focus.
  const opener = useRef<Element | null>(typeof document === "undefined" ? null : document.activeElement);

  useEffect(() => {
    const el = panel.current;
    if (el && !el.contains(document.activeElement)) {
      const scope = initialFocus && initialFocus !== "dialog" ? el.querySelector(initialFocus) : el;
      const field = initialFocus === "dialog" ? null : scope?.matches(FIELD) ? (scope as HTMLElement) : scope?.querySelector<HTMLElement>(FIELD);
      (field ?? el).focus({ preventScroll: true });
    }
    const back = opener.current;
    return () => {
      if (back instanceof HTMLElement && back.isConnected) back.focus({ preventScroll: true });
    };
    // Once, as it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const el = panel.current;
    if (!el || !modal) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const items = [...el.querySelectorAll<HTMLElement>(TABBABLE)];
      if (items.length === 0) {
        e.preventDefault();
        el.focus({ preventScroll: true });
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const at = document.activeElement;
      if (e.shiftKey) {
        if (at === first || at === el || !el.contains(at)) {
          e.preventDefault();
          last.focus({ preventScroll: true });
        }
      } else if (at === last || !el.contains(at)) {
        e.preventDefault();
        first.focus({ preventScroll: true });
      }
    };
    el.addEventListener("keydown", onKey);
    return () => el.removeEventListener("keydown", onKey);
  }, [panel, modal]);
}
