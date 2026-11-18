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

describe("the keyboard class (bottom bar hidden while typing)", () => {
  const coarse = (on: boolean) =>
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: (q: string) => ({ matches: on && q.includes("coarse"), media: q, addEventListener() {}, removeEventListener() {} }),
    });
  const keyboard = () => root.classList.contains("keyboard");
  const field = () => {
    const input = document.createElement("input");
    document.body.append(input);
    return input;
  };

  afterEach(() => {
    document.body.replaceChildren();
    root.classList.remove("keyboard");
  });

  it("comes on when a text field takes the focus on a touch screen", () => {
    coarse(true);
    const stop = watchViewport();
    field().focus();
    expect(keyboard()).toBe(true);
    stop();
  });

  it("goes when a field is removed without a focusout (iOS), as a sheet closing does", async () => {
    coarse(true);
    const stop = watchViewport();
    const input = field();
    input.focus();
    expect(keyboard()).toBe(true);
    // iOS removes a focused field without sending focusout/blur: stop jsdom sending them too.
    const quiet = (e: Event) => e.stopImmediatePropagation();
    document.addEventListener("focusout", quiet, true);
    input.remove();
    await new Promise((r) => setTimeout(r, 0)); // mutation observers run as a microtask
    expect(keyboard()).toBe(true); // not at once: a tap may still be landing
    await new Promise((r) => setTimeout(r, 200));
    expect(keyboard()).toBe(false);
    document.removeEventListener("focusout", quiet, true);
    stop();
  });

  it("goes when the focus moves to a button, and on a tap once no field has it", async () => {
    coarse(true);
    const stop = watchViewport();
    const input = field();
    input.focus();
    const button = document.createElement("button");
    document.body.append(button);
    button.focus();
    expect(keyboard()).toBe(true);
    await new Promise((r) => setTimeout(r, 200));
    expect(keyboard()).toBe(false);

    input.focus();
    expect(keyboard()).toBe(true);
    root.classList.add("keyboard");
    (document.activeElement as HTMLElement).blur();
    document.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 200));
    expect(keyboard()).toBe(false);
    stop();
  });

  it("stays while a field still has the focus, whatever else changes", async () => {
    coarse(true);
    const stop = watchViewport();
    field().focus();
    document.body.append(document.createElement("div"));
    document.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 200));
    expect(keyboard()).toBe(true);
    stop();
  });

  it("never comes on with a mouse", () => {
    coarse(false);
    const stop = watchViewport();
    field().focus();
    expect(keyboard()).toBe(false);
    stop();
  });
});
