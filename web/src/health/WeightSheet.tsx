import { useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";

import { Sheet } from "../components/Sheet";
import { Button } from "../components/ui";
import type { WeightUnit } from "./api";
import { healthKey } from "./api";
import { bodyApi } from "./bodyApi";

/** Log a weigh-in in the person's unit. Saved says so; in numbers-free mode it never echoes the number back. */
export function WeightSheet({ unit, hidden, onClose }: { unit: WeightUnit; hidden: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const valid = Number(value) > 0 && Number.isFinite(Number(value));

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await bodyApi.logWeight(value.trim(), unit);
      await client.invalidateQueries({ queryKey: healthKey.all });
      setSaved(hidden ? "Saved" : `Saved ${value.trim()} ${unit}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the weight");
    } finally {
      setBusy(false);
    }
  }

  if (saved) {
    return (
      <Sheet title="Log weight" onClose={onClose} footer={<Button variant="primary" full onClick={onClose}>Done</Button>}>
        <p role="status">{saved}</p>
      </Sheet>
    );
  }
  return (
    <Sheet
      title="Log weight"
      as="form"
      onSubmit={(e) => void save(e)}
      onClose={onClose}
      footer={
        <Button variant="primary" full type="submit" disabled={busy || !valid}>
          Save weight
        </Button>
      }
    >
      <label className="field">
        {`Weight (${unit})`}
        <input className="input health-fig" type="number" inputMode="decimal" step="any" min="1" value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  );
}
