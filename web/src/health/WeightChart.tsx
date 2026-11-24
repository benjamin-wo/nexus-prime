import type { WeightUnit } from "./api";
import type { TrendPoint } from "./bodyApi";
import { inUnit } from "./bodyFormat";
import { formatShortDate } from "../format";

/** The scale's readings as small dots and the trend as a line, oldest first (the Gym progress chart's approach: one svg).
 * The figures are in the rows under it, so the chart says none of them twice. Not drawn at all when numbers are hidden. */
export function WeightChart({ points, unit }: { points: TrendPoint[]; unit: WeightUnit }) {
  if (points.length < 2) return null;
  const width = 640;
  const height = 200;
  const pad = { top: 12, right: 12, bottom: 22, left: 52 };
  const inset = 10; // the dots start clear of the axis labels
  const conv = (kg: string) => Number(inUnit(kg, unit));
  const trend = points.map((p) => conv(p.trend_kg));
  const scale = points.map((p) => (p.scale_kg === null ? null : conv(p.scale_kg)));
  const all = [...trend, ...scale.filter((v): v is number => v !== null)];
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const span = hi - lo || 1;
  const x = (i: number) => pad.left + inset + (i / (points.length - 1)) * (width - pad.left - pad.right - 2 * inset);
  const y = (v: number) => pad.top + (1 - (v - lo) / span) * (height - pad.top - pad.bottom);
  const path = trend.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const at = points.length - 1;
  const when = (p: TrendPoint) => formatShortDate(`${p.date}T12:00:00Z`, "UTC");

  return (
    <figure className="health-chart">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Weight trend over ${points.length} days`}>
        {scale.map((v, i) => v !== null && <circle key={points[i].date} className="dot scale" cx={x(i)} cy={y(v)} r={2} />)}
        <path className="line" d={path} />
        <circle className="dot on" cx={x(at)} cy={y(trend[at])} r={4} />
        <text className="axis" x={pad.left - 4} y={y(hi) + 4} textAnchor="end">
          {hi.toFixed(1)}
        </text>
        <text className="axis" x={pad.left - 4} y={y(lo) + 4} textAnchor="end">
          {lo.toFixed(1)}
        </text>
        <text className="axis" x={pad.left + inset} y={height - 6}>
          {when(points[0])}
        </text>
        <text className="axis" x={width - pad.right} y={height - 6} textAnchor="end">
          {when(points[points.length - 1])}
        </text>
      </svg>
    </figure>
  );
}
