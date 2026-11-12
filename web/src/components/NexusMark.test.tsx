import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NexusMark, NexusWordmark } from "./NexusMark";

describe("NexusMark", () => {
  it("is decorative unless it is given a name", () => {
    const { container } = render(<NexusMark size={28} className="msg-avatar" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).not.toHaveAttribute("role");
    expect(svg).toHaveClass("nexus-mark", "msg-avatar");
    expect(screen.queryByRole("img")).toBeNull();
  });

  it("carries its name when it stands for something on its own", () => {
    render(<NexusMark alt="Nexus" />);
    expect(screen.getByRole("img", { name: "Nexus" })).toBeInTheDocument();
  });

  it("is square for a slot and as tall as the mark when big", () => {
    const { container, rerender } = render(<NexusMark size={40} />);
    expect(container.querySelector("svg")).toHaveAttribute("height", "40");
    rerender(<NexusMark size={134} big />);
    expect(container.querySelector("svg")).toHaveAttribute("height", "112");
  });

  it("draws in the brand palette, or in one colour for a coloured button", () => {
    const { container, rerender } = render(<NexusMark />);
    const fills = new Set([...container.querySelectorAll("rect")].map((r) => r.getAttribute("fill")));
    expect([...fills].sort()).toEqual(["#0B1020", "#22D3EE", "#2563EB", "#A3FF12"]);
    rerender(<NexusMark variant="cloud" />);
    const cloud = new Set([...container.querySelectorAll("rect")].map((r) => r.getAttribute("fill")));
    expect([...cloud]).toEqual(["#F8FAFC"]);
    rerender(<NexusMark variant="mono" />);
    const mono = new Set([...container.querySelectorAll("rect")].map((r) => r.getAttribute("fill")));
    expect([...mono]).toEqual(["currentColor"]);
  });
});

describe("NexusWordmark", () => {
  it("keeps the proportions of the letters, with or without the tagline", () => {
    const { container, rerender } = render(<NexusWordmark height={20} />);
    expect(container.querySelector("svg")).toHaveAttribute("width", "100");
    rerender(<NexusWordmark height={32} tagline alt="Nexus" />);
    expect(screen.getByRole("img", { name: "Nexus" })).toHaveAttribute("width", "100");
  });
});
