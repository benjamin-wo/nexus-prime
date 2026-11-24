import { Sheet } from "../components/Sheet";
import { Row, RowList } from "../components/ui";
import { formatDate } from "../format";
import type { Exercise, WorkoutDetail } from "./api";
import { byDone, formatDuration, formatSet, formatVolume, volumeKg } from "./format";

/** One finished workout: its sets by exercise. */
export function WorkoutDetailSheet({ workout, names, onClose }: { workout: WorkoutDetail; names: Map<string, Exercise>; onClose: () => void }) {
  const ids = [...new Set(byDone(workout.sets).map((s) => s.exercise_id))];
  const seconds = workout.finished_at ? Math.round((Date.parse(workout.finished_at) - Date.parse(workout.started_at)) / 1000) : null;
  return (
    <Sheet title={formatDate(workout.started_at)} onClose={onClose}>
      <div className="health-stack">
        <p className="muted">
          {[seconds === null ? "Not finished" : formatDuration(seconds), `${workout.sets.length} sets`, formatVolume(volumeKg(workout.sets))].join(" · ")}
        </p>
        {workout.note && <p>{workout.note}</p>}
        {ids.length === 0 ? (
          <p className="muted">No sets were logged.</p>
        ) : (
          <RowList aria-label="Exercises done">
            {ids.map((id) => (
              <Row
                key={id}
                title={names.get(id)?.name ?? "Exercise"}
                sub={
                  <span className="health-fig">
                    {byDone(workout.sets.filter((s) => s.exercise_id === id)).map((s) => formatSet(s)).join(", ")}
                  </span>
                }
              />
            ))}
          </RowList>
        )}
      </div>
    </Sheet>
  );
}
