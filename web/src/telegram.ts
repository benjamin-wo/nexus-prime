/**
 * Running as a Telegram Mini App. Telegram opens the app with signed launch data
 * in the URL fragment (#tgWebAppData=...); the server checks it and starts a
 * session, so there is no sign-in step.
 */

type WebApp = {
  ready(): void;
  expand(): void;
  setHeaderColor?(color: string): void;
  setBackgroundColor?(color: string): void;
  openLink?(url: string): void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
  }
}

const SHELL = "#09090b"; // --bg-shell

export function readInitData(hash: string): string | null {
  return new URLSearchParams(hash.replace(/^#/, "")).get("tgWebAppData") || null;
}

/** Captured once at startup, before anything rewrites the URL. */
export const initData: string | null = readInitData(window.location.hash);

/** Set when a Mini App sign-in is refused, for the sign-in page to explain. */
export const miniApp: { error?: "access" | "signin" } = {};

function forgetLaunchData(): void {
  // The launch data is a credential for a day; don't leave it in the address.
  window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
}

/**
 * Open a link outside the app. Inside Telegram it opens in the phone's browser,
 * which Google's sign-in requires (it refuses in-app web views).
 */
export function openExternal(url: string): void {
  const app = window.Telegram?.WebApp;
  if (app?.openLink) app.openLink(url);
  else window.open(url, "_blank", "noopener,noreferrer");
}

/** Load Telegram's script (for the full-height panel and header colour), then tidy the URL. */
export function startMiniApp(): void {
  if (!initData) return;
  const script = document.createElement("script");
  script.src = "https://telegram.org/js/telegram-web-app.js";
  script.async = true;
  script.onload = () => {
    const app = window.Telegram?.WebApp;
    try {
      app?.ready();
      app?.expand();
      app?.setHeaderColor?.(SHELL);
      app?.setBackgroundColor?.(SHELL);
    } finally {
      forgetLaunchData();
    }
  };
  script.onerror = forgetLaunchData;
  document.head.appendChild(script);
}
