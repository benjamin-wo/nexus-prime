import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Research, type ResearchIdeasOut, type Run, type Trip, type TripDetail, type TripStop } from "../api";
import { Icon } from "../components/Icon";
import { formatRange, formatWholeMoney, formatShortDate } from "../format";
import { stopsOf } from "./TripBits";

const day = (iso: string) => formatShortDate(iso, "UTC");
/** Research prices are whole numbers in the currency named beside them: "SGD 4,602". */
const wholeMoney = (amount: string, currency: string) => formatWholeMoney({ amount, currency });
const wholeRange = (low: string, high: string, currency: string) =>
  formatRange({ amount: low, currency }, { amount: high, currency }, { whole: true });
const positive = (amount: string | null): amount is string => amount !== null && Number(amount) > 0;

/** A citation: the source's number, linking to the page it came from. */
function Cite({ id, research }: { id: number | null; research: Research }) {
  const source = research.sources.find((s) => s.id === id);
  if (!source) return null;
  return (
    <a className="cite" href={source.url} target="_blank" rel="noopener noreferrer nofollow" title={source.title}>
      [{source.id}]
    </a>
  );
}

/** The research's dates cut down to the trip's (ISO dates compare as text); null when none of
 * them fall inside the trip. */
export function clipDates(start: string, end: string, trip: Pick<Trip, "start" | "end">): { start: string; end: string } | null {
  const from = start > trip.start ? start : trip.start;
  const to = end < trip.end ? end : trip.end;
  return from <= to ? { start: from, end: to } : null;
}

/** What making room for the new stop does to one that was there. */
export type StopChange =
  | { name: string; kind: "ends"; on: string }
  | { name: string; kind: "starts"; on: string }
  | { name: string; kind: "splits"; endsOn: string; startsOn: string }
  | { name: string; kind: "goes" };

/** The stops as the server accepts them: dates in the trip, each ending no earlier than it starts,
 * in order (a stop may start on the one before's last day, not earlier), no two starting the same
 * day, and at most ten. */
function allowed(stops: TripStop[], trip: Pick<Trip, "start" | "end">): boolean {
  if (stops.length > 10) return false;
  return stops.every((s, i) => {
    if (!s.name || s.start > s.end || s.start < trip.start || s.end > trip.end) return false;
    const before = stops[i - 1];
    return !before || (s.start >= before.end && s.start > before.start);
  });
}

/** The stops to save so the trip also has `name` for the research's dates, clipped to the trip.
 * The new stop is kept whole and the ones it overlaps make room: one that starts before it ends on
 * its first day, one that ends after it starts on its last day, one that does both is split in two,
 * and one inside it goes. `changes` says what happened to each, for showing before saving. Null when
 * the dates don't fit the trip or the result would break the server's rules for stops. */
export function planStop(
  current: TripStop[],
  name: string,
  dates: { start: string; end: string },
  trip: Pick<Trip, "start" | "end">,
): { stops: TripStop[]; changes: StopChange[] } | null {
  const clipped = clipDates(dates.start, dates.end, trip);
  if (!clipped) return null;
  const { start: s, end: e } = clipped;
  const stops: TripStop[] = [];
  const changes: StopChange[] = [];
  for (const x of current) {
    const early = x.start < s;
    const late = x.end > e;
    if (x.end <= s || x.start >= e) {
      stops.push(x); // clear of the new stop, or only sharing its travel day
    } else if (early && late) {
      stops.push({ ...x, end: s }, { ...x, start: e });
      changes.push({ name: x.name, kind: "splits", endsOn: s, startsOn: e });
    } else if (early) {
      stops.push({ ...x, end: s });
      changes.push({ name: x.name, kind: "ends", on: s });
    } else if (late) {
      stops.push({ ...x, start: e });
      changes.push({ name: x.name, kind: "starts", on: e });
    } else {
      changes.push({ name: x.name, kind: "goes" });
    }
  }
  stops.push({ name: name.trim(), start: s, end: e });
  stops.sort((a, b) => a.start.localeCompare(b.start) || a.end.localeCompare(b.end));
  return allowed(stops, trip) ? { stops, changes } : null;
}

/** The stops to save, or null; see planStop. */
export const stopsWith = (current: TripStop[], name: string, dates: { start: string; end: string }, trip: Pick<Trip, "start" | "end">): TripStop[] | null =>
  planStop(current, name, dates, trip)?.stops ?? null;

