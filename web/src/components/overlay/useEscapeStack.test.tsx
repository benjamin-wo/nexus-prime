import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useEscapeStack } from "./useEscapeStack";

function Listener({ fn }: { fn: () => void }) {
  useEscapeStack(fn);
  return null;
}
const esc = () => fireEvent.keyDown(window, { key: "Escape" });

describe("useEscapeStack", () => {
  it("gives Escape to the newest handler, and back to the previous one when it unmounts", () => {
    const first = vi.fn();
    const second = vi.fn();
    render(<Listener fn={first} />);
    const top = render(<Listener fn={second} />);
    esc();
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
    top.unmount();
    esc();
    expect(first).toHaveBeenCalledTimes(1);
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("ignores other keys, and an Escape that was stopped before window", () => {
    const fn = vi.fn();
    const { getByTestId } = render(
      <div onKeyDown={(e) => e.stopPropagation()}>
        <input data-testid="field" />
        <Listener fn={fn} />
      </div>,
    );
    fireEvent.keyDown(window, { key: "Enter" });
    fireEvent.keyDown(getByTestId("field"), { key: "Escape" });
    expect(fn).not.toHaveBeenCalled();
    esc();
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("calls the latest handler", () => {
    const old = vi.fn();
    const next = vi.fn();
    const { rerender } = render(<Listener fn={old} />);
    rerender(<Listener fn={next} />);
    esc();
    expect(old).not.toHaveBeenCalled();
    expect(next).toHaveBeenCalledTimes(1);
  });
});
