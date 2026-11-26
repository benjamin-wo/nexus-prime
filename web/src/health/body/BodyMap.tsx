import { MUSCLE_REGIONS, type Muscle } from "./muscles";
import { PATHS, VIEW_BOX, type Region, type View } from "./paths";

import "./body-map.css";

export interface BodyMapProps {
  /** Muscles the exercise mainly works: the solid accent. */
  primary?: readonly Muscle[];
  /** Muscles it also works: the same accent, lighter. A muscle in both lists is shown as primary. */
  secondary?: readonly Muscle[];
  /** Front, back or both side by side. */
  view?: View | "both";
  /** Height of one figure in px; by default it follows the stylesheet (22rem) and shrinks to fit. */
  size?: number;
  /** The accessible name; by default "Works chest; also triceps, shoulders". */
  label?: string;
  className?: string;
}

/** "Works chest; also triceps, shoulders" (the picture's text alternative). */
export function describeMuscles(primary: readonly Muscle[], secondary: readonly Muscle[]): string {
  const main = primary.length ? `Works ${primary.join(", ")}` : "";
  const also = secondary.length ? `${main ? "also" : "Also works"} ${secondary.join(", ")}` : "";
  return [main, also].filter(Boolean).join("; ") || "Body map, no muscles highlighted";
}

type State = "primary" | "secondary";

function regionStates(primary: readonly Muscle[], secondary: readonly Muscle[]): Map<Region, State> {
  const states = new Map<Region, State>();
  for (const m of secondary) for (const r of MUSCLE_REGIONS[m]) states.set(r, "secondary");
  for (const m of primary) for (const r of MUSCLE_REGIONS[m]) states.set(r, "primary");
  return states;
}

function Figure({ view, states, size }: { view: View; states: Map<Region, State>; size?: number }) {
  const regions = Object.keys(PATHS[view]) as Region[];
  const layer = (state: State | null) =>
    regions
      .filter((r) => (states.get(r) ?? null) === state)
      .flatMap((r) =>
        (PATHS[view][r] ?? []).map(([side, d], i) => (
          <path
            key={`${r}-${side}-${i}`}
            d={d}
            className={state ? `body-map-${state}` : "body-map-off"}
            data-region={r}
            data-state={state ?? "off"}
          />
        )),
      );
  // Neutral first, then the worked regions on top (a sub-region such as upperAbs overlaps its parent), and the
  // secondary layer as one group so its overlaps do not darken.
  return (
    <svg
      className="body-map-fig"
      viewBox={VIEW_BOX[view]}
      data-view={view}
      style={size ? { height: size } : undefined}
      aria-hidden="true"
      focusable="false"
    >
      <g aria-hidden="true">{layer(null)}</g>
      <g className="body-map-secondary-layer" aria-hidden="true">
        {layer("secondary")}
      </g>
      <g aria-hidden="true">{layer("primary")}</g>
    </svg>
  );
}

/** A muscle body map: the figure with the worked muscles highlighted. Presentational: the caller passes the muscles. */
export function BodyMap({ primary = [], secondary = [], view = "front", size, label, className }: BodyMapProps) {
  const states = regionStates(primary, secondary);
  const views: View[] = view === "both" ? ["front", "back"] : [view];
  return (
    <div
      role="img"
      aria-label={label ?? describeMuscles(primary, secondary)}
      className={className ? `body-map ${className}` : "body-map"}
      data-view={view}
    >
      {views.map((v) => (
        <Figure key={v} view={v} states={states} size={size} />
      ))}
    </div>
  );
}
