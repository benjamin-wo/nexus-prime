import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import type { Money } from "../api";
import { Button, Figure, Row, RowList } from "../components/ui";
import { formatChange, formatMoney } from "../format";
import { healthApi, healthKey } from "../health/api";
import { inUnit } from "../health/bodyFormat";
import { useWeight, useWeightUnit } from "../health/bodyHooks";
import type {
  BudgetsFigures,
  OutlookFigures,
  PortfolioFigures,
  RecordsFigures,
  SpendingFigures,
  TodayFigures,
  TripFigures,
  WeightFigures,
  WorkoutFigures,
} from "./types";

// One small component per kind of view, from Paper's blocks only: Figure, Row and Button, with a tiny chart
// where it adds something. The focus view is a little larger (a big figure, more rows); the others are compact.
// Figures are never worked out here: they are what the server sent.

export type KindProps<T> = { figures: T; focus: boolean; open: () => void };

const money = (value: Money | null | undefined) => (value ? formatMoney(value) : "—");
const upper = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const group = (v: string) => Math.round(Number(v)).toLocaleString("en-US");
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The headline figure: a full one for the focus view, a small one for the rest. */
function Headline({ focus, label, value, extra }: { focus: boolean; label: string; value: string; extra?: ReactNode }) {
  return <Figure size={focus ? "lg" : "sm"} label={label} value={value} extra={extra} />;
}

