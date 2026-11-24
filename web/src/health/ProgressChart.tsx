import { type PointerEvent, useState } from "react";

import { formatShortDate } from "../format";
import type { ProgressPoint } from "./api";

/** The estimated one-rep max of each workout's best set, oldest first, as a line (the Trade plans chart's approach:
 * one svg, a hit area for the pointer, a caption that says the day under it). The rows under it carry the same figures. */
export function ProgressChart({ points, name }: { points: ProgressPoint[]; name: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;
  const width = 640;
  const height = 200;
  const pad = { top: 12, right: 12, bottom: 22, left: 44 };
  const values = points.map((p) => Number(p.e1rm_kg));
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const x = (i: number) => pad.left + (i / (points.length - 1)) * (width - pad.left - pad.right);
  const y = (v: number) => pad.top + (1 - (v - lo) / span) * (height - pad.top - pad.bottom);
  const path = values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");

  function move(event: PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / box.width;
    setHover(Math.max(0, Math.min(points.length - 1, Math.round(ratio * (points.length - 1)))));
  }

  const at = hover ?? points.length - 1;
  const point = points[at];
  return (
    <figure className="health-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${name}: estimated one-rep max over ${points.length} workouts`}>
        <path className="line" d={path} />
        {values.map((v, i) => (
          <circle key={points[i].workout_id} className={i === at ? "dot on" : "dot"} cx={x(i)} cy={y(v)} r={i === at ? 4 : 2.5} />
        ))}
        <text className="axis" x={pad.left - 6} y={y(hi) + 4} textAnchor="end">
          {Math.round(hi)}
        </text>
        <text className="axis" x={pad.left - 6} y={y(lo) + 4} textAnchor="end">
          {Math.round(lo)}
        </text>
        <text className="axis" x={pad.left} y={height - 6}>
          {formatShortDate(points[0].at)}
        </text>
        <text className="axis" x={width - pad.right} y={height - 6} textAnchor="end">
          {formatShortDate(points[points.length - 1].at)}
        </text>
        <rect className="hit" x={pad.left} y={0} width={width - pad.left - pad.right} height={height} onPointerMove={move} onPointerLeave={() => setHover(null)} />
      </svg>
      <figcaption className="caption" aria-live="polite">
        <strong className="health-fig">{Math.round(Number(point.e1rm_kg))} kg</strong> estimated max on {formatShortDate(point.at)}
      </figcaption>
    </figure>
  );
}
