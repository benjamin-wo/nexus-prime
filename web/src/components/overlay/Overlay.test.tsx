import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Overlay } from "./Overlay";

describe("Overlay", () => {
  it("a panel's aria-modal follows `modal`, and only a modal one locks the page", () => {
    const { rerender } = render(
      <Overlay shape="panel" labelledBy="t" onClose={() => {}} modal={false}>
        <h2 id="t">Chat</h2>
      </Overlay>,
    );
    expect(screen.getByRole("dialog", { name: "Chat" })).toHaveAttribute("aria-modal", "false");
    expect(document.documentElement).not.toHaveClass("overlay-open");
    rerender(
      <Overlay shape="panel" labelledBy="t" onClose={() => {}} modal>
        <h2 id="t">Chat</h2>
      </Overlay>,
    );
    expect(screen.getByRole("dialog", { name: "Chat" })).toHaveAttribute("aria-modal", "true");
    expect(document.documentElement).toHaveClass("overlay-open");
  });

  it("a panel has no backdrop; a sheet does, and is modal", () => {
    const panel = render(
      <Overlay shape="panel" labelledBy="t" onClose={() => {}}>
        <h2 id="t">Chat</h2>
      </Overlay>,
    );
    expect(document.querySelector(".overlay-backdrop")).toBeNull();
    panel.unmount();
    render(
      <Overlay shape="sheet" labelledBy="t" onClose={() => {}}>
        <h2 id="t">Sheet</h2>
      </Overlay>,
    );
    expect(document.querySelector(".overlay-backdrop")).not.toBeNull();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
  });
});
