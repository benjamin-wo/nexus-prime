import { afterEach, describe, expect, it, vi } from "vitest";

import { hapticImpact, hapticSelection, tripInviteIn } from "./telegram";

describe("the trip invite in an address", () => {
  it("is the token of a trip invite link", () => {
    expect(tripInviteIn("/trip-invite/abc_DEF-123")).toBe("abc_DEF-123");
    expect(tripInviteIn("/trip-invite/a%20b")).toBe("a b");
  });

  it("is nothing for any other address", () => {
    for (const path of ["/", "/travel", "/invite/abc", "/trip-invite/", "/trip-invite", "/x/trip-invite/abc"]) {
      expect(tripInviteIn(path)).toBeNull();
    }
    expect(tripInviteIn("/trip-invite/%E0%A4%A")).toBeNull(); // not valid percent-encoding
  });
});

describe("haptics", () => {
  afterEach(() => {
    delete window.Telegram;
  });

  it("do nothing outside Telegram", () => {
    expect(() => {
      hapticImpact("medium");
      hapticSelection();
    }).not.toThrow();
  });

  it("go through Telegram's haptic engine when it has one", () => {
    const impactOccurred = vi.fn();
    const selectionChanged = vi.fn();
    window.Telegram = { WebApp: { ready() {}, expand() {}, HapticFeedback: { impactOccurred, selectionChanged } } };
    hapticImpact("medium");
    hapticSelection();
    expect(impactOccurred).toHaveBeenCalledWith("medium");
    expect(selectionChanged).toHaveBeenCalledTimes(1);
  });

  it("do nothing on a Telegram without them, or when they throw", () => {
    window.Telegram = { WebApp: { ready() {}, expand() {} } };
    expect(() => hapticImpact()).not.toThrow();
    window.Telegram = {
      WebApp: {
        ready() {},
        expand() {},
        HapticFeedback: {
          impactOccurred() {
            throw new Error("nope");
          },
          selectionChanged() {
            throw new Error("nope");
          },
        },
      },
    };
    expect(() => {
      hapticImpact();
      hapticSelection();
    }).not.toThrow();
  });
});
