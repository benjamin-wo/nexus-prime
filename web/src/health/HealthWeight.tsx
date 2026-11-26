import { useState } from "react";

import { LoadError } from "../components/LoadError";
import { Button, Row, RowList, Section } from "../components/ui";
import { formatDate } from "../format";
import { inUnit } from "./bodyFormat";
import { useWeight, useWeightUnit } from "./bodyHooks";
import { HealthGate } from "./HealthGate";
import { WeightChart } from "./WeightChart";
import { WeightSheet } from "./WeightSheet";

function WeightBody() {
  const weight = useWeight();
  const unit = useWeightUnit();
  const [logging, setLogging] = useState(false);
  const w = weight.data;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Weight</h1>
          <p className="muted">Your trend, not any one day.</p>
        </div>
        <Button variant="primary" onClick={() => setLogging(true)}>
          Log weight
        </Button>
      </div>
      {weight.isError ? (
        <LoadError variant="page" message="Couldn't load your weight." query={weight} />
      ) : !w ? (
        <p className="state">Loading…</p>
      ) : (
        <Section id="trend" title="Trend">
          <p className="health-trend-words">{w.trend_words}</p>
          {w.hidden ? (
            <p className="caption">Numbers are hidden. You can change that in Settings, under Health data.</p>
          ) : (
            <>
              {w.points && w.points.length >= 2 ? <WeightChart points={w.points} unit={unit} /> : <p className="muted">Log a few weigh-ins to see a trend.</p>}
              <RowList aria-label="Weight">
                {w.trend_kg && <Row title="Trend" trailing={<span className="health-fig">{`${inUnit(w.trend_kg, unit)} ${unit}`}</span>} />}
                {w.last_weigh_in && (
                  <Row title="Last weigh-in" sub={formatDate(w.last_weigh_in.at)} trailing={<span className="health-fig">{`${inUnit(w.last_weigh_in.kg, unit)} ${unit}`}</span>} />
                )}
              </RowList>
              {w.rate_text && <p>{w.rate_text}</p>}
            </>
          )}
        </Section>
      )}
      {logging && <WeightSheet unit={unit} hidden={w?.hidden ?? false} onClose={() => setLogging(false)} />}
    </>
  );
}

export function HealthWeight() {
  return (
    <HealthGate>
      <WeightBody />
    </HealthGate>
  );
}
