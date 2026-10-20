import type { ReactNode } from "react";

import type { PriceKind } from "../api";
import { priceWhen } from "../format";

/** When a price is from, as a muted caption; a live price has a small emerald dot. Anything
 * passed as children follows after a dot. */
export function PriceWhen({
  kind,
  at,
  day,
  children,
}: {
  kind: PriceKind | null;
  at: string | null;
  day: string | null;
  children?: ReactNode;
}) {
  return (
    <span className="caption price-when">
      {kind === "live" && <span className="live-dot" aria-hidden="true" />}
      <span>
        {priceWhen(kind, at, day)}
        {children && <> · {children}</>}
      </span>
    </span>
  );
}
