import { type ButtonHTMLAttributes, forwardRef, type HTMLAttributes, type Ref } from "react";
import { Link, type LinkProps } from "react-router-dom";

import "./chip.css";

/**
 * A chip (DESIGN.md §5 Chips and filters): a pressable pill for a filter, a pick or a suggestion. Off it is an
 * outline with ink text; on (`pressed`, or the current one of a set) it is an ink fill, so colour never says "on".
 * `.day-pill` and `.ask-chip` share the same rules in chip.css, so pages that still write those classes look the same.
 *
 * With `to` it is a router link (a suggestion that goes somewhere); otherwise a button, `type="button"`.
 */
interface ChipOwn {
  /** On or off, for a chip that toggles or picks: sets `aria-pressed`. Leave it out for a chip that only acts. */
  pressed?: boolean;
  className?: string;
}

export type ChipButtonProps = ChipOwn & ButtonHTMLAttributes<HTMLButtonElement> & { to?: never };
export type ChipLinkProps = ChipOwn & Omit<LinkProps, "className">;
export type ChipProps = ChipButtonProps | ChipLinkProps;

const chipClass = (className?: string) => (className ? `chip-btn ${className}` : "chip-btn");

export const Chip = forwardRef<HTMLButtonElement | HTMLAnchorElement, ChipProps>(function Chip(props, ref) {
  if ("to" in props && props.to !== undefined) {
    const { pressed, className, ...rest } = props as ChipLinkProps;
    return (
      <Link
        ref={ref as Ref<HTMLAnchorElement>}
        className={chipClass(className)}
        aria-current={pressed ? "true" : undefined}
        {...rest}
      />
    );
  }
  const { pressed, className, type = "button", ...rest } = props as ChipButtonProps;
  return (
    <button
      ref={ref as Ref<HTMLButtonElement>}
      type={type}
      className={chipClass(className)}
      aria-pressed={pressed}
      {...rest}
    />
  );
});

/** A row of chips. It is a `group` (or a `radiogroup` for a pick of one), named by `aria-label` or `aria-labelledby`. */
export type ChipGroupProps = Omit<HTMLAttributes<HTMLDivElement>, "role"> & {
  role?: "group" | "radiogroup";
} & ({ "aria-label": string } | { "aria-labelledby": string });

export function ChipGroup({ role = "group", className, ...rest }: ChipGroupProps) {
  return <div role={role} className={className ? `chips ${className}` : "chips"} {...rest} />;
}
