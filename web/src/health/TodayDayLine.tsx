import type { Day } from "./bodyApi";
import { gramsRange, kcalRange } from "./bodyFormat";
import { TargetsPaused } from "./SafetyNotes";

const group = (v: string) => Math.round(Number(v)).toLocaleString("en-US");
const upper = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "About 1,600 kcal · about 90 g protein so far. A rough guide." Nothing in numbers-free mode; a quiet note when targets are paused. */
export function TodayDayLine({ day }: { day: Day }) {
  if (day.hidden || !day.totals) return null;
  const { totals, remaining, targets_kcal: target } = day;
  return (
    <div className="health-stack">
      <p>{upper(`${kcalRange(totals)} · ${gramsRange(totals, "protein_g")} protein so far. A rough guide.`)}</p>
      {day.safety.suspended ? (
        <TargetsPaused safety={day.safety} />
      ) : (
        target && remaining && <p className="muted">{`About ${group(remaining.kcal)} kcal left of about ${group(target)} today.`}</p>
      )}
    </div>
  );
}
