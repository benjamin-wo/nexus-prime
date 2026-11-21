/**
 * Running inside the Nexus iOS app (an Expo shell around this site in a WebView). The app injects
 * `window.NexusNative` before the page loads and listens for the messages below; see
 * `mobile/src/bridge.ts` for the other end. Outside the app every call here does nothing.
 */

export type HapticKind = "light" | "medium" | "success" | "warning" | "error" | "selection";
export type SharePayload = { title?: string; url?: string; text?: string };

declare global {
  interface Window {
    NexusNative?: { v?: number; platform?: string };
    ReactNativeWebView?: { postMessage(message: string): void };
  }
}

export function inNativeApp(): boolean {
  return window.NexusNative?.platform === "ios" || typeof window.ReactNativeWebView?.postMessage === "function";
}

function send(message: Record<string, unknown>): void {
  if (!inNativeApp()) return;
  try {
    window.ReactNativeWebView?.postMessage(JSON.stringify({ v: 1, ...message }));
  } catch {
    // A missing bridge must never break the page.
  }
}

export function nativeHaptic(kind: HapticKind = "light"): void {
  send({ type: "haptic", kind });
}

export function nativeShare(payload: SharePayload): void {
  send({ type: "share", ...payload });
}

/** Marks the page as hosted by the app (for styling) and tells the app the page is up. */
export function startNative(): void {
  if (!inNativeApp()) return;
  document.documentElement.dataset.host = "ios";
  send({ type: "ready" });
}
