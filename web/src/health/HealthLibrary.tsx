import { lazy, Suspense, useCallback, useState } from "react";

import { Toast } from "../components/Toast";
import type { Exercise } from "./api";
import { ExerciseSearch } from "./ExerciseSearch";
import { HealthGate } from "./HealthGate";
import { Section } from "../components/ui";

// The detail brings the body map and the photos; it is fetched when the first exercise is opened.
const ExerciseDetail = lazy(() => import("./ExerciseDetail").then((m) => ({ default: m.ExerciseDetail })));

export function HealthLibrary() {
  const [open, setOpen] = useState<Exercise | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const closeNotice = useCallback(() => setNotice(null), []);
  return (
    <HealthGate>
      <div className="page-head">
        <div>
          <h1>Library</h1>
          <p className="muted">Find an exercise, see how it is done and which muscles it works.</p>
        </div>
      </div>
      <Section id="library" title="Exercises">
        <ExerciseSearch onPick={setOpen} />
      </Section>
      {open && (
        <Suspense fallback={null}>
          <ExerciseDetail exercise={open} onClose={() => setOpen(null)} onAdded={setNotice} />
        </Suspense>
      )}
      {notice && <Toast message={notice} onClose={closeNotice} />}
    </HealthGate>
  );
}
