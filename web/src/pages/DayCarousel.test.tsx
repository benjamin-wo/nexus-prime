import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DayCarousel } from "./DayCarousel";

// jsdom has no layout: a slide is as tall as the number on its first child, and a stand-in
// ResizeObserver lets a test say when a slide's content changed.
const watchers = new Set<() => void>();
class FakeResizeObserver {
  constructor(private readonly callback: () => void) {}
  observe() {
    watchers.add(this.callback);
  }
  disconnect() {
    watchers.delete(this.callback);
  }
  unobserve() {}
}
const heights: Record<string, number> = { "2026-11-10": 200, "2026-11-11": 560, "2026-11-12": 320 };

beforeEach(() => {
  watchers.clear();
  vi.stubGlobal("ResizeObserver", FakeResizeObserver);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const content = this.classList.contains("day-slide") ? this.firstElementChild?.getAttribute("data-day") : null;
    return { height: content ? heights[content] : 0, width: 0, top: 0, left: 0, right: 0, bottom: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
  });
});
afterEach(() => vi.unstubAllGlobals());

function Days() {
  const days = Object.keys(heights);
  const [day, setDay] = useState(days[0]);
  return (
    <DayCarousel days={days} value={day} onPick={setDay} pill={(d) => d.slice(8)} name={(d) => `Day ${d.slice(8)}`}>
      {(d) => <div data-day={d}>Plans for {d}</div>}
    </DayCarousel>
  );
}

const track = () => document.querySelector<HTMLElement>(".day-track")!;

describe("the day carousel", () => {
  it("is as tall as the day in view, and follows it from day to day", async () => {
    render(<Days />);
    expect(track().style.height).toBe("200px");

    await userEvent.setup().click(screen.getByRole("button", { name: "Next day" }));
    expect(track().style.height).toBe("560px");
    expect(screen.getByText(/2 of 3/)).toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole("button", { name: "12" }));
    expect(track().style.height).toBe("320px");
  });

  it("grows and shrinks as the day's content does", async () => {
    render(<Days />);
    expect(track().style.height).toBe("200px");
    heights["2026-11-10"] = 410;
    act(() => watchers.forEach((notify) => notify()));
    expect(track().style.height).toBe("410px");
    heights["2026-11-10"] = 200;
  });

  it("keeps every day on the page, each its own slide, with no inner scrolling box", () => {
    render(<Days />);
    expect(screen.getAllByRole("group", { name: /^Day \d+, \d of 3$/ })).toHaveLength(3);
    expect(document.querySelector(".more-below")).toBeNull();
    expect(screen.getByRole("button", { name: "Previous day" })).toBeDisabled();
  });
});
