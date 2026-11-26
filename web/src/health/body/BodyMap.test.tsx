import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BodyMap, describeMuscles } from "./BodyMap";
import { MUSCLE_REGIONS, MUSCLES } from "./muscles";
import { PATHS, VIEW_BOX } from "./paths";

const states = (container: HTMLElement, state: string) =>
  new Set([...container.querySelectorAll(`path[data-state="${state}"]`)].map((p) => p.getAttribute("data-region")));

describe("muscle mapping", () => {
  it("has the 17 free-exercise-db muscles", () => {
    expect(MUSCLES).toHaveLength(17);
    expect(Object.keys(MUSCLE_REGIONS).sort()).toEqual([...MUSCLES].sort());
  });

  it.each(MUSCLES)("%s maps to at least one path that exists", (muscle) => {
    const regions = MUSCLE_REGIONS[muscle];
    expect(regions.length).toBeGreaterThan(0);
    const drawn = regions.filter((r) => PATHS.front[r]?.length || PATHS.back[r]?.length);
    expect(drawn.length).toBeGreaterThan(0);
  });

  it("only names regions that are drawn in some view", () => {
    for (const regions of Object.values(MUSCLE_REGIONS))
      for (const r of regions) expect(PATHS.front[r] ?? PATHS.back[r]).toBeDefined();
  });
});

describe("BodyMap", () => {
  it("fills primary and secondary regions and leaves the rest neutral", () => {
    const { container } = render(<BodyMap primary={["chest"]} secondary={["triceps"]} view="front" />);
    expect(states(container, "primary")).toContain("chest");
    expect(states(container, "secondary")).toContain("triceps");
    expect(states(container, "off")).toContain("quadriceps");
    expect(states(container, "off")).not.toContain("chest");
  });

  it("shows a muscle named in both lists as primary", () => {
    const { container } = render(<BodyMap primary={["biceps"]} secondary={["biceps"]} />);
    expect(states(container, "primary")).toContain("biceps");
    expect(states(container, "secondary").size).toBe(0);
  });

  it("covers shoulders front and rear", () => {
    const front = render(<BodyMap primary={["shoulders"]} view="front" />);
    expect(states(front.container, "primary")).toContain("frontDeltoid");
    const back = render(<BodyMap primary={["shoulders"]} view="back" />);
    expect(states(back.container, "primary")).toContain("rearDeltoid");
  });

  it("is one image named by what it works, with the shapes hidden", () => {
    const { container } = render(<BodyMap primary={["chest"]} secondary={["triceps", "shoulders"]} />);
    expect(screen.getByRole("img", { name: "Works chest; also triceps, shoulders" })).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector("path")?.closest('[aria-hidden="true"]')).not.toBeNull();
  });

  it("describes the other combinations, and takes an explicit label", () => {
    expect(describeMuscles(["lats"], [])).toBe("Works lats");
    expect(describeMuscles([], ["calves"])).toBe("Also works calves");
    expect(describeMuscles([], [])).toBe("Body map, no muscles highlighted");
    render(<BodyMap primary={["neck"]} label="Neck stretch" />);
    expect(screen.getByRole("img", { name: "Neck stretch" })).toBeInTheDocument();
  });

  it("switches between front, back and both", () => {
    const views = (c: HTMLElement) => [...c.querySelectorAll("svg")].map((s) => s.getAttribute("data-view"));
    const front = render(<BodyMap />);
    expect(views(front.container)).toEqual(["front"]);
    expect(front.container.querySelector("svg")).toHaveAttribute("viewBox", VIEW_BOX.front);
    const back = render(<BodyMap view="back" />);
    expect(views(back.container)).toEqual(["back"]);
    expect(back.container.querySelector("svg")).toHaveAttribute("viewBox", VIEW_BOX.back);
    const both = render(<BodyMap view="both" primary={["glutes"]} />);
    expect(views(both.container)).toEqual(["front", "back"]);
  });

  it("highlights a back-only muscle only on the back", () => {
    const { container } = render(<BodyMap view="both" primary={["lower back"]} />);
    expect(container.querySelector('svg[data-view="front"] path[data-state="primary"]')).toBeNull();
    expect(container.querySelector('svg[data-view="back"] path[data-state="primary"]')).not.toBeNull();
  });
});
