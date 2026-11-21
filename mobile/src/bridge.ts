/**
 * The message protocol between the site (web/src/native.ts) and this app.
 * Every message is JSON: { v: 1, type, ... }. Anything malformed, of another version, or sent by a
 * page outside the Nexus origin is ignored.
 */

export const HAPTIC_KINDS = ["light", "medium", "success", "warning", "error", "selection"] as const;
export type HapticKind = (typeof HAPTIC_KINDS)[number];

export type BridgeMessage =
  | { v: 1; type: "ready" }
  | { v: 1; type: "haptic"; kind: HapticKind }
  | { v: 1; type: "share"; title?: string; url?: string; text?: string };

/** Set before the page loads, so the site knows it is inside the app. */
export const INJECTED_BEFORE_LOAD = `window.NexusNative = { v: 1, platform: 'ios' }; true;`;

export function originOf(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.origin : null;
  } catch {
    return null;
  }
}

function text(value: unknown, max: number): string | undefined {
  return typeof value === "string" && value.length > 0 ? value.slice(0, max) : undefined;
}

/** The message, or null when it should be ignored. `fromUrl` is the page that sent it. */
export function parseMessage(raw: unknown, fromUrl: string, siteUrl: string): BridgeMessage | null {
  const site = originOf(siteUrl);
  if (!site || originOf(fromUrl) !== site || typeof raw !== "string" || raw.length > 10_000) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const msg = data as Record<string, unknown>;
  if (msg.v !== 1) return null;
  switch (msg.type) {
    case "ready":
      return { v: 1, type: "ready" };
    case "haptic":
      return HAPTIC_KINDS.includes(msg.kind as HapticKind) ? { v: 1, type: "haptic", kind: msg.kind as HapticKind } : null;
    case "share": {
      const url = text(msg.url, 2000);
      // A shared link must stay on the Nexus site.
      if (url && originOf(url) !== site) return null;
      const out = { v: 1 as const, type: "share" as const, title: text(msg.title, 200), url, text: text(msg.text, 2000) };
      return out.url || out.text ? out : null;
    }
    default:
      return null;
  }
}
