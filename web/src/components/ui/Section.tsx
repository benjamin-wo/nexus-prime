import type { ReactNode } from "react";

import "./section.css";

/**
 * A section (DESIGN.md §5 Surfaces): a heading row (an H2 and at most one action, a text button such as See all,
 * Open or Edit) over a soft block, `--bg-card` with no border and no shadow, that holds its rows. The section is
 * named by its heading (`aria-labelledby={id}`). Sections are never nested.
 *
 * The markup keeps the class names the app has always used (`.block`, `.block-head`, and `.card` on the body,
 * with `className` added to the body), so page CSS that targets them keeps working; section.css gives the body
 * its soft look.
 */
export interface SectionProps {
  /** The heading's id; the section is labelled by it. */
  id: string;
  title: ReactNode;
  /** One action at the right of the heading. */
  action?: ReactNode;
  /** Added to the body (the soft block), not the section. */
  className?: string;
  children: ReactNode;
}

export function Section({ id, title, action, className, children }: SectionProps) {
  return (
    <section className="block" aria-labelledby={id}>
      <div className="block-head">
        <h2 id={id}>{title}</h2>
        {action}
      </div>
      <div className={`card section-body${className ? ` ${className}` : ""}`}>{children}</div>
    </section>
  );
}
