import { LoadError } from "../components/LoadError";
import { Sheet } from "../components/Sheet";
import { Button, Row, RowList } from "../components/ui";
import { formatDate } from "../format";
import { inUnit } from "./bodyFormat";
import { useWeight, useWeightUnit } from "./bodyHooks";
import { WeightChart } from "./WeightChart";

/** The full weight trend: the chart, the rate and the words. Numbers hidden shows the words only. */
export function WeightTrend() {
  const weight = useWeight();
  const unit = useWeightUnit();
  const w = weight.data;
  if (weight.isError) return <LoadError message="Couldn't load your weight." query={weight} />;
  if (!w) return <p className="state">Loading…</p>;
  return (
    <div className="health-stack">
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
    </div>
  );
}

export function TrendSheet({ onClose }: { onClose: () => void }) {
  return (
    <Sheet title="Weight trend" onClose={onClose} footer={<Button variant="primary" full onClick={onClose}>Done</Button>}>
      <WeightTrend />
    </Sheet>
  );
}
