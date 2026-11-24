import { Row, RowList, Section } from "../components/ui";
import type { Day } from "./bodyApi";
import { gramsRange, kcalRange } from "./bodyFormat";
import { TargetsPaused } from "./SafetyNotes";

const group = (v: string) => Math.round(Number(v)).toLocaleString("en-US");

/** A day's total as a range, and what is left of the targets when there are some. In numbers-free mode there is none of it. */
export function DayTotals({ day, id = "day-totals" }: { day: Day; id?: string }) {
  if (day.hidden) return null;
  const { totals, remaining, targets_kcal: target } = day;
  const none = day.meals.length === 0;
  return (
    <Section id={id} title="The day so far">
      {none || !totals ? (
        <p className="muted">Nothing logged yet.</p>
      ) : (
        <RowList aria-label="Day totals">
          <Row title="Energy" trailing={<span className="health-fig">{kcalRange(totals)}</span>} />
          <Row title="Protein" trailing={<span className="health-fig">{gramsRange(totals, "protein_g")}</span>} />
        </RowList>
      )}
      {day.safety.suspended ? (
        <TargetsPaused safety={day.safety} />
      ) : (
        target &&
        remaining && (
          <RowList aria-label="Against your target">
            <Row title="Target" trailing={<span className="health-fig">about {group(target)} kcal</span>} />
            <Row title="Left today" trailing={<span className="health-fig">about {group(remaining.kcal)} kcal</span>} />
          </RowList>
        )
      )}
    </Section>
  );
}
