import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Sheet } from "./Sheet";

describe("the sheet", () => {
  it("is a modal dialog named by its title", () => {
    render(
      <Sheet title="Recent changes" onClose={() => {}}>
        <p>Nothing yet.</p>
      </Sheet>,
    );
    const dialog = screen.getByRole("dialog", { name: "Recent changes" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { name: "Recent changes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    // It is in the page body, not inside whatever rendered it.
    expect(dialog.closest("body")).toBe(document.body);
  });

  it("closes on Escape, on Close and on a click outside, but not on a click inside", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Sheet title="Stops" onClose={onClose}>
        <p>Where you are.</p>
      </Sheet>,
    );
    await user.click(screen.getByText("Where you are."));
    await user.click(screen.getByRole("dialog"));
    expect(onClose).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);

    const backdrop = screen.getByRole("dialog").parentElement as HTMLElement;
    expect(backdrop).toHaveClass("sheet-backdrop");
    await user.click(backdrop);
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("shows a back button only when it can go back, with its own name", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    const { rerender } = render(
      <Sheet title="Add to Tokyo" onClose={() => {}}>
        <p>Choices</p>
      </Sheet>,
    );
    expect(screen.queryByRole("button", { name: /back/i })).toBeNull();

    rerender(
      <Sheet title="Add a booking" onClose={() => {}} onBack={onBack}>
        <p>Form</p>
      </Sheet>,
    );
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(onBack).toHaveBeenCalledTimes(1);

    rerender(
      <Sheet title="Add a booking" onClose={() => {}} onBack={onBack} backLabel="Back to the ways to add">
        <p>Form</p>
      </Sheet>,
    );
    expect(screen.getByRole("button", { name: "Back to the ways to add" })).toBeInTheDocument();
  });

  it("puts the focus on the first field and gives it back on close", async () => {
    const user = userEvent.setup();
    function Page() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open
          </button>
          {open && (
            <Sheet title="Drop a pin here" onClose={() => setOpen(false)}>
              <button type="button">Not a field</button>
              <label>
                Name
                <input />
              </label>
            </Sheet>
          )}
        </>
      );
    }
    render(<Page />);
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);
    expect(screen.getByLabelText("Name")).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(opener).toHaveFocus();
  });

  it("focuses the dialog itself when there is no field, and locks the page's scroll while open", () => {
    const { unmount } = render(
      <Sheet title="Recent changes" onClose={() => {}}>
        <p>Nothing yet.</p>
      </Sheet>,
    );
    expect(screen.getByRole("dialog")).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("can be a form that submits", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((e: { preventDefault: () => void }) => e.preventDefault());
    render(
      <Sheet as="form" title="Drop a pin here" onClose={() => {}} onSubmit={onSubmit}>
        <button type="submit">Save pin</button>
      </Sheet>,
    );
    expect(screen.getByRole("dialog", { name: "Drop a pin here" }).tagName).toBe("FORM");
    await user.click(screen.getByRole("button", { name: "Save pin" }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });
});
