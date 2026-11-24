import { Sheet } from "../components/Sheet";
import { Button, Figure, Row, RowList } from "../components/ui";
import type { Exercise, Summary } from "./api";
import { formatDuration, formatVolume, PR_WORDS } from "./format";

/** After Finish: how long, how many sets, how much, and the records (the server's list), in plain words. */
export function FinishSheet({ summary, names, onClose }: { summary: Summary; names: Map<string, Exercise>; onClose: () => void }) {
  const records = Object.entries(summary.prs);
  return (
    <Sheet title="Workout finished" onClose={onClose} footer={<Button variant="primary" full onClick={onClose}>Done</Button>}>
      <div className="health-stack">
        <div className="mini-tiles health-tiles">
          <Figure size="sm" label="Duration" value={formatDuration(summary.duration_seconds)} />
          <Figure size="sm" label="Sets" value={String(summary.sets)} />
          <Figure size="sm" label="Volume" value={formatVolume(summary.volume_kg)} />
        </div>
        {records.length === 0 ? (
          <p className="muted">No new records this time.</p>
        ) : (
          <RowList aria-label="Records">
            {records.map(([id, kinds]) => (
              <Row key={id} title={`New best: ${names.get(id)?.name ?? "Exercise"}`} sub={kinds.map((k) => PR_WORDS[k]).join(", ")} />
            ))}
          </RowList>
        )}
      </div>
    </Sheet>
  );
}