/** A line of values as a sparkline: marks only, the words next to it say what it shows. */
function Spark({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1;
  const points = values.map((v, i) => `${((i / (values.length - 1)) * 100).toFixed(1)},${(22 - ((v - lo) / span) * 20).toFixed(1)}`).join(" ");
  return (
    <svg className="vc-spark" viewBox="0 0 100 24" preserveAspectRatio="none" role="img" aria-label={label}>
      <polyline points={points} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** Money in against money out, as two bars to one scale. */
function InOut({ received, spent }: { received: Money | null; spent: Money | null }) {
  const a = Number(received?.amount ?? 0);
  const b = Number(spent?.amount ?? 0);
  const top = Math.max(a, b);
  if (top <= 0) return null;
  return (
    <div className="vc-inout" role="img" aria-label={`Received ${money(received)}, spent ${money(spent)}`}>
      <span className="vc-bar-line">
        <span className="vc-bar-label">In · {money(received)}</span>
        <span className="vc-in" style={{ width: `${(a / top) * 100}%` }} />
      </span>
      <span className="vc-bar-line">
        <span className="vc-bar-label">Out · {money(spent)}</span>
        <span className="vc-out" style={{ width: `${(b / top) * 100}%` }} />
      </span>
    </div>
  );
}

export function OutlookCard({ figures: f, focus }: KindProps<OutlookFigures>) {
  return (
    <>
      <Headline focus={focus} label={f.shortfall ? "Short at month end" : "Left at month end"} value={money(f.shortfall ?? f.overall)} />
      <InOut received={f.received} spent={f.spent} />
      <RowList aria-label="This month">
        <Row title="Received" trailing={money(f.received)} />
        <Row title="Spent" trailing={money(f.spent)} />
        {focus && f.headroom && <Row title="Room to spare" trailing={money(f.headroom)} />}
        {focus && f.shortfall && <Row title="Short by" trailing={<span className="error-text">{money(f.shortfall)}</span>} />}
      </RowList>
    </>
  );
}

export function BudgetsCard({ figures: f, focus }: KindProps<BudgetsFigures>) {
  const rows = f.budgets.slice(0, focus ? 6 : 3);
  if (f.count === 0) return <p className="muted">No budgets set for this month.</p>;
  return (
    <RowList aria-label="Budgets">
      {rows.map((b) => (
        <Row
          key={b.name}
          title={b.name}
          sub={`${money(b.spent)} of ${money(b.limit)}`}
          trailing={b.percent >= 100 ? <span className="error-text">{b.percent}% used</span> : `${b.percent}% used`}
        />
      ))}
      {f.count > rows.length && <Row title={`${f.count - rows.length} more`} sub={f.over > 0 ? `${plural(f.over, "budget")} over in all` : undefined} />}
    </RowList>
  );
}

const SWATCHES = ["sw-1", "sw-2", "sw-3", "sw-4"];

export function SpendingCard({ figures: f, focus }: KindProps<SpendingFigures>) {
  const total = f.categories.reduce((sum, c) => sum + Number(c.total?.amount ?? 0), 0);
  const rows = f.categories.slice(0, focus ? 5 : 3);
  return (
    <>
      <Headline focus={focus} label="Spent" value={money(f.spent)} extra={plural(f.count, "entry", "entries")} />
      {total > 0 && (
        <div className="split-bar vc-split" aria-hidden="true">
          {f.categories.map((c, i) => (
            <span key={c.name} className={SWATCHES[i] ?? "rest"} style={{ flexGrow: (Number(c.total?.amount ?? 0) / total) * 100 }} />
          ))}
        </div>
      )}
      <RowList aria-label="Spending by category">
        {rows.map((c, i) => (
          <Row key={c.name} title={<><span className={`swatch ${SWATCHES[i] ?? "rest"}`} aria-hidden="true" /> {c.name}</>} trailing={money(c.total)} />
        ))}
      </RowList>
    </>
  );
}

export function TripBudgetCard({ figures: f, focus }: KindProps<TripFigures>) {
  if (!f.budget) return <Row title="No budget set" sub={`Spent ${money(f.spent)}`} />;
  return (
    <>
      <Headline focus={focus} label="Left in the budget" value={money(f.left)} extra={f.percent !== null ? `${f.percent}% spent` : undefined} />
      <RowList aria-label="Trip money">
        <Row title="Budget" trailing={money(f.budget)} />
        <Row title="Spent" trailing={money(f.spent)} />
        {focus && f.to_spend && <Row title="Still to spend after bookings" trailing={money(f.to_spend)} />}
      </RowList>
    </>
  );
}

export function PortfolioCard({ figures: f, focus }: KindProps<PortfolioFigures>) {
  if (f.holdings === 0) return <p className="muted">No holdings yet.</p>;
  return (
    <>
      <Headline focus={focus} label="Value" value={money(f.value)} extra={plural(f.holdings, "holding")} />
      <RowList aria-label="Portfolio">
        {f.day_change && <Row title="Today" trailing={formatChange(f.day_change)} />}
        {f.gain && <Row title="Gain or loss" trailing={formatChange(f.gain)} />}
        {focus && f.cost && <Row title="Cost" trailing={money(f.cost)} />}
      </RowList>
    </>
  );
}

function workoutLine(w: WorkoutFigures): { title: string; sub?: string } {
  switch (w.state) {
    case "open":
      return { title: "Workout in progress", sub: "Pick up where you left off" };
    case "planned":
      return { title: w.routine ?? "Workout planned", sub: w.exercises ? plural(w.exercises, "exercise") : undefined };
    case "suggested":
      return {
        title: w.focus ? `Suggested: ${w.focus}` : "Suggested workout",
        sub: [w.exercises ? plural(w.exercises, "exercise") : null, w.minutes ? `about ${w.minutes} min` : null].filter(Boolean).join(" · ") || undefined,
      };
    default:
      return { title: "Rest day" };
  }
}

export function TodayCard({ figures: f, focus }: KindProps<TodayFigures>) {
  // Numbers-free mode: the server leaves the energy and protein out, and the card says so in words.
  const numbers = f.kcal != null;
  return (
    <RowList aria-label="Your day">
      <Row title="Meals" trailing={f.meals === 0 ? "None yet" : `${f.meals} logged`} />
      {numbers && (
        <Row
          title="Energy so far"
          sub={f.kcal_target ? `of about ${group(f.kcal_target)} kcal` : "A rough guide"}
          trailing={<span className="health-fig">about {group(f.kcal as string)} kcal</span>}
        />
      )}
      {numbers && focus && f.protein_g != null && <Row title="Protein so far" trailing={<span className="health-fig">about {group(f.protein_g)} g</span>} />}
      {f.workout && <Row title={workoutLine(f.workout).title} sub={workoutLine(f.workout).sub} />}
    </RowList>
  );
}

export function WeightCard({ figures: f, focus }: KindProps<WeightFigures>) {
  const unit = useWeightUnit();
  // The trend's points are the page's own read, shared through the cache; none in numbers-free mode.
  const weight = useWeight();
  const points = f.hidden ? [] : (weight.data?.points ?? []).map((p) => Number(p.trend_kg));
  if (f.hidden || !f.trend_kg) {
    return (
      <RowList aria-label="Weight trend">
        <Row title="Trend" trailing={upper(f.trend_words)} />
      </RowList>
    );
  }
  return (
    <>
      <Headline
        focus={focus}
        label="Trend weight"
        value={`${inUnit(f.trend_kg, unit)} ${unit}`}
        extra={[f.trend_words, f.kg_a_week ? `${inUnit(f.kg_a_week, unit)} ${unit} a week` : null].filter(Boolean).join(" · ")}
      />
      <Spark values={points} label={`Weight trend, ${f.trend_words}`} />
    </>
  );
}

export function WorkoutCard({ figures: f, open }: KindProps<WorkoutFigures>) {
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const line = workoutLine(f);
  const resume = f.state === "open";
  // Start is the page's own: today's routine (or none) through the same call, then the Gym page shows it.
  async function start() {
    setBusy(true);
    setError(null);
    try {
      if (f.state === "planned") {
        const today = await client.fetchQuery({ queryKey: [...healthKey.all, "today"], queryFn: healthApi.today, staleTime: 0 });
        if (!today.in_progress) await healthApi.startWorkout(today.routine?.id ?? null);
        await client.invalidateQueries({ queryKey: healthKey.all });
      }
      open();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the workout");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <RowList aria-label="Workout">
        <Row title={line.title} sub={line.sub} />
      </RowList>
      {f.state !== "rest" && (
        <Button size="sm" variant="primary" disabled={busy} onClick={() => void start()}>
          {resume ? "Resume" : "Start"}
        </Button>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

export function RecordsCard({ figures: f, focus }: KindProps<RecordsFigures>) {
  const unit = useWeightUnit();
  if (f.records.length === 0) return <p className="muted">No records yet. Finish a workout with weights to see them.</p>;
  return (
    <RowList aria-label="Records">
      {f.records.slice(0, focus ? 5 : 3).map((r) => (
        <Row
          key={r.exercise}
          title={r.exercise}
          sub={plural(r.sessions, "session")}
          trailing={r.heaviest_kg ? <span className="health-fig">{`${inUnit(r.heaviest_kg, unit)} ${unit}`}</span> : undefined}
        />
      ))}
    </RowList>
  );
}

export function TripsCard({ open }: { open: () => void }) {
  return (
    <RowList aria-label="Trips">
      <Row title="All your trips" onClick={open} />
    </RowList>
  );
}