const dayWord = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

/** One change in plain words: "Tokyo would end on Thu 8 Apr". */
export function changeText(c: StopChange): string {
  if (c.kind === "ends") return `${c.name} would end on ${dayWord(c.on)}`;
  if (c.kind === "starts") return `${c.name} would start on ${dayWord(c.on)}`;
  if (c.kind === "splits") return `${c.name} would end on ${dayWord(c.endsOn)} and start again on ${dayWord(c.startsOn)}`;
  return `${c.name} would be replaced`;
}

/** "Added 9 ideas to Japan in spring (2 were already there)". */
export function addedText(out: Pick<ResearchIdeasOut, "added" | "skipped">, where: string): string {
  const ideas = `${out.added} ${out.added === 1 ? "idea" : "ideas"}`;
  const there = out.skipped === 0 ? "" : out.skipped === 1 ? " (1 was already there)" : ` (${out.skipped} were already there)`;
  return `Added ${ideas} to ${where}${there}`;
}

type Step = { kind: "made"; trip: Trip } | { kind: "pick" } | { kind: "done"; trip: Trip; out: ResearchIdeasOut };

/** Saves the ticked areas' ideas on a trip: asks which trip (or whether to use the one just made),
 * then says what was added and offers the research's city as a stop. */
function AddIdeas({
  runId,
  research,
  areas,
  step,
  onStep,
  onLeave,
}: {
  runId: string;
  research: Research;
  areas: string[];
  step: Step;
  onStep: (step: Step | null) => void;
  onLeave: (trip: Trip) => void;
}) {
  const client = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stop, setStop] = useState<"offer" | "saved">("offer");
  const trips = useQuery({ queryKey: ["trips"], queryFn: () => api<Trip[]>("/travel/trips"), enabled: step.kind === "pick" });
  const open = (trips.data ?? []).filter((t) => t.status !== "finished");
  // The trip's stops, so the stop offer can say what it would change before anything is saved.
  const offered = step.kind === "done" && stop === "offer" && step.out.stop_suggestion !== null;
  const detail = useQuery({
    queryKey: ["trip", step.kind === "done" ? step.trip.id : ""],
    queryFn: () => api<TripDetail>(`/travel/trips/${step.kind === "done" ? step.trip.id : ""}`),
    enabled: offered,
  });

  // Move to the new question, so a screen reader hears it and the keyboard starts there.
  useEffect(() => heading.current?.focus(), [step.kind]);

  async function add(trip: Trip) {
    setBusy(true);
    setError(null);
    setStop("offer");
    try {
      const out = await api<ResearchIdeasOut>(`/travel/research/${runId}/ideas`, { method: "POST", body: { trip_id: trip.id, areas } });
      void client.invalidateQueries({ queryKey: ["trip", trip.id] });
      onStep({ kind: "done", trip, out });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add the ideas. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function addStop(trip: Trip, name: string) {
    setBusy(true);
    setError(null);
    try {
      const fresh = await api<TripDetail>(`/travel/trips/${trip.id}`);
      const plan = planStop(stopsOf(fresh), name, research, trip);
      if (!plan) {
        setError(`${name} can't be added as a stop without breaking the stops rules. Use Edit stops on the trip instead.`);
        return;
      }
      await api(`/travel/trips/${trip.id}/stops`, { method: "PUT", body: { stops: plan.stops } });
      void client.invalidateQueries({ queryKey: ["trip", trip.id] });
      setStop("saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the stop. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const alert = error && (
    <p className="error-text" role="alert">
      {error}
    </p>
  );

  if (step.kind === "made") {
    return (
      <section className="card research-add" aria-labelledby="research-add-title">
        <h2 id="research-add-title" ref={heading} tabIndex={-1}>
          Add the ideas from these areas to the trip too?
        </h2>
        <p className="muted">
          {areas.length === 1 ? "The things to do in 1 area" : `The things to do in ${areas.length} areas`} become ideas on {step.trip.destination}. Nothing is booked.
        </p>
        {alert}
        <div className="actions">
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void add(step.trip)}>
            {busy ? "Adding…" : "Add"}
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => onLeave(step.trip)}>
            Not now
          </button>
        </div>
      </section>
    );
  }

  if (step.kind === "pick") {
    return (
      <section className="card research-add" aria-labelledby="research-add-title">
        <h2 id="research-add-title" ref={heading} tabIndex={-1}>
          Which trip?
        </h2>
        {trips.isLoading && <p className="state">Loading…</p>}
        {trips.isError && (
          <p className="error-text" role="alert">
            Couldn't load your trips.
          </p>
        )}
        {trips.data && open.length === 0 && <p className="state">You have no upcoming trips to add to.</p>}
        {open.length > 0 && (
          <ul className="trip-pick">
            {open.map((t) => (
              <li key={t.id}>
                <button type="button" className="btn btn-soft trip-pick-btn" disabled={busy} onClick={() => void add(t)}>
                  <span>{t.destination}</span>
                  <span className="caption">
                    {day(t.start)} to {day(t.end)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {alert}
        <div className="actions">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => onStep(null)}>
            Cancel
          </button>
        </div>
      </section>
    );
  }

  const { trip, out } = step;
  const dates = clipDates(research.start, research.end, trip);
  const suggestion = out.stop_suggestion && dates ? out.stop_suggestion : null;
  const plan = suggestion && dates && detail.data ? planStop(stopsOf(detail.data), suggestion, dates, trip) : null;
  return (
    <section className="card research-add" aria-labelledby="research-add-title">
      <h2 id="research-add-title" ref={heading} tabIndex={-1}>
        Ideas added
      </h2>
      <p role="status">{addedText(out, trip.destination)}.</p>
      <p>
        <Link to={`/travel/trips/${trip.id}?tab=ideas`}>See them on the trip's Ideas tab</Link>
      </p>
      {suggestion && dates && stop === "offer" && (
        <div className="research-stop">
          <p>
            Add {suggestion} as a stop for {dayWord(dates.start)} to {dayWord(dates.end)}?
            {plan && plan.changes.length > 0 && ` ${plan.changes.map(changeText).join(". ")}.`}
          </p>
          {detail.isLoading && <p className="caption">Checking the trip's stops…</p>}
          {detail.data && !plan && <p className="caption">That would break the rules for stops. You can still add it with Edit stops on the trip.</p>}
          <div className="actions">
            <button type="button" className="btn btn-primary" disabled={busy || !plan} onClick={() => void addStop(trip, suggestion)}>
              {busy ? "Saving…" : `Add ${suggestion} as a stop`}
            </button>
          </div>
        </div>
      )}
      {suggestion && stop === "saved" && (
        <p role="status">
          Added {suggestion} as a stop. <Link to={`/travel/trips/${trip.id}`}>Open the trip</Link>
        </p>
      )}
      {alert}
    </section>
  );
}

/** Recent research runs, on the Trips page. */
export function ResearchList() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<Run[]>("/runs") });
  const mine = (runs.data ?? []).filter((r) => r.kind === "travel.research");
  if (mine.length === 0) return null;
  return (
    <section className="card quiet-list" aria-labelledby="research">
      <div className="card-head">
        <h2 id="research">Research</h2>
      </div>
      <ul className="quiet-rows">
        {mine.map((r) => (
          <li key={r.id} className="quiet-row">
            <Icon name={r.status === "done" ? "sparkle" : "find"} size={18} className="quiet-row-icon" />
            <span className="quiet-row-text">
              {r.status === "done" ? <Link to={`/travel/research/${r.id}`}>{r.title}</Link> : <span className="quiet-row-title">{r.title}</span>}
              <span className="caption">{r.status === "done" ? `Ready ${formatShortDate(r.finished_at ?? r.created_at)}` : r.progress}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** How the estimate sits against the budget, in plain words; null with no budget or no estimate.
 * "fits" when even the top of the range is within it, "over" when the whole range is past it, and
 * "could" when only the top of the range is. */
export function budgetLine(r: Pick<Research, "estimate_low" | "estimate_high" | "budget" | "home_currency">): { kind: "fits" | "could" | "over"; text: string } | null {
  if (!positive(r.estimate_low) || !positive(r.estimate_high) || !positive(r.budget)) return null;
  const budget = Number(r.budget);
  const of = `your budget of ${wholeMoney(r.budget, r.home_currency)}`;
  const by = (amount: number) => wholeMoney(String(Math.round(amount)), r.home_currency);
  if (Number(r.estimate_high) <= budget) return { kind: "fits", text: `Fits ${of}` };
  if (Number(r.estimate_low) <= budget) return { kind: "could", text: `Could go over ${of} by up to ${by(Number(r.estimate_high) - budget)}` };
  return { kind: "over", text: `Over ${of} by about ${by(Number(r.estimate_low) - budget)}` };
}

/** The first card: what the whole trip might cost, against the budget when there is one. */
export function ResearchSummary({ r }: { r: Research }) {
  const line = budgetLine(r);
  return (
    <section className="card money-summary" aria-labelledby="budget-card">
      <h2 id="budget-card" className="money-label">
        Estimated cost
      </h2>
      {positive(r.estimate_low) && positive(r.estimate_high) ? (
        <>
          <p className="money-figure">{wholeRange(r.estimate_low, r.estimate_high, r.home_currency)}</p>
          <p className="money-left">
            for {plural(r.nights, "night")}, {plural(r.travellers, "traveller")}
          </p>
        </>
      ) : (
        <p className="muted">Not enough sourced prices to estimate the whole trip.</p>
      )}
      {line && <p className={`money-left${line.kind === "fits" ? "" : " money-over"}`}>{line.text}</p>}
      {r.estimate_lines.length > 0 && (
        <ul className="research-lines">
          {r.estimate_lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
      {positive(r.set_aside) && positive(r.budget) && (
        <p className="money-left">
          Put aside {wholeMoney(r.set_aside, r.home_currency)} on each of the {r.paydays_left} paydays before then for a{" "}
          {wholeMoney(r.budget, r.home_currency)} budget.{" "}
          {r.fits === true && <span className="budget-state-ok-strong">It fits your cash flow.</span>}
          {r.fits === false && <span className="budget-state-over">That's tight for your cash flow.</span>}
        </p>
      )}
      <p className="money-note">Worked out from the prices below</p>
    </section>
  );
}

/** The pages the figures came from, folded away until asked for. */
export function ResearchSources({ r }: { r: Research }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="card research-sources" aria-labelledby="sources">
      <h2 id="sources" className="research-sources-h">
        <button type="button" className="research-sources-btn" aria-expanded={open} aria-controls="sources-list" onClick={() => setOpen(!open)}>
          <span>Sources · {r.sources.length}</span>
          <Icon name="chevron" size={18} className="research-chev" />
        </button>
      </h2>
      <div id="sources-list" className="research-sources-panel" hidden={!open}>
        <p className="caption">Other people's pages; nothing is booked</p>
        <ol className="sources">
          {r.sources.map((s) => (
            <li key={s.id} value={s.id}>
              <a href={s.url} target="_blank" rel="noopener noreferrer nofollow">
                {s.title}
              </a>{" "}
              <span className="caption">checked {day(s.checked_on)}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/** One trip's research: the estimated cost, when to go, costs with sources and where to stay. */
export function ResearchPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const research = useQuery({ queryKey: ["research", id], queryFn: () => api<Research>(`/travel/research/${id}`) });
  const [error, setError] = useState<string | null>(null);
  const [step, setStep] = useState<Step | null>(null);
  // Which areas' ideas to save: every area that has things to do, until the person unticks one.
  const [unticked, setUnticked] = useState<string[]>([]);
  const r = research.data;
  const withIdeas = (r?.areas ?? []).filter((a) => a.things.length > 0);
  const ticked = withIdeas.filter((a) => !unticked.includes(a.name)).map((a) => a.name);
  const toggle = (name: string, on: boolean) => setUnticked((was) => (on ? was.filter((n) => n !== name) : [...was, name]));

  async function makeTrip() {
    setError(null);
    try {
      const trip = await api<Trip>(`/travel/research/${id}/trip`, { method: "POST" });
      void client.invalidateQueries({ queryKey: ["trips"] });
      void client.invalidateQueries({ queryKey: ["research", id] });
      if (ticked.length > 0) setStep({ kind: "made", trip });
      else navigate(`/travel/trips/${trip.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make the trip");
    }
  }

  return (
    <div className="research-page">
      <header className="research-head">
        <Link className="btn btn-ghost research-back" to="/travel">
          <Icon name="chevron" size={16} className="icon-back" />
          Trips
        </Link>
        <div className="research-head-row">
          <div className="research-head-text">
            <h1 className="accent-serif research-title">{r ? r.destination : "Research"}</h1>
            {r && (
              <p className="research-meta">
                {day(r.start)} to {day(r.end)} · {plural(r.nights, "night")} · {plural(r.travellers, "traveller")}
              </p>
            )}
          </div>
          {r &&
            (r.trip_id ? (
              <Link className="btn btn-soft" to={`/travel/trips/${r.trip_id}`}>
                Open the trip
              </Link>
            ) : (
              <button type="button" className="btn btn-primary" onClick={() => void makeTrip()}>
                Make it a trip
              </button>
            ))}
        </div>
      </header>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {r && step && <AddIdeas runId={id} research={r} areas={ticked} step={step} onStep={setStep} onLeave={(trip) => navigate(`/travel/trips/${trip.id}`)} />}
      {research.isLoading && <p className="state">Loading…</p>}
      {research.isError && (
        <p className="error-text" role="alert">
          {research.error instanceof Error ? research.error.message : "Couldn't load that research."}
        </p>
      )}
      {r && (
        <>
          <ResearchSummary r={r} />
          <section className="card" aria-labelledby="when-to-go">
            <div className="card-head">
              <h2 id="when-to-go">When to go</h2>
            </div>
            {r.when_summary && <p className="research-lede">{r.when_summary}</p>}
            <ul className="research-rows">
              {r.when.map((p) => (
                <li key={p.text} className="research-row">
                  <span className="research-row-plain">
                    {p.text} <Cite id={p.source} research={r} />
                  </span>
                </li>
              ))}
            </ul>
          </section>
          <section className="card" aria-labelledby="costs">
            <div className="card-head">
              <h2 id="costs">Costs</h2>
              <span className="caption">As checked on each source's date</span>
            </div>
            {r.prices.length === 0 ? (
              <p className="state">No prices with a source were found.</p>
            ) : (
              <ul className="research-rows">
                {r.prices.map((p) => (
                  <li key={`${p.label}:${p.source}`} className="research-row">
                    <span className="research-row-main">
                      <span className="research-row-title">
                        {p.label} <Cite id={p.source} research={r} />
                      </span>
                      <span className="research-row-sub">per {p.per}</span>
                    </span>
                    <span className="research-row-amount">
                      <span className="num">{wholeRange(p.low, p.high, p.currency)}</span>
                      {positive(p.home_low) && positive(p.home_high) && p.currency !== r.home_currency && (
                        <span className="caption"> · {wholeRange(p.home_low, p.home_high, r.home_currency)}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section className="card" aria-labelledby="where-to-stay">
            <div className="card-head">
              <h2 id="where-to-stay">Where to stay</h2>
            </div>
            <div className="research-areas">
              {r.areas.map((a) => (
                <div key={a.name} className="area">
                  <div className="area-head">
                    <h3>
                      {a.name} <Cite id={a.source} research={r} />
                    </h3>
                    {a.things.length > 0 && (
                      <label className="area-save">
                        <input type="checkbox" checked={!unticked.includes(a.name)} onChange={(e) => toggle(a.name, e.target.checked)} aria-label={`Save its ideas from ${a.name}`} />
                        <span>Save its ideas</span>
                      </label>
                    )}
                  </div>
                  <p className="muted">{a.why}</p>
                  {a.things.length > 0 && <p className="caption">{a.things.join(" · ")}</p>}
                </div>
              ))}
            </div>
            {withIdeas.length > 0 && (
              <div className="research-actions">
                <button type="button" className="btn btn-soft" disabled={ticked.length === 0} onClick={() => setStep({ kind: "pick" })}>
                  Add to a trip…
                </button>
                <span className="caption">
                  {ticked.length === 0 ? "Tick an area to save its ideas." : `Saves the things to do in ${ticked.length} of ${withIdeas.length} areas as ideas. Nothing is booked.`}
                </span>
              </div>
            )}
            {r.getting_around && (
              <p className="research-around">
                <strong>Getting around:</strong> {r.getting_around} <Cite id={r.getting_around_source} research={r} />
              </p>
            )}
          </section>
          <ResearchSources r={r} />
        </>
      )}
    </div>
  );
}
