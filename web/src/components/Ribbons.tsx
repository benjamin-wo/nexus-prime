import type React from "react";

/** Light ribbons drifting slowly behind the pages: bundles of fine strands sweeping
 * across the screen in the ember colours, with a soft glow, as on a landing page.
 * Purely decoration (hidden from screen readers, never in the way of a tap); they
 * hold still for reduced motion. */

// One bundle: strands fanned out around a sweeping curve across a 1600 x 1000 box.
function bundle(seed: number, count: number, from: [number, number], to: [number, number], bend: [number, number, number, number]) {
  const paths: string[] = [];
  for (let i = 0; i < count; i++) {
    const spread = (i - count / 2) * (14 + seed * 3);
    const wobble = Math.sin(i * 1.7 + seed) * 22;
    const [x0, y0] = from;
    const [x1, y1] = to;
    const [c1x, c1y, c2x, c2y] = bend;
    paths.push(
      `M${x0} ${y0 + spread * 0.4} C${c1x + wobble} ${c1y + spread}, ${c2x - wobble} ${c2y - spread * 0.8}, ${x1} ${y1 + spread * 0.5}`,
    );
  }
  return paths;
}

const MAIN = bundle(1, 22, [-100, 900], [1700, 180], [420, 980, 980, -40]);
const SECOND = bundle(2, 12, [-100, 620], [1700, 520], [520, 120, 1100, 980]);
const FAINT = bundle(3, 8, [200, 1100], [1700, -60], [700, 760, 1100, 300]);

const DEFS = (
  <defs>
    <linearGradient id="ribbon-ember" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stopColor="#7c2d12" stopOpacity="0" />
      <stop offset="0.35" stopColor="#f97316" stopOpacity="0.9" />
      <stop offset="0.6" stopColor="#fb923c" stopOpacity="1" />
      <stop offset="1" stopColor="#f59e0b" stopOpacity="0" />
    </linearGradient>
    <linearGradient id="ribbon-amber" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stopColor="#f59e0b" stopOpacity="0" />
      <stop offset="0.5" stopColor="#f59e0b" stopOpacity="0.7" />
      <stop offset="1" stopColor="#f97316" stopOpacity="0" />
    </linearGradient>
    <filter id="ribbon-glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="18" />
    </filter>
  </defs>
);

/** One layer of strands, drawn once. Its wrapper is what moves: the browser hands a
 * moving layer to the graphics chip as a finished picture, so drifting costs nothing
 * per frame, where moving shapes inside the SVG would redraw it (glow and all) each
 * frame. */
function Layer({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <div className={`ribbon ${className}`}>
      <svg viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice" focusable="false">
        {DEFS}
        {children}
      </svg>
    </div>
  );
}

export function Ribbons() {
  return (
    <div className="ribbons" aria-hidden="true">
      <Layer className="ribbon-faint">
        {FAINT.map((d, i) => (
          <path key={i} d={d} stroke="url(#ribbon-ember)" strokeWidth={0.6} fill="none" opacity={0.18} />
        ))}
      </Layer>
      <Layer className="ribbon-second">
        {SECOND.map((d, i) => (
          <path key={i} d={d} stroke="url(#ribbon-amber)" strokeWidth={0.9} fill="none" opacity={0.35 + (i % 4) * 0.1} />
        ))}
      </Layer>
      <Layer className="ribbon-main">
        <g filter="url(#ribbon-glow)" opacity="0.85">
          {MAIN.filter((_, i) => i % 3 === 0).map((d, i) => (
            <path key={i} d={d} stroke="url(#ribbon-ember)" strokeWidth="16" fill="none" />
          ))}
        </g>
        {MAIN.map((d, i) => (
          <path key={i} d={d} stroke="url(#ribbon-ember)" strokeWidth={i % 4 === 0 ? 2 : 1} fill="none" opacity={0.55 + (i % 5) * 0.1} />
        ))}
        {MAIN.filter((_, i) => i % 6 === 2).map((d, i) => (
          <path key={`bright-${i}`} d={d} stroke="#fdba74" strokeWidth="1.2" fill="none" opacity="0.7" />
        ))}
      </Layer>
      <div className="ribbons-veil" />
    </div>
  );
}
