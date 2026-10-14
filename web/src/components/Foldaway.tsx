import { type ReactNode, useEffect, useRef, useState } from "react";

/** A secondary way in, kept out of the way until asked for: a small button that
 * opens into its form (focused on its first field), so an empty section shows one
 * line and one action, not a form. */
export function Foldaway({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) box.current?.querySelector<HTMLElement>("input, select, textarea")?.focus();
  }, [open]);
  if (!open) {
    return (
      <button type="button" className="btn btn-small foldaway" onClick={() => setOpen(true)}>
        {label}
      </button>
    );
  }
  return <div ref={box}>{children}</div>;
}
