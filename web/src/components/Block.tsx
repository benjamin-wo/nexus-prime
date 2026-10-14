import type { ReactNode } from "react";

/** A section whose title sits above its card, as a label for what's inside, with
 * an optional action (Details, Open, Edit) on the right of the title. */
export function Block({
  id,
  title,
  action,
  className,
  children,
}: {
  id: string;
  title: ReactNode;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className="block" aria-labelledby={id}>
      <div className="block-head">
        <h2 id={id}>{title}</h2>
        {action}
      </div>
      <div className={`card${className ? ` ${className}` : ""}`}>{children}</div>
    </section>
  );
}
