import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useScrollLock } from "./useScrollLock";

function Locker() {
  useScrollLock();
  return null;
}
const locked = () => document.documentElement.classList.contains("overlay-open");

describe("useScrollLock", () => {
  it("keeps the class until the last overlay closes", () => {
    const a = render(<Locker />);
    expect(locked()).toBe(true);
    const b = render(<Locker />);
    a.unmount();
    expect(locked()).toBe(true);
    b.unmount();
    expect(locked()).toBe(false);
  });

  it("does nothing while inactive", () => {
    function Off() {
      useScrollLock(false);
      return null;
    }
    const { unmount } = render(<Off />);
    expect(locked()).toBe(false);
    unmount();
  });
});
