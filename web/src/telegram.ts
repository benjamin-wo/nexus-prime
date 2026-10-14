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
  setBottomBarColor?(color: string): void;
  disableVerticalSwipes?(): void;
  openLink?(url: string): void;
  BackButton?: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: { impactOccurred(style: "light" | "medium"): void; selectionChanged(): void };
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

const READY = "nexus:telegram-ready";

/** Calls ``then`` with Telegram's app once its script has loaded (straight away if it
 * has); returns a function that stops waiting. Outside Telegram it never calls. */
export function withMiniApp(then: (app: WebApp) => void): () => void {
  const app = window.Telegram?.WebApp;
  if (app?.BackButton) {
    then(app);
    return () => {};
  }
  const onReady = () => window.Telegram?.WebApp && then(window.Telegram.WebApp);
  window.addEventListener(READY, onReady);
  return () => window.removeEventListener(READY, onReady);
}

/** A light tap under the finger for the main button, a tick for changing tab or
 * day: the feel of a native app, through Telegram (phones that have it). */
function hapticsOnTap(app: WebApp): void {
  document.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target || !app.HapticFeedback) return;
    if (target.closest(".btn-primary, .trip-fab-button")) app.HapticFeedback.impactOccurred("light");
    else if (target.closest(".nav-link, .dept-tab, .day-pill, .tab")) app.HapticFeedback.selectionChanged();
  });
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
      app?.setBottomBarColor?.(SHELL);
      // Pages scroll inside the app: a swipe down while reading shouldn't close it.
      app?.disableVerticalSwipes?.();
      if (app) hapticsOnTap(app);
    } finally {
      forgetLaunchData();
      window.dispatchEvent(new Event(READY));
    }
  };
  script.onerror = forgetLaunchData;
  document.head.appendChild(script);
}
