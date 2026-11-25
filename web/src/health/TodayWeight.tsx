import { useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button, Section } from "../components/ui";
import { inUnit } from "./bodyFormat";
import { useWeight, useWeightUnit } from "./bodyHooks";
import { TrendSheet } from "./WeightTrend";
import { WeightSheet } from "./WeightSheet";

const upper = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Weight as one line ("82.4 kg, slowly down"), a small Log weight button, and the full trend behind See trend. */
export function TodayWeight() {
  const weight = useWeight();
  const unit = useWeightUnit();
  const [sheet, setSheet] = useState<"log" | "trend" | null>(null);
  const w = weight.data;
  const line = !w ? null : w.hidden ? upper(w.trend_words) : w.trend_kg ? `${inUnit(w.trend_kg, unit)} ${unit}, ${w.trend_words}` : null;
  return (
    <Section
      id="home-weight"
      title="Weight"
      action={
        <Button variant="text" onClick={() => setSheet("log")}>
          Log weight
        </Button>
      }
    >
      {weight.isError ? (
        <LoadError message="Couldn't load your weight." query={weight} />
      ) : !w ? (
        <p className="state">Loading…</p>
      ) : (
        <p>
          <span className="health-fig">{line ?? "No weigh-ins yet."}</span>{" "}
          {line && (
            <Button size="sm" variant="text" onClick={() => setSheet("trend")}>
              See trend
            </Button>
          )}
        </p>
      )}
      {sheet === "log" && <WeightSheet unit={unit} hidden={w?.hidden ?? false} onClose={() => setSheet(null)} />}
      {sheet === "trend" && <TrendSheet onClose={() => setSheet(null)} />}
    </Section>
  );
}
