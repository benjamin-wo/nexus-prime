import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, type Research, type Run, type Trip } from "../api";
import { formatShortDate } from "../format";

const day = (iso: string) => formatShortDate(iso, "UTC");
const whole = (amount: string) => Number(amount).toLocaleString(undefined, { maximumFractionDigits: 0 });

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

/** Recent research runs, on the Trips page. */
export function ResearchList() {
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<Run[]>("/runs") });
  const mine = (runs.data ?? []).filter((r) => r.kind === "travel.research");
  if (mine.length === 0) return null;
  return (
    <section className="card" aria-labelledby="research">
      <div className="card-head">
        <h2 id="research">Research</h2>
      </div>
      <ul className="feed">
        {mine.map((r) => (
          <li key={r.id} className="run-row">
            <span className="wrap">
              {r.status === "done" ? <Link to={`/travel/research/${r.id}`}>{r.title}</Link> : r.title}
              <br />
              <span className="caption">{r.status === "done" ? `Ready ${formatShortDate(r.finished_at ?? r.created_at)}` : r.progress}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** One trip's research: when to go, costs with sources, where to stay and the budget. */
export function ResearchPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const research = useQuery({ queryKey: ["research", id], queryFn: () => api<Research>(`/travel/research/${id}`) });
  const [error, setError] = useState<string | null>(null);
  const r = research.data;

  async function makeTrip() {
    setError(null);
    try {
      const trip = await api<Trip>(`/travel/research/${id}/trip`, { method: "POST" });
      void client.invalidateQueries({ queryKey: ["trips"] });
      navigate(`/travel/trips/${trip.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't make the trip");
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="caption">
            <Link to="/travel">Trips</Link>
          </p>
          <h1>{r ? r.destination : "Research"}</h1>
          {r && (
            <p className="muted">
              {day(r.start)} to {day(r.end)} · {r.nights} nights · {r.travellers} {r.travellers === 1 ? "traveller" : "travellers"}
            </p>
          )}
        </div>
        {r &&
          (r.trip_id ? (
            <Link className="btn" to={`/travel/trips/${r.trip_id}`}>
              Open the trip
            </Link>
          ) : (
            <button type="button" className="btn btn-primary" onClick={() => void makeTrip()}>
              Make it a trip
            </button>
          ))}
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {research.isLoading && <p className="state">Loading…</p>}
      {research.isError && (
        <p className="error-text" role="alert">
          {research.error instanceof Error ? research.error.message : "Couldn't load that research."}
        </p>
      )}
      {r && (
        <>
          <section className="card" aria-labelledby="budget-card">
            <div className="card-head">
              <h2 id="budget-card">Budget</h2>
              <span className="caption">Worked out from the prices below</span>
            </div>
            {r.estimate_low && r.estimate_high ? (
              <p>
                About{" "}
                <strong>
                  {whole(r.estimate_low)} to {whole(r.estimate_high)} {r.home_currency}
                </strong>{" "}
                for {r.travellers}.
              </p>
            ) : (
              <p className="muted">Not enough sourced prices to estimate the whole trip.</p>
            )}
            {r.estimate_lines.length > 0 && (
              <ul className="caption">
                {r.estimate_lines.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            )}
            {r.set_aside && r.budget && (
              <p>
                Put aside {whole(r.set_aside)} {r.home_currency} on each of the {r.paydays_left} paydays before then for a {whole(r.budget)}{" "}
                {r.home_currency} budget.{" "}
                {r.fits === true && <span className="budget-state-ok-strong">It fits your cash flow.</span>}
                {r.fits === false && <span className="budget-state-over">That's tight for your cash flow.</span>}
              </p>
            )}
          </section>
          <section className="card" aria-labelledby="when-to-go">
            <div className="card-head">
              <h2 id="when-to-go">When to go</h2>
            </div>
            {r.when_summary && <p>{r.when_summary}</p>}
            <ul>
              {r.when.map((p) => (
                <li key={p.text}>
                  {p.text} <Cite id={p.source} research={r} />
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
              <div className="table-wrap">
                <table className="holdings">
                  <thead>
                    <tr>
                      <th scope="col">What</th>
                      <th scope="col" className="num">
                        Range
                      </th>
                      <th scope="col">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.prices.map((p) => (
                      <tr key={`${p.label}:${p.source}`}>
                        <td>
                          {p.label}
                          <br />
                          <span className="caption">per {p.per}</span>
                        </td>
                        <td className="num">
                          {whole(p.low)}–{whole(p.high)} {p.currency}
                          {p.home_low && p.home_high && p.currency !== r.home_currency && (
                            <span className="caption">
                              <br />
                              about {whole(p.home_low)}–{whole(p.home_high)} {r.home_currency}
                            </span>
                          )}
                        </td>
                        <td>
                          <Cite id={p.source} research={r} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <section className="card" aria-labelledby="where-to-stay">
            <div className="card-head">
              <h2 id="where-to-stay">Where to stay</h2>
            </div>
            {r.areas.map((a) => (
              <div key={a.name} className="area">
                <h3>
                  {a.name} <Cite id={a.source} research={r} />
                </h3>
                <p className="muted">{a.why}</p>
                {a.things.length > 0 && <p className="caption">{a.things.join(" · ")}</p>}
              </div>
            ))}
            {r.getting_around && (
              <p>
                <strong>Getting around:</strong> {r.getting_around} <Cite id={r.getting_around_source} research={r} />
              </p>
            )}
          </section>
          <section className="card" aria-labelledby="sources">
            <div className="card-head">
              <h2 id="sources">Sources</h2>
              <span className="caption">Other people's pages; nothing is booked</span>
            </div>
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
          </section>
        </>
      )}
    </>
  );
}
