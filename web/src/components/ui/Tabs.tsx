import { NavLink } from "react-router-dom";

import "./tabs.css";

/**
 * A department's sub-tabs (DESIGN.md §5 Department tabs): text on the ground, the current one ink and 600 with a
 * 4px accent dot under it, the rest muted. Each tab is a router link; the current one has `aria-current="page"`
 * (NavLink sets it). The nav is named by `label` ("Money pages"), so it can be found as a landmark.
 *
 * One tab is no choice: a caller shows the bar only when there are two or more.
 */
export interface TabItem {
  to: string;
  label: string;
  /** Current only on this exact path, not on the pages under it (a department's first tab). */
  end?: boolean;
}

export function Tabs({ label, items, className }: { label: string; items: TabItem[]; className?: string }) {
  return (
    <nav className={className ? `dept-tabs ${className}` : "dept-tabs"} aria-label={label}>
      {items.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) => `dept-tab${isActive ? " active" : ""}`}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
