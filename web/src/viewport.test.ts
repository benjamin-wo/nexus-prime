import { afterEach, describe, expect, it } from "vitest";

import { watchViewport } from "./viewport";

/** A stand-in for window.visualViewport: it has a height and a top, and fires resize and scroll. */
class FakeViewport extends EventTarget {
  height = 800;
  offsetTop = 0;
}

const root = document.documentElement;
const vars = () => [root.style.getPropertyValue("--vv-height"), root.style.getPropertyValue("--vv-top")];

afterEach(() => {
  Object.defineProperty(window, "visualViewport", { value: undefined, configurable: true });
  root.style.removeProperty("--vv-height");
  root.style.removeProperty("--vv-top");
});

function fakeViewport(): FakeViewport {
  const vv = new FakeViewport();
  Object.defineProperty(window, "visualViewport", { value: vv, configurable: true });
  return vv;
}

describe("watchViewport", () => {
  it("holds the visible screen in --vv-height and --vv-top, and follows it", () => {
    const vv = fakeViewport();
    const stop = watchViewport();
    expect(vars()).toEqual(["800px", "0px"]);

    vv.height = 480;
    vv.dispatchEvent(new Event("resize"));
    expect(vars()).toEqual(["480px", "0px"]);

    vv.offsetTop = 120;
    vv.dispatchEvent(new Event("scroll"));
    expect(vars()).toEqual(["480px", "120px"]);
    stop();
  });

  it("takes the variables away, and stops listening, when it is disposed", () => {
    const vv = fakeViewport();
    const stop = watchViewport();
    stop();
    expect(vars()).toEqual(["", ""]);

    vv.height = 300;
    vv.dispatchEvent(new Event("resize"));
    expect(vars()).toEqual(["", ""]);
  });

  it("copes with a browser that has no visual viewport", () => {
    const stop = watchViewport();
    expect(vars()).toEqual(["", ""]);
    expect(root.style.getPropertyValue("--stable-height")).not.toBe("");
    stop();
  });
});
