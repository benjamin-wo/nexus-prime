import { type ReactNode, useEffect, useRef, useState } from "react";

import { Button } from "./ui";

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
      <Button size="sm" className="foldaway" onClick={() => setOpen(true)}>
        {label}
      </Button>
    );
  }
  return <div ref={box}>{children}</div>;
}
