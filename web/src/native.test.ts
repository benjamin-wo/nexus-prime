import { afterEach, describe, expect, it, vi } from "vitest";

import { inNativeApp, nativeHaptic, nativeShare, startNative } from "./native";

afterEach(() => {
  delete window.NexusNative;
  delete window.ReactNativeWebView;
  delete document.documentElement.dataset.host;
});

describe("native bridge", () => {
  it("does nothing outside the app", () => {
    expect(inNativeApp()).toBe(false);
    nativeHaptic("success");
    startNative();
    expect(document.documentElement.dataset.host).toBeUndefined();
  });

  it("posts versioned messages inside the app", () => {
    const postMessage = vi.fn();
    window.ReactNativeWebView = { postMessage };
    window.NexusNative = { v: 1, platform: "ios" };
    nativeHaptic("success");
    nativeShare({ title: "T", url: "https://example.com/" });
    expect(JSON.parse(postMessage.mock.calls[0][0])).toEqual({ v: 1, type: "haptic", kind: "success" });
    expect(JSON.parse(postMessage.mock.calls[1][0])).toEqual({
      v: 1,
      type: "share",
      title: "T",
      url: "https://example.com/",
    });
  });

  it("marks the page and says ready on start", () => {
    const postMessage = vi.fn();
    window.ReactNativeWebView = { postMessage };
    startNative();
    expect(document.documentElement.dataset.host).toBe("ios");
    expect(JSON.parse(postMessage.mock.calls[0][0])).toEqual({ v: 1, type: "ready" });
  });

  it("swallows a failing bridge", () => {
    window.ReactNativeWebView = {
      postMessage: () => {
        throw new Error("gone");
      },
    };
    expect(() => nativeHaptic()).not.toThrow();
  });
});
