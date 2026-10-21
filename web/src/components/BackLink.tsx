import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Icon } from "./Icon";

/** The way back from a page that sits inside another (Receipts by email, inside Settings). */
export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link className="back-link" to={to}>
      <Icon name="chevronLeft" size={18} />
      {children}
    </Link>
  );
}
