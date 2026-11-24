import { useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { LoadError } from "../components/LoadError";
import { Toast } from "../components/Toast";
import { Button, Row, RowList, Section } from "../components/ui";
import { healthApi, healthKey, type Plan, type Routine } from "./api";
import { WEEKDAYS } from "./format";
import { HealthGate } from "./HealthGate";
import { useRoutines } from "./hooks";
import { PlanEditor } from "./PlanEditor";
import { RoutineEditor } from "./RoutineEditor";

function planRows(plan: Plan, routines: Routine[]) {
  const name = (id: string) => routines.find((r) => r.id === id)?.name ?? "A deleted routine";
  if (plan.kind === "weekly") {
    return Object.entries(plan.weekly)
      .sort(([a], [b]) => Number(a) - Number(b))
      .map(([d, id]) => ({ title: WEEKDAYS[Number(d)] ?? `Day ${d}`, trailing: name(id) }));
  }
  return plan.rotation.map((id, i) => ({ title: `Turn ${i + 1}`, trailing: name(id) }));
}

export function HealthRoutines() {
  const routines = useRoutines();
  const plan = useQuery({ queryKey: [...healthKey.all, "plan"], queryFn: healthApi.plan });
  const [editing, setEditing] = useState<Routine | "new" | null>(null);
  const [planning, setPlanning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const closeNotice = useCallback(() => setNotice(null), []);
  const list = routines.data ?? [];
  const rows = plan.data ? planRows(plan.data, list) : [];
  return (
    <HealthGate>
      <div className="page-head">
        <div>
          <h1>Routines</h1>
          <p className="muted">The workouts you repeat, and which one is on for today.</p>
        </div>
      </div>
      <Section
        id="routines"
        title="Your routines"
        action={
          <Button variant="text" onClick={() => setEditing("new")}>
            New routine
          </Button>
        }
      >
        {routines.isError ? (
          <LoadError message="Couldn't load your routines." query={routines} />
        ) : routines.isLoading ? (
          <p className="state">Loading…</p>
        ) : list.length === 0 ? (
          <p className="muted">No routines yet. Make one here, or add an exercise to a routine from the Library.</p>
        ) : (
          <RowList aria-label="Routines">
            {list.map((r) => (
              <Row
                key={r.id}
                title={r.name}
                sub={`${r.slots.length} ${r.slots.length === 1 ? "exercise" : "exercises"}`}
                label={`Edit ${r.name}`}
                onClick={() => setEditing(r)}
              />
            ))}
          </RowList>
        )}
      </Section>
      <Section
        id="plan"
        title="Plan"
        action={
          <Button variant="text" onClick={() => setPlanning(true)}>
            {plan.data ? "Edit plan" : "Set a plan"}
          </Button>
        }
      >
        {plan.isError ? (
          <LoadError message="Couldn't load your plan." query={plan} />
        ) : plan.isLoading ? (
          <p className="state">Loading…</p>
        ) : !plan.data || rows.length === 0 ? (
          <p className="muted">No plan. Choose weekly days or a rotation and Today will offer the right routine.</p>
        ) : (
          <RowList aria-label={plan.data.kind === "weekly" ? "Weekly plan" : "Rotation"}>
            {rows.map((r, i) => (
              <Row key={i} title={r.title} trailing={r.trailing} />
            ))}
          </RowList>
        )}
      </Section>
      {editing && (
        <RoutineEditor
          key={editing === "new" ? "new" : editing.id}
          routine={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={setNotice}
        />
      )}
      {planning && <PlanEditor plan={plan.data ?? null} routines={list} onClose={() => setPlanning(false)} onSaved={setNotice} />}
      {notice && <Toast message={notice} onClose={closeNotice} />}
    </HealthGate>
  );
}
