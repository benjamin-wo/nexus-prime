import { afterEach, describe, expect, it, vi } from "vitest";

import { CHROME, THEME_EVENT, currentScheme, setTheme } from "./theme";

function phoneIsDark(dark: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: dark && query.includes("dark"),
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

afterEach(() => {
  delete document.documentElement.dataset.theme;
  vi.unstubAllGlobals();
});

describe("the colour scheme", () => {
  it("follows the phone until a theme is set", () => {
    phoneIsDark(true);
    expect(currentScheme()).toBe("dark");
    phoneIsDark(false);
    expect(currentScheme()).toBe("light");
  });

  it("is the set theme, whatever the phone says", () => {
    phoneIsDark(true);
    setTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(currentScheme()).toBe("light");
  });

  it("tells the page only when the scheme actually changes", () => {
    phoneIsDark(false);
    const heard = vi.fn();
    window.addEventListener(THEME_EVENT, heard);
    expect(setTheme("light")).toBe(false);
    expect(setTheme("dark")).toBe(true);
    expect(setTheme("dark")).toBe(false);
    window.removeEventListener(THEME_EVENT, heard);
    expect(heard).toHaveBeenCalledTimes(1);
  });

  it("has colours for Telegram's header and bar in both schemes", () => {
    expect(CHROME.light.shell).toBe("#f8fafc");
    expect(CHROME.dark.shell).toBe("#0b1020");
  });
});
