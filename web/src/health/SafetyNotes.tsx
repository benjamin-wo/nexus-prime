import { useState } from "react";

import { Sheet } from "../components/Sheet";
import { Button, Row, RowList } from "../components/ui";
import type { SafetyNote, Signpost } from "./bodyApi";
import { checkInKey, checkInSeen, contactHref, markCheckInSeen, wantsCheckIn } from "./safety";

/** Places to get help, as the API sends them, with a link on the contact where it is an email or a number. */
export function Signposts({ items }: { items: Signpost[] }) {
  if (items.length === 0) return null;
  return (
    <RowList aria-label="Where to get help">
      {items.map((s) => {
        const href = contactHref(s.contact);
        return <Row key={s.name} title={s.name} sub={s.note} trailing={href ? <a href={href}>{s.contact}</a> : s.contact} />;
      })}
    </RowList>
  );
}

/** Where targets would be: a quiet note that they are paused, and the signposts. Plain text, not an alert. */
export function TargetsPaused({ safety }: { safety: Pick<SafetyNote, "signposts"> }) {
  return (
    <div className="health-note" aria-label="Targets are paused">
      <p>Targets are paused for now. Your food log still works.</p>
      <Signposts items={safety.signposts} />
    </div>
  );
}

/** The soft check-in: the API's text and the signposts, once. Closing marks it seen on this device. */
export function CheckIn({ safety, day }: { safety: SafetyNote | undefined; day: string }) {
  const key = wantsCheckIn(safety) ? checkInKey(safety, day) : "";
  const [closed, setClosed] = useState(false);
  if (!wantsCheckIn(safety) || closed || checkInSeen(key)) return null;
  const close = () => {
    markCheckInSeen(key);
    setClosed(true);
  };
  return (
    <Sheet title="Checking in" onClose={close} footer={<Button variant="primary" full onClick={close}>Close</Button>}>
      <div className="health-stack">
        {safety.check_in && <p>{safety.check_in}</p>}
        <Signposts items={safety.signposts} />
      </div>
    </Sheet>
  );
}
