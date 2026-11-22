import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { describe, expect, it } from "vitest";

import { useFocusManagement } from "./useFocusManagement";

function Panel({ modal = true, initialFocus }: { modal?: boolean; initialFocus?: string }) {
  const panel = useRef<HTMLDivElement>(null);
  useFocusManagement({ panel, modal, initialFocus });
  return (
    <div ref={panel} tabIndex={-1} role="dialog" aria-label="Panel">
      <button type="button">First</button>
      <input aria-label="Name" />
      <button type="button">Last</button>
    </div>
  );
}

describe("useFocusManagement", () => {
  it("focuses the first field, or the dialog when asked", () => {
    const a = render(<Panel />);
    expect(screen.getByLabelText("Name")).toHaveFocus();
    a.unmount();
    render(<Panel initialFocus="dialog" />);
    expect(screen.getByRole("dialog")).toHaveFocus();
  });

  it("wraps Tab and Shift+Tab inside a modal panel", async () => {
    const user = userEvent.setup();
    render(<Panel />);
    await user.tab();
    expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "Last" })).toHaveFocus();
  });

  it("does not trap a non-modal panel", async () => {
    const user = userEvent.setup();
    render(
      <>
        <Panel modal={false} />
        <button type="button">Outside</button>
      </>,
    );
    await user.tab();
    await user.tab();
    expect(screen.getByRole("button", { name: "Outside" })).toHaveFocus();
  });

  it("gives the focus back to the opener on close", async () => {
    const user = userEvent.setup();
    function Page() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen((o) => !o)}>
            Toggle
          </button>
          {open && <Panel />}
        </>
      );
    }
    render(<Page />);
    const opener = screen.getByRole("button", { name: "Toggle" });
    await user.click(opener);
    expect(screen.getByLabelText("Name")).toHaveFocus();
    await user.click(opener);
    expect(opener).toHaveFocus();
  });
});
