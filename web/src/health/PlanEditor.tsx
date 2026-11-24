import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Sheet } from "../components/Sheet";
import { Button, Chip, ChipGroup, Row, RowList } from "../components/ui";
import { type Plan, healthApi, healthKey, type Routine } from "./api";
import { WEEKDAYS } from "./format";
import { move } from "./RoutineEditor";

/** The training plan: a routine on set weekdays, or the routines in turn. */
export function PlanEditor({ plan, routines, onClose, onSaved }: { plan: Plan | null; routines: Routine[]; onClose: () => void; onSaved: (message: string) => void }) {
  const client = useQueryClient();
  const [kind, setKind] = useState<Plan["kind"]>(plan?.kind ?? "weekly");
  const [weekly, setWeekly] = useState<Record<string, string>>(plan?.weekly ?? {});
  const [rotation, setRotation] = useState<string[]>(plan?.rotation ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameOf = (id: string) => routines.find((r) => r.id === id)?.name ?? "A deleted routine";

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const days = Object.entries(weekly).filter(([, id]) => id);
      await healthApi.savePlan({
        kind,
        weekly: kind === "weekly" ? Object.fromEntries(days.map(([d, id]) => [Number(d), id])) : {},
        rotation: kind === "rotation" ? rotation : [],
      });
      await client.invalidateQueries({ queryKey: healthKey.all });
      onSaved("Saved your plan.");
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the plan");
      setBusy(false);
    }
  }

  return (
    <Sheet
      as="form"
      title="Training plan"
      onClose={onClose}
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy) void save();
      }}
      footer={
        <Button variant="primary" full type="submit" disabled={busy}>
          Save plan
        </Button>
      }
    >
      <div className="health-stack">
        <ChipGroup role="radiogroup" aria-label="How the plan runs">
          <Chip pressed={kind === "weekly"} role="radio" aria-checked={kind === "weekly"} onClick={() => setKind("weekly")}>
            Weekly days
          </Chip>
          <Chip pressed={kind === "rotation"} role="radio" aria-checked={kind === "rotation"} onClick={() => setKind("rotation")}>
            Rotation
          </Chip>
        </ChipGroup>
        {routines.length === 0 && <p className="muted">Make a routine first, then plan it here.</p>}
        {kind === "weekly" ? (
          <RowList aria-label="Routine for each weekday">
            {WEEKDAYS.map((day, d) => (
              <Row
                key={day}
                title={day}
                trailing={
                  <select
                    className="input health-select"
                    aria-label={`Routine on ${day}`}
                    value={weekly[d] ?? ""}
                    onChange={(e) => setWeekly((w) => ({ ...w, [d]: e.target.value }))}
                  >
                    <option value="">Rest day</option>
                    {routines.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                }
              />
            ))}
          </RowList>
        ) : (
          <>
            <p className="muted">Nexus offers the next routine in this order after each workout.</p>
            {rotation.length > 0 && (
              <RowList aria-label="Rotation order">
                {rotation.map((id, i) => (
                  <Row
                    key={`${id}-${i}`}
                    title={nameOf(id)}
                    sub={`Turn ${i + 1} of ${rotation.length}`}
                    actions={
                      <>
                        <Button size="sm" variant="text" disabled={i === 0} aria-label={`Move ${nameOf(id)} up`} onClick={() => setRotation((r) => move(r, i, -1))}>
                          Up
                        </Button>
                        <Button size="sm" variant="text" disabled={i === rotation.length - 1} aria-label={`Move ${nameOf(id)} down`} onClick={() => setRotation((r) => move(r, i, 1))}>
                          Down
                        </Button>
                        <Button size="sm" variant="danger" aria-label={`Remove ${nameOf(id)} from the rotation`} onClick={() => setRotation((r) => r.filter((_, j) => j !== i))}>
                          Remove
                        </Button>
                      </>
                    }
                  />
                ))}
              </RowList>
            )}
            <label className="field">
              Add a routine to the rotation
              <select
                className="input"
                value=""
                onChange={(e) => e.target.value && setRotation((r) => [...r, e.target.value])}
              >
                <option value="">Choose a routine</option>
                {routines.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
          </>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </div>
    </Sheet>
  );
}
