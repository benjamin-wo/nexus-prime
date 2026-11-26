import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Button, Chip, ChipGroup, Row, RowList } from "../components/ui";
import { LoadError } from "../components/LoadError";
import { type Exercise, EQUIPMENT, healthApi, healthKey, LEVELS } from "./api";
import { useDebounced } from "./hooks";
import { MUSCLES } from "./body/muscles";

const PAGE = 30;
const MAX = 200; // the API's own limit

/** A group of chips that picks one value or none. */
function Pick({ label, values, value, onChange }: { label: string; values: readonly string[]; value: string; onChange: (v: string) => void }) {
  return (
    <ChipGroup aria-label={label} className="health-chips">
      {values.map((v) => (
        <Chip key={v} pressed={value === v} onClick={() => onChange(value === v ? "" : v)}>
          {v}
        </Chip>
      ))}
    </ChipGroup>
  );
}

export const exerciseSub = (e: Exercise) => [e.primary_muscles.join(", "), e.equipment, e.level].filter(Boolean).join(" · ");

/**
 * The exercise library's search: a box, filter chips for muscle, equipment and level, and the results as rows, a page
 * at a time ("Show more" asks the API for more; it pages by limit). Pressing a row calls `onPick`.
 */
export function ExerciseSearch({ onPick, pickLabel }: { onPick: (e: Exercise) => void; pickLabel?: (e: Exercise) => string }) {
  const [text, setText] = useState("");
  const [muscle, setMuscle] = useState("");
  const [equipment, setEquipment] = useState("");
  const [level, setLevel] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const search = useDebounced(text.trim());
  const filter = { text: search, muscle, equipment, level, limit };
  const found = useQuery({
    queryKey: [...healthKey.all, "exercises", filter],
    queryFn: () => healthApi.exercises(filter),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  });
  const reset = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setLimit(PAGE);
  };
  const list = found.data ?? [];
  return (
    <div className="health-search">
      <label className="field">
        <span className="sr-only">Search exercises</span>
        <input
          className="input"
          type="search"
          placeholder="Search exercises"
          aria-label="Search exercises"
          value={text}
          onChange={(e) => reset(setText)(e.target.value)}
        />
      </label>
      <Pick label="Muscle" values={MUSCLES} value={muscle} onChange={reset(setMuscle)} />
      <Pick label="Equipment" values={EQUIPMENT} value={equipment} onChange={reset(setEquipment)} />
      <Pick label="Level" values={LEVELS} value={level} onChange={reset(setLevel)} />
      {found.isError ? (
        <LoadError message="Couldn't load exercises." query={found} />
      ) : found.isLoading ? (
        <p className="state">Loading…</p>
      ) : list.length === 0 ? (
        <p className="muted">No exercise matches that.</p>
      ) : (
        <>
          <RowList aria-label="Exercises">
            {list.map((e) => (
              <Row key={e.id} title={e.name} sub={exerciseSub(e)} label={pickLabel?.(e)} onClick={() => onPick(e)} />
            ))}
          </RowList>
          {list.length >= limit && limit < MAX && (
            <Button variant="text" disabled={found.isFetching} onClick={() => setLimit((n) => Math.min(MAX, n + PAGE))}>
              Show more
            </Button>
          )}
        </>
      )}
    </div>
  );
}
