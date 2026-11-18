import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LONG_PRESS_MS, type LongPressOptions, useLongPress } from "./useLongPress";

function Row({ onLong, onClick, options }: { onLong: (key: string) => void; onClick: () => void; options?: LongPressOptions }) {
  const bind = useLongPress<string>(onLong, options);
  return (
    <div data-testid="row" onClick={onClick} {...bind("row-1")}>
      <button type="button">Name</button>
      <input aria-label="Tick" type="checkbox" />
      <a href="#x">Link</a>
    </div>
  );
}

const down = (el: Element, init: PointerEventInit = {}) =>
  fireEvent.pointerDown(el, { pointerType: "touch", pointerId: 1, isPrimary: true, button: 0, clientX: 100, clientY: 100, ...init });
const move = (el: Element, init: PointerEventInit = {}) =>
  fireEvent.pointerMove(el, { pointerType: "touch", pointerId: 1, isPrimary: true, clientX: 100, clientY: 100, ...init });
const up = (el: Element, init: PointerEventInit = {}) =>
  fireEvent.pointerUp(el, { pointerType: "touch", pointerId: 1, isPrimary: true, clientX: 100, clientY: 100, ...init });
const wait = (ms: number) => act(() => void vi.advanceTimersByTime(ms));

function setup(options?: LongPressOptions) {
  const onLong = vi.fn();
  const onClick = vi.fn();
  render(<Row onLong={onLong} onClick={onClick} options={options} />);
  return { onLong, onClick, row: screen.getByTestId("row") };
}

describe("useLongPress", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("fires once, with the row's key, after the delay", () => {
    const { onLong, row } = setup();
    down(row);
    wait(LONG_PRESS_MS - 1);
    expect(onLong).not.toHaveBeenCalled();
    wait(1);
    expect(onLong).toHaveBeenCalledTimes(1);
    expect(onLong).toHaveBeenCalledWith("row-1");
    wait(2000);
    expect(onLong).toHaveBeenCalledTimes(1);
  });

  it("honours a delay of its own", () => {
    const { onLong, row } = setup({ delay: 800 });
    down(row);
    wait(799);
    expect(onLong).not.toHaveBeenCalled();
    wait(1);
    expect(onLong).toHaveBeenCalledTimes(1);
  });

  it("is dropped when the finger moves further than the slop (a scroll)", () => {
    const { onLong, row } = setup();
    down(row);
    wait(200);
    move(row, { clientY: 100 + 11 });
    wait(1000);
    expect(onLong).not.toHaveBeenCalled();
  });

  it("survives a wobble inside the slop", () => {
    const { onLong, row } = setup();
    down(row);
    move(row, { clientX: 100 + 5, clientY: 100 + 5 });
    move(row, { clientX: 100 - 6, clientY: 100 });
    wait(LONG_PRESS_MS);
    expect(onLong).toHaveBeenCalledTimes(1);
  });

  it("is dropped by lifting early, and the tap that follows is not swallowed", () => {
    const { onLong, onClick, row } = setup();
    down(row);
    wait(200);
    up(row);
    wait(1000);
    expect(onLong).not.toHaveBeenCalled();
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("is dropped by pointercancel (the browser took the touch to scroll)", () => {
    const { onLong, row } = setup();
    down(row);
    wait(200);
    fireEvent.pointerCancel(row, { pointerType: "touch", pointerId: 1, isPrimary: true });
    wait(1000);
    expect(onLong).not.toHaveBeenCalled();
  });

  it("is dropped by a second finger", () => {
    const { onLong, row } = setup();
    down(row);
    wait(200);
    down(row, { pointerId: 2, isPrimary: false, clientX: 160 });
    wait(1000);
    expect(onLong).not.toHaveBeenCalled();
  });

  it("swallows the click that follows a long press, once", () => {
    const { onLong, onClick, row } = setup();
    down(row);
    wait(LONG_PRESS_MS);
    expect(onLong).toHaveBeenCalledTimes(1);
    up(row);
    // The click a finger lifting makes, even on a button inside the row.
    fireEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(onClick).not.toHaveBeenCalled();
    // The next tap is an ordinary one.
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("doesn't let a click that never came eat a later tap", () => {
    const { onClick, row } = setup();
    down(row);
    wait(LONG_PRESS_MS);
    up(row);
    wait(1000);
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("doesn't swallow clicks after a cancelled press", () => {
    const { onClick, row } = setup();
    down(row);
    wait(LONG_PRESS_MS);
    fireEvent.pointerCancel(row, { pointerType: "touch", pointerId: 1, isPrimary: true });
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("ignores a mouse by default", () => {
    const { onLong, row } = setup();
    down(row, { pointerType: "mouse" });
    wait(LONG_PRESS_MS);
    expect(onLong).not.toHaveBeenCalled();
  });

  it("takes a mouse when asked", () => {
    const { onLong, row } = setup({ mouse: true });
    down(row, { pointerType: "mouse" });
    wait(LONG_PRESS_MS);
    expect(onLong).toHaveBeenCalledTimes(1);
  });

  it("ignores buttons other than the main one (a mouse right-click)", () => {
    const { onLong, row } = setup({ mouse: true });
    down(row, { pointerType: "mouse", button: 2 });
    wait(LONG_PRESS_MS * 2);
    expect(onLong).not.toHaveBeenCalled();
  });

  it("leaves inputs and links to themselves", () => {
    const { onLong } = setup();
    down(screen.getByRole("checkbox"));
    wait(LONG_PRESS_MS);
    down(screen.getByRole("link"));
    wait(LONG_PRESS_MS);
    expect(onLong).not.toHaveBeenCalled();
  });

  it("does nothing while disabled", () => {
    const { onLong, row } = setup({ enabled: false });
    down(row);
    wait(LONG_PRESS_MS);
    expect(onLong).not.toHaveBeenCalled();
  });

  it("stops the touch context menu but keeps a mouse's", () => {
    const { row } = setup();
    down(row, { pointerType: "touch" });
    expect(fireEvent.contextMenu(row)).toBe(false); // preventDefault was called
    up(row);
    down(row, { pointerType: "mouse", button: 2 });
    expect(fireEvent.contextMenu(row)).toBe(true);
  });

  it("drops a press in progress when the row goes away", () => {
    const onLong = vi.fn();
    const { unmount } = render(<Row onLong={onLong} onClick={() => {}} />);
    down(screen.getByTestId("row"));
    unmount();
    wait(LONG_PRESS_MS * 2);
    expect(onLong).not.toHaveBeenCalled();
  });
});
