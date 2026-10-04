import { useQuery } from "@tanstack/react-query";
import { type PointerEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type PlanBody, type PlanBrief, type PlanDetail } from "../api";
import { formatDate, formatShortDate } from "../format";

const usd = (amount: string | number) =>
  Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Every plan the research team has written, newest first. */
export function PlansPage() {
  const plans = useQuery({ queryKey: ["plans"], queryFn: () => api<PlanBrief[]>("/investments/plans") });
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Plans</h1>
          <p className="muted">Swing-trade research for days to weeks. Research only: never an order.</p>
        </div>
      </div>
      <section className="card" aria-labelledby="all-plans">
        <div className="card-head">
          <h2 id="all-plans">Research plans</h2>
        </div>
        {plans.isLoading && <p className="state">Loading…</p>}
        {plans.data?.length === 0 && (
          <p className="state">
            No plans yet. Open a stock from your portfolio or watchlist and ask for one, or say "plan for NVDA" in the
            chat.
          </p>
        )}
        {plans.data && plans.data.length > 0 && (
          <ul className="feed" aria-label="Plans">
            {plans.data.map((p) => (
              <li key={p.id}>
                <Link className="feed-item" to={`/investment/plans/${p.id}`}>
                  <span className="wrap">{p.summary_line}</span>
                  <span className="caption">
                    {formatShortDate(p.created_at)}
                    {p.expired && " · expired"}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

type Line = { label: string; price: number; kind: "stop" | "target" | "close" };

/** Recent closes with the plan's levels drawn across: the entry zone as a band, the
 * stop and targets as lines, each labelled. One series, so no legend. */
function PlanChart({ closes, plan }: { closes: PlanDetail["closes"]; plan: PlanBody }) {
  const [hover, setHover] = useState<number | null>(null);
  if (closes.length < 2) return null;
  const width = 640;
  const height = 240;
  const pad = { top: 12, right: 112, bottom: 22, left: 8 };
  const lines: Line[] = [
    ...(plan.stop ? [{ label: `Stop ${usd(plan.stop)}`, price: Number(plan.stop), kind: "stop" as const }] : []),
    ...plan.targets.map((t, i) => ({ label: `Target ${i + 1} ${usd(t.price)}`, price: Number(t.price), kind: "target" as const })),
  ];
  const values = [
    ...closes.map((c) => Number(c.close)),
    ...lines.map((l) => l.price),
    ...(plan.entry_low ? [Number(plan.entry_low), Number(plan.entry_high)] : []),
  ];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const x = (i: number) => pad.left + (i / (closes.length - 1)) * (width - pad.left - pad.right);
  const y = (v: number) => pad.top + (1 - (v - lo) / span) * (height - pad.top - pad.bottom);
  const path = closes.map((c, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(Number(c.close)).toFixed(1)}`).join("");

  function move(event: PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - box.left) / box.width;
    setHover(Math.max(0, Math.min(closes.length - 1, Math.round(ratio * (closes.length - 1)))));
  }

  const point = hover !== null ? closes[hover] : null;
  return (
    <figure className="plan-chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${plan.symbol} daily closes over ${closes.length} days, with the plan's levels`}
      >
        {plan.entry_low && plan.entry_high && (
          <g className="zone">
            <rect
              x={pad.left}
              width={width - pad.left - pad.right}
              y={y(Number(plan.entry_high))}
              height={Math.max(2, y(Number(plan.entry_low)) - y(Number(plan.entry_high)))}
            />
            <text x={width - pad.right + 6} y={(y(Number(plan.entry_high)) + y(Number(plan.entry_low))) / 2 + 4}>
              Entry zone
            </text>
          </g>
        )}
        {lines.map((l) => (
          <g key={l.label} className={`level ${l.kind}`}>
            <line x1={pad.left} x2={width - pad.right} y1={y(l.price)} y2={y(l.price)} />
            <text x={width - pad.right + 6} y={y(l.price) + 4}>
              {l.label}
            </text>
          </g>
        ))}
        <path className="price" d={path} />
        {point && hover !== null && (
          <g className="crosshair">
            <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={height - pad.bottom} />
            <circle cx={x(hover)} cy={y(Number(point.close))} r={4} />
          </g>
        )}
        <text className="axis" x={pad.left} y={height - 6}>
          {formatShortDate(closes[0].day, "UTC")}
        </text>
        <text className="axis" x={width - pad.right} y={height - 6} textAnchor="end">
          {formatShortDate(closes[closes.length - 1].day, "UTC")}
        </text>
        <rect
          className="hit"
          x={pad.left}
          y={0}
          width={width - pad.left - pad.right}
          height={height}
          onPointerMove={move}
          onPointerLeave={() => setHover(null)}
        />
      </svg>
      <figcaption className="caption" aria-live="polite">
        {point ? (
          <>
            <strong>USD {usd(point.close)}</strong> close on {formatShortDate(point.day, "UTC")}
          </>
        ) : (
          "Daily closes. Hover or tap the chart for a day's close."
        )}
      </figcaption>
    </figure>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/** One plan: the numbers (worked out in code), the chart, and the analysts' notes
 * with their sources. */
export function PlanPage() {
  const { id = "" } = useParams();
  const detail = useQuery({ queryKey: ["plan", id], queryFn: () => api<PlanDetail>(`/investments/plans/${id}`) });
  const data = detail.data;
  const plan = data?.plan;
  const sources = new Map((plan?.sources ?? []).map((s) => [s.id, s]));
  return (
    <>
      <div className="page-head">
        <div>
          <p className="caption">
            <Link to="/investment/plans">Plans</Link>
            {plan && (
              <>
                {" "}
                · <Link to={`/investment/stocks/${plan.symbol}`}>{plan.symbol}</Link>
              </>
            )}
          </p>
          <h1>{plan ? `Plan for ${plan.symbol}` : "Plan"}</h1>
          {data && (
            <p className="muted">
              Made {formatDate(data.brief.created_at)} from the close of {formatShortDate(plan!.as_of, "UTC")} · valid until{" "}
              {formatShortDate(plan!.valid_until, "UTC")}
              {data.brief.expired && " (expired: ask for a fresh one)"}
            </p>
          )}
        </div>
      </div>
      {detail.isLoading && <p className="state">Loading…</p>}
      {detail.isError && (
        <p className="error-text" role="alert">
          {detail.error instanceof Error ? detail.error.message : "Couldn't load that plan."}
        </p>
      )}
      {data && plan && (
        <>
          <section className="card" aria-labelledby="verdict">
            <div className="card-head">
              <h2 id="verdict">{plan.verdict_text}</h2>
            </div>
            <p>{plan.summary}</p>
            <dl className="totals" aria-label="Plan levels">
              <div>
                <dt>Close</dt>
                <dd className="num">{usd(plan.close)}</dd>
              </div>
              {plan.entry_low && (
                <div>
                  <dt>Entry zone ({plan.entry_why})</dt>
                  <dd className="num">
                    {usd(plan.entry_low)}–{usd(plan.entry_high!)}
                  </dd>
                </div>
              )}
              {plan.stop && (
                <div>
                  <dt>Stop</dt>
                  <dd className="num">{usd(plan.stop)}</dd>
                </div>
              )}
              {plan.targets.map((t, i) => (
                <div key={t.price}>
                  <dt>
                    Target {i + 1} ({t.why}, {t.reward_risk}× risk)
                  </dt>
                  <dd className="num">{usd(t.price)}</dd>
                </div>
              ))}
            </dl>
            <p className="caption">{plan.reason}</p>
            {plan.held && (
              <p className="muted">
                You hold {plan.held}
                {plan.held_gain_percent !== null && `, ${Number(plan.held_gain_percent) >= 0 ? "+" : ""}${plan.held_gain_percent}% against your cost`}.
              </p>
            )}
            {plan.earnings_in_window && (
              <p className="warning-text">⚠️ Earnings on {formatShortDate(plan.earnings_in_window, "UTC")}, inside the plan's window.</p>
            )}
            <p>
              <strong>What would prove it wrong:</strong> {plan.invalidation}
            </p>
            <PlanChart closes={data.closes} plan={plan} />
          </section>

          <section className="card" aria-labelledby="analysts">
            <div className="card-head">
              <h2 id="analysts">The analysts</h2>
            </div>
            <h3>Technical</h3>
            <p>{plan.technical}</p>
            <h3>News</h3>
            {plan.news.length === 0 ? (
              <p className="muted">No recent news to weigh.</p>
            ) : (
              <ul>
                {plan.news.map((n) => (
                  <li key={n.text}>
                    {n.text}{" "}
                    {n.sources.map((sid) => {
                      const s = sources.get(sid);
                      return s ? (
                        <a key={sid} className="cite" href={s.url} target="_blank" rel="noopener noreferrer nofollow" title={s.headline}>
                          [{s.source}]
                        </a>
                      ) : null;
                    })}
                  </li>
                ))}
              </ul>
            )}
            <List title="Risks in the window" items={plan.risks} />
            <div className="debate">
              <List title="Bull case" items={plan.bull} />
              <List title="Bear case" items={plan.bear} />
            </div>
            <List title="Levels used" items={plan.levels} />
            <p className="caption">
              Every price here was worked out in code from daily closes; the analysts only wrote the words. Research, not
              advice.
            </p>
          </section>
        </>
      )}
    </>
  );
}
