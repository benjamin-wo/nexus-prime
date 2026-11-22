import { useSyncExternalStore } from "react";

/** A phone: the chat panel is a sheet that leaves 24px of the page showing. styles.css's `@media (max-width: 480px)` uses the same number. */
export const PHONE = 480;
/** Compact: a sheet is a bottom sheet. overlay.css's `@media (max-width: 720px)` uses the same number. */
export const COMPACT = 720;

export const PHONE_QUERY = `(max-width: ${PHONE}px)`;
export const COMPACT_QUERY = `(max-width: ${COMPACT}px)`;

/** Whether a media query matches now, kept current. False where `matchMedia` is missing. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const list = typeof window !== "undefined" ? window.matchMedia?.(query) : undefined;
      list?.addEventListener?.("change", notify);
      return () => list?.removeEventListener?.("change", notify);
    },
    () => typeof window !== "undefined" && window.matchMedia?.(query).matches === true,
    () => false,
  );
}
