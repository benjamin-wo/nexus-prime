/**
 * Light and dark. The colours live as tokens in styles.css: by default they follow the phone
 * (`prefers-color-scheme`), and `<html data-theme="light|dark">` wins over it. Inside Telegram the
 * Mini App sets that attribute from Telegram's own theme (telegram.ts), because a phone's
 * Telegram can be dark while the phone is light, or the other way round.
 */
import { useSyncExternalStore } from "react";

export type Scheme = "light" | "dark";

/** Fired on `window` when the page's scheme is set from outside the CSS (Telegram's theme). */
export const THEME_EVENT = "nexus:theme";

/** The page colours Telegram's own chrome is painted with (the same values as the tokens in styles.css):
 * the page (`--bg-shell`, also the header) and the bottom bar (Paper: the ground, no hero). */
export const CHROME: Record<Scheme, { shell: string; bar: string }> = {
  light: { shell: "#F3F1EC", bar: "#F3F1EC" },
  dark: { shell: "#161512", bar: "#161512" },
};

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** The scheme the page is showing now: an explicit `data-theme`, else the phone's setting. */
export function currentScheme(): Scheme {
  const set = document.documentElement.dataset.theme;
  if (set === "light" || set === "dark") return set;
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

/** Pin the page to a scheme (Telegram's). Returns whether the page's scheme changed. */
export function setTheme(scheme: Scheme): boolean {
  const before = currentScheme();
  document.documentElement.dataset.theme = scheme;
  if (before === scheme) return false;
  window.dispatchEvent(new Event(THEME_EVENT));
  return true;
}

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia?.(DARK_QUERY);
  window.addEventListener(THEME_EVENT, onChange);
  query?.addEventListener?.("change", onChange);
  return () => {
    window.removeEventListener(THEME_EVENT, onChange);
    query?.removeEventListener?.("change", onChange);
  };
}

/** The scheme the page is showing, kept up to date. */
export function useScheme(): Scheme {
  return useSyncExternalStore(subscribe, currentScheme, () => "light");
}
