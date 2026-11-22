import { act, fireEvent, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDragToClose } from "./useDragToClose";

const haptic = vi.fn();
vi.mock("../../native", () => ({ nativeHaptic: (k: string) => haptic(k) }));

function Harness({ onClose, enabled = true }: { onClose: () => void; enabled?: boolean }) {
  const handle = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  useDragToClose({ handle, panel, backdrop, onClose, enabled });
  return (
    <div ref={backdrop} data-testid="backdrop">
      <div ref={panel} data-testid="panel">
        <div ref={handle} data-testid="handle">
          <span data-testid="grab" />
          <button type="button">Close</button>
        </div>
      </div>
    </div>
  );
}

let now = 0;
const move = (el: Element, y: number, x = 0, dt = 100) => {
  now += dt;
  fireEvent.pointerMove(el, { pointerId: 1, clientX: x, clientY: y });
};
const down = (el: Element) => fireEvent.pointerDown(el, { pointerId: 1, clientX: 0, clientY: 0, button: 0 });

beforeEach(() => {
  vi.useFakeTimers();
  now = 0;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  haptic.mockClear();
  Element.prototype.setPointerCapture = vi.fn();
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ height: 400 } as DOMRect);
  window.matchMedia = vi.fn().mockReturnValue({ matches: false }) as unknown as typeof window.matchMedia;
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useDragToClose", () => {
  it("closes after a drag past a quarter of the height, once the slide has ended", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Harness onClose={onClose} />);
    const grab = getByTestId("grab");
    down(grab);
    move(grab, 50);
    move(grab, 150, 0, 300);
    expect(getByTestId("panel").style.transform).toBe("translateY(150px)");
    expect(Number(getByTestId("backdrop").style.opacity)).toBeLessThan(1);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    expect(getByTestId("panel").style.transform).toBe("translateY(100%)");
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.transitionEnd(getByTestId("panel"));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(haptic).toHaveBeenCalledWith("light");
  });

  it("closes on the timeout if no transition ends", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Harness onClose={onClose} />);
    const grab = getByTestId("grab");
    down(grab);
    move(grab, 20);
    move(grab, 200, 0, 500);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    act(() => void vi.advanceTimersByTime(300));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("springs back after a short, slow drag", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Harness onClose={onClose} />);
    const grab = getByTestId("grab");
    down(grab);
    move(grab, 10, 0, 500);
    move(grab, 40, 0, 500);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    expect(getByTestId("panel").style.transform).toBe("translateY(0)");
    act(() => void vi.advanceTimersByTime(300));
    expect(onClose).not.toHaveBeenCalled();
    expect(getByTestId("panel").style.transform).toBe("");
    expect(getByTestId("backdrop").style.opacity).toBe("");
  });

  it("closes on a fast short flick", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Harness onClose={onClose} />);
    const grab = getByTestId("grab");
    down(grab);
    move(grab, 10, 0, 500);
    move(grab, 40, 0, 20);
    move(grab, 80, 0, 20);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    act(() => void vi.advanceTimersByTime(300));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores an upward or sideways start", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Harness onClose={onClose} />);
    const grab = getByTestId("grab");
    down(grab);
    move(grab, -30);
    move(grab, 300);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    down(grab);
    move(grab, 8, 40);
    move(grab, 300);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    act(() => void vi.advanceTimersByTime(300));
    expect(getByTestId("panel").style.transform).toBe("");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("leaves a press on a button in the handle alone", () => {
    const onClose = vi.fn();
    const { getByRole, getByTestId } = render(<Harness onClose={onClose} />);
    const button = getByRole("button");
    down(button);
    move(button, 20);
    move(button, 300);
    fireEvent.pointerUp(button, { pointerId: 1 });
    act(() => void vi.advanceTimersByTime(300));
    expect(getByTestId("panel").style.transform).toBe("");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("does nothing when disabled", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Harness onClose={onClose} enabled={false} />);
    const grab = getByTestId("grab");
    down(grab);
    move(grab, 20);
    move(grab, 300);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    act(() => void vi.advanceTimersByTime(300));
    expect(getByTestId("panel").style.transform).toBe("");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("with reduced motion closes at once, with no transition", () => {
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia;
    const onClose = vi.fn();
    const { getByTestId } = render(<Harness onClose={onClose} />);
    const grab = getByTestId("grab");
    down(grab);
    move(grab, 20);
    move(grab, 300, 0, 500);
    fireEvent.pointerUp(grab, { pointerId: 1 });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("useDragToClose pulling down from the top of the scroller", () => {
  function Pull({ onClose, scrollTop = 0 }: { onClose: () => void; scrollTop?: number }) {
    const panel = useRef<HTMLDivElement>(null);
    const backdrop = useRef<HTMLDivElement>(null);
    const scroller = useRef<HTMLDivElement>(null);
    useDragToClose({ panel, backdrop, scroller, onClose, enabled: true });
    return (
      <div ref={backdrop}>
        <div ref={panel} data-testid="panel">
          <div
            ref={(el) => {
              (scroller as { current: HTMLDivElement | null }).current = el;
              if (el) el.scrollTop = scrollTop;
            }}
            data-testid="body"
          >
            <p data-testid="text">Content</p>
            <input data-testid="field" />
          </div>
        </div>
      </div>
    );
  }
  const touch = (y: number, x = 0) => ({ touches: [{ clientX: x, clientY: y }] });
  const start = (el: Element, y = 0) => fireEvent.touchStart(el, touch(y));
  const drag = (el: Element, y: number, x = 0, dt = 100) => {
    now += dt;
    return fireEvent.touchMove(el, touch(y, x));
  };

  it("closes when pulled past the threshold from scrollTop 0, and takes the gesture", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Pull onClose={onClose} />);
    const text = getByTestId("text");
    start(text);
    drag(text, 5, 0, 300);
    const notPrevented = drag(text, 200, 0, 300);
    expect(notPrevented).toBe(false); // preventDefault was called
    expect(getByTestId("panel").style.transform).toBe("translateY(200px)");
    fireEvent.touchEnd(text);
    act(() => void vi.advanceTimersByTime(300));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the body is scrolled", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Pull onClose={onClose} scrollTop={30} />);
    const text = getByTestId("text");
    start(text);
    drag(text, 5);
    expect(drag(text, 250)).toBe(true);
    fireEvent.touchEnd(text);
    act(() => void vi.advanceTimersByTime(300));
    expect(getByTestId("panel").style.transform).toBe("");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("gives up on an upward start, and one that starts in a field", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Pull onClose={onClose} />);
    const text = getByTestId("text");
    start(text);
    drag(text, -20);
    expect(drag(text, 300)).toBe(true);
    fireEvent.touchEnd(text);
    const field = getByTestId("field");
    start(field);
    drag(field, 20);
    drag(field, 300);
    fireEvent.touchEnd(field);
    act(() => void vi.advanceTimersByTime(300));
    expect(getByTestId("panel").style.transform).toBe("");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("springs back on touchcancel", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Pull onClose={onClose} />);
    const text = getByTestId("text");
    start(text);
    drag(text, 20, 0, 300);
    drag(text, 300, 0, 500);
    fireEvent.touchCancel(text);
    expect(getByTestId("panel").style.transform).toBe("translateY(0)");
    act(() => void vi.advanceTimersByTime(300));
    expect(getByTestId("panel").style.transform).toBe("");
    expect(onClose).not.toHaveBeenCalled();
  });
});
