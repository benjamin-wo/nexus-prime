import type { HTMLAttributes, ReactNode } from "react";

import { CountUp } from "../../motion";

import "./figure.css";

/**
 * A figure (DESIGN.md §3 Figure, §5): a small label, the amount in Bricolage (tabular, counting up the first time
 * it is seen, at once for reduced motion) and an optional muted line under it.
 *
 * - `lg` (the default) is a headline figure of its own: `.tile`, with `.caption`, `.value` and `.extra`;
 * - `sm` sits beside others in a row of small figures (`.mini-tiles`): `.mini-tile`, with `.caption` and `.mini-value`.
 *
 * Those are the class names the app has always used, so page CSS that targets them keeps working. The figure
 * sizes to its box (container query) and, if it must, wraps between the currency and the number.
 */
export type FigureSize = "lg" | "sm";

export type FigureProps = Omit<HTMLAttributes<HTMLElement>, "children"> & {
  label: ReactNode;
  /** A formatted figure ("SGD 1,842.60", "71%"); a placeholder ("…") shows as it is. */
  value: string;
  extra?: ReactNode;
  size?: FigureSize;
  /** `section` for a figure that is a region of its own (named by `aria-label`). */
  as?: "div" | "section";
};

export function Figure({ label, value, extra, size = "lg", as: Tag = "div", className, ...rest }: FigureProps) {
  const base = size === "sm" ? "mini-tile" : "tile";
  return (
    <Tag className={className ? `${className} ${base}` : base} {...rest}>
      <span className="caption">{label}</span>
      <span className={size === "sm" ? "mini-value" : "value"}>
        <CountUp value={value} />
      </span>
      {extra != null && extra !== false && <span className={size === "sm" ? "caption" : "extra"}>{extra}</span>}
    </Tag>
  );
}
