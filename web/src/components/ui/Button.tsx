import { type AnchorHTMLAttributes, type ButtonHTMLAttributes, forwardRef } from "react";
import { Link, type LinkProps } from "react-router-dom";

import "./button.css";

/**
 * A pill button (DESIGN.md §5 Buttons). The look lives in button.css; this only picks the classes, which are the
 * ones the app has always used (`btn btn-primary` and so on), so CSS, tests and e2e selectors keep working.
 *
 * - no variant: the plain `btn`, a `--bg-raised` pill with ink text (also cancel and back);
 * - `primary`: the filled `--accent` pill;
 * - `secondary`: `btn-soft`, the same `--bg-raised` pill, for an action that is not cancel;
 * - `text`: `btn-ghost`, `--accent-text` with no fill (a section's action, "Show all", icon buttons);
 * - `danger`: `btn-danger`, a `--rose-accent` text button, never filled.
 */
export type ButtonVariant = "primary" | "secondary" | "text" | "danger";
export type ButtonSize = "md" | "sm";

export interface ButtonLook {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** A full-width button at the foot of a form or a sheet: 52px tall. */
  full?: boolean;
  className?: string;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "btn-primary",
  secondary: "btn-soft",
  text: "btn-ghost",
  danger: "btn-danger",
};

/** The class list for a look: `btn`, then the variant, size and width classes, then the caller's own. */
export function buttonClass({ variant, size = "md", full, className }: ButtonLook = {}): string {
  return [
    "btn",
    variant && VARIANT_CLASS[variant],
    size === "sm" && "btn-small",
    full && "btn-full",
    className,
  ]
    .filter(Boolean)
    .join(" ");
}

export type ButtonProps = ButtonLook & ButtonHTMLAttributes<HTMLButtonElement>;

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant, size, full, className, type = "button", ...rest },
  ref,
) {
  return <button ref={ref} type={type} className={buttonClass({ variant, size, full, className })} {...rest} />;
});

/** A router link (`to`) or a plain link (`href`, e.g. one that opens outside the app) that looks like a button. */
export type ButtonLinkProps = ButtonLook &
  (
    | (Omit<LinkProps, "className"> & { href?: never })
    | (Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "className"> & { href: string; to?: never })
  );

export const ButtonLink = forwardRef<HTMLAnchorElement, ButtonLinkProps>(function ButtonLink(
  { variant, size, full, className, ...rest },
  ref,
) {
  const cls = buttonClass({ variant, size, full, className });
  if ("to" in rest && rest.to !== undefined) return <Link ref={ref} className={cls} {...(rest as LinkProps)} />;
  return <a ref={ref} className={cls} {...(rest as AnchorHTMLAttributes<HTMLAnchorElement>)} />;
});
