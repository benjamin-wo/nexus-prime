import type { HTMLAttributes, MouseEventHandler, ReactNode } from "react";
import { Link } from "react-router-dom";

import "./row.css";

/**
 * Rows (DESIGN.md §5 Rows): a title and a muted sub-line on the left, a figure or a plain word right-aligned on the
 * right (tabular), and maybe a few small actions. At least 56px tall; rows in a `RowList` are divided by a
 * `--border-card` hairline, the last without one. No icon tile, no card, no badge.
 *
 * With `to` (a route), `href` (a plain link) or `onClick` the title, sub-line and trailing figure are one link or
 * button, so the whole row is pressable; `actions` stay outside it, as their own buttons.
 *
 * The page CSS that still writes `.money-rows` / `.money-row*` by hand shares these rules (row.css).
 */
export function RowList({ className, ...rest }: HTMLAttributes<HTMLUListElement>) {
  return <ul className={className ? `row-list ${className}` : "row-list"} {...rest} />;
}

export interface RowProps {
  title: ReactNode;
  /** One muted line under the title. */
  sub?: ReactNode;
  /** A figure or a plain word at the right, tabular. */
  trailing?: ReactNode;
  /** Small buttons at the end of the row, outside the row's own link. */
  actions?: ReactNode;
  /** A route: the row is a router link. */
  to?: string;
  /** A plain link (e.g. one that leaves the app). */
  href?: string;
  /** The row is a button. */
  onClick?: MouseEventHandler<HTMLButtonElement>;
  /** On the `li`. */
  className?: string;
}

export function Row({ title, sub, trailing, actions, to, href, onClick, className }: RowProps) {
  const body = (
    <>
      <span className="row-text">
        <span className="row-title">{title}</span>
        {sub != null && sub !== false && <span className="row-sub">{sub}</span>}
      </span>
      {trailing != null && trailing !== false && <span className="row-trailing">{trailing}</span>}
    </>
  );
  let line: ReactNode;
  if (to !== undefined) {
    line = (
      <Link className="row-line row-press" to={to}>
        {body}
      </Link>
    );
  } else if (href !== undefined) {
    line = (
      <a className="row-line row-press" href={href}>
        {body}
      </a>
    );
  } else if (onClick) {
    line = (
      <button type="button" className="row-line row-press" onClick={onClick}>
        {body}
      </button>
    );
  } else {
    line = <div className="row-line">{body}</div>;
  }
  return (
    <li className={className ? `row-item ${className}` : "row-item"}>
      {line}
      {actions != null && actions !== false && <span className="row-actions-end">{actions}</span>}
    </li>
  );
}
