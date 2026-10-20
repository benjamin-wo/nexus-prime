import { describe, expect, it } from "vitest";

import { LIVE_REFRESH_MS, livePolling } from "./prices";

describe("livePolling", () => {
  it("polls every 60 seconds while the price is live and the page is visible", () => {
    expect(LIVE_REFRESH_MS).toBe(60_000);
    expect(livePolling("live", "visible")).toBe(60_000);
  });

  it("does not poll for a close, provisional or not, or before there is a price", () => {
    expect(livePolling("close", "visible")).toBe(false);
    expect(livePolling("provisional_close", "visible")).toBe(false);
    expect(livePolling(null, "visible")).toBe(false);
    expect(livePolling(undefined, "visible")).toBe(false);
  });

  it("does not poll while the page is hidden", () => {
    expect(livePolling("live", "hidden")).toBe(false);
  });

  it("reads the page's own visibility by default", () => {
    const state = Object.getOwnPropertyDescriptor(Document.prototype, "visibilityState");
    const set = (value: string) => Object.defineProperty(document, "visibilityState", { value, configurable: true });
    try {
      set("hidden");
      expect(livePolling("live")).toBe(false);
      set("visible");
      expect(livePolling("live")).toBe(60_000);
    } finally {
      delete (document as unknown as Record<string, unknown>).visibilityState;
      if (state) Object.defineProperty(Document.prototype, "visibilityState", state);
    }
  });
});
