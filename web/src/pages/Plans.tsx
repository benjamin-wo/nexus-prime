import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type PointerEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, type PlanBody, type PlanBrief, type PlanDetail, type PlanOdds, type PlanRecord, type PlanStep } from "../api";
import { formatDate, formatShortDate } from "../format";

const usd = (amount: string | number) =>
  Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Every plan the research team has written, newest first. */
/** Where a plan stands: open, or how it ended. */
export function PlanStatus({ plan }: { plan: PlanBrief }) {
  if (!plan.followed) return null;
  const result = plan.result_percent !== null ? ` ${Number(plan.result_percent) > 0 ? "+" : ""}${plan.result_percent}%` : "";
  const label =
    plan.status === "target"
      ? `🎯 Hit target${result}`
      : plan.status === "stopped"
        ? `🛑 Stopped out${result}`
        : plan.status === "expired"
          ? plan.entered_on
            ? `📅 Ran out${result}`
            : "📅 Ran out, never bought"
          : plan.entered_on
            ? "⏳ Open, bought"
            : "⏳ Open, waiting to buy";
  return <span className={`badge status-${plan.status}`}>{label}</span>;
}

function TrackRecord() {
  const record = useQuery({ queryKey: ["plans", "record"], queryFn: () => api<PlanRecord>("/investments/plans/record") });
  const r = record.data;
  if (!r) return null;
  return (
    <section className="card" aria-labelledby="record">
      <div className="card-head">
        <h2 id="record">Track record</h2>
        <span className="caption">Scored after each US close, misses included</span>
      </div>
      {r.finished > 0 && (
        <dl className="totals" aria-label="Plan results">
          <div>
            <dt>Hit target</dt>
            <dd className="num up">{r.targets}</dd>
          </div>
          <div>
            <dt>Stopped out</dt>
            <dd className="num down">{r.stopped}</dd>
          </div>
          <div>
            <dt>Ran out</dt>
            <dd className="num">{r.expired}</dd>
          </div>
          {r.average_result !== null && (
            <div>
              <dt>Average result</dt>
              <dd className={`num ${Number(r.average_result) >= 0 ? "up" : "down"}`}>
                {Number(r.average_result) > 0 ? "+" : ""}
                {r.average_result}%
              </dd>
            </div>
          )}
          {r.odds_said !== null && r.odds_happened !== null && (
            <>
              <div>
                <dt>Odds gave target 1</dt>
                <dd className="num">{r.odds_said}%</dd>
              </div>
              <div>
                <dt>Reached it</dt>
                <dd className="num">{r.odds_happened}%</dd>
              </div>
            </>
          )}
        </dl>
      )}
      <p className="muted">{r.text}</p>
    </section>
  );
}

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
      <TrackRecord />
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
                  <span className="wrap">
                    <strong>{p.headline}</strong>
                    <br />
                    <span className="muted">{p.reason}</span>
                  </span>
                  <span className="caption">
                    <PlanStatus plan={p} />
                    <br />
                    {formatShortDate(p.created_at)}
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

type Line = { label: string; price: number; kind: "stop" | "target" | "cost" };

/** Recent closes with the plan's levels drawn across: the entry zone as a band, the
 * stop and targets as lines, each labelled. One series, so no legend. */
function PlanChart({ closes, plan }: { closes: PlanDetail["closes"]; plan: PlanBody }) {
  const [hover, setHover] = useState<number | null>(null);
  if (closes.length < 2) return null;
  const width = 640;
  const height = 240;
  const pad = { top: 12, right: 112, bottom: 22, left: 8 };
  const lines: Line[] = [
    ...(plan.stop ? [{ label: `Cut losses ${usd(plan.stop)}`, price: Number(plan.stop), kind: "stop" as const }] : []),
    ...plan.targets.map((t, i) => ({ label: `Profit ${i + 1}: ${usd(t.price)}`, price: Number(t.price), kind: "target" as const })),
    ...(plan.average_cost ? [{ label: `Your cost ${usd(plan.average_cost)}`, price: Number(plan.average_cost), kind: "cost" as const }] : []),
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
              {plan.held ? "Add-more zone" : "Buy zone"}
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

const ICONS: Record<PlanStep["kind"], string> = {
  buy: "🟢",
  take_profit: "🎯",
  cut_loss: "🛑",
  trail: "↗️",
  review: "📅",
};

/** How the headline is coloured: go, wait or stop. */
export function verdictTone(verdict: string): "good" | "wait" | "bad" {
  if (verdict === "in_zone" || verdict === "hold" || verdict === "trim") return "good";
  if (verdict === "wait") return "wait";
  return "bad";
}

/** The steps for a plan saved before the game plan existed. */
function fallbackSteps(plan: PlanBody): PlanStep[] {
  const steps: PlanStep[] = [];
  if (plan.entry_low)
    steps.push({ kind: "buy", title: "Buy", price: `${usd(plan.entry_low)} to ${usd(plan.entry_high!)}`, detail: `At the ${plan.entry_why}.`, change: [] });
  if (plan.targets.length)
    steps.push({ kind: "take_profit", title: "Take profit", price: plan.targets.map((t) => usd(t.price)).join(" / "), detail: "Sell part at the first price, the rest at the second.", change: [] });
  if (plan.stop)
    steps.push({ kind: "cut_loss", title: "Cut losses", price: usd(plan.stop), detail: `Sell if a day closes below ${usd(plan.stop)}.`, change: [] });
  steps.push({ kind: "review", title: `Valid until ${formatShortDate(plan.valid_until, "UTC")}`, price: null, detail: "Then ask for a fresh plan.", change: [] });
  return steps;
}

export function planSteps(plan: PlanBody): PlanStep[] {
  return plan.playbook && plan.playbook.length ? plan.playbook : fallbackSteps(plan);
}

/** The game plan: what to do, at what price, and how far that is from today. */
export function GamePlan({ steps, compact = false }: { steps: PlanStep[]; compact?: boolean }) {
  return (
    <ol className={`game-plan${compact ? " compact" : ""}`} aria-label="Game plan">
      {steps.map((step) => (
        <li key={step.kind} className={`step ${step.kind}`}>
          <span className="step-icon" aria-hidden="true">
            {ICONS[step.kind]}
          </span>
          <div className="step-body">
            <div className="step-head">
              <span className="step-title">{step.title}</span>
              {step.price && <span className="step-price num">{step.price}</span>}
              {step.change.map((c) => (
                <span key={c} className={`chip ${step.kind === "take_profit" ? "up" : step.kind === "cut_loss" ? "down" : ""}`}>
                  {c}
                </span>
              ))}
            </div>
            {!compact && <p className="step-detail">{step.detail}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function List({ title, items, tone }: { title: string; items: string[]; tone?: "up" | "down" }) {
  if (items.length === 0) return null;
  return (
    <div className={`why-list ${tone ?? ""}`}>
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/** One plan: the headline, the game plan with its prices (worked out in code), the
 * chart, then why, with sources. */
function Following({ brief }: { brief: PlanBrief }) {
  const client = useQueryClient();
  const [alerts, setAlerts] = useState(brief.alerts);
  if (!brief.followed) return null;
  async function toggle() {
    const on = !alerts;
    setAlerts(on);
    try {
      await api(`/investments/plans/${brief.id}/alerts`, { method: "POST", body: { on } });
    } catch {
      setAlerts(!on);
    }
    void client.invalidateQueries({ queryKey: ["plan", brief.id] });
  }
  const outcome =
    brief.status === "open"
      ? brief.entered_on
        ? "It's being followed after each US close: you'll get a message if it reaches its target or its stop, or runs out."
        : "It's being followed after each US close: you'll get a message when it dips into the buy zone, and again at its target or stop."
      : `It finished on ${formatShortDate(brief.outcome_day!, "UTC")}${brief.outcome_price ? ` at ${usd(brief.outcome_price)}` : ""}.`;
  return (
    <section className="card following" aria-labelledby="following">
      <div className="card-head">
        <h2 id="following">How it's going</h2>
        <PlanStatus plan={brief} />
      </div>
      <p className="muted">{outcome}</p>
      {brief.status === "open" && (
        <label className="toggle">
          <input type="checkbox" checked={alerts} onChange={() => void toggle()} /> Telegram alerts for this plan
        </label>
      )}
    </section>
  );
}

/** The plan replayed over the stock's last year of daily moves, worked out in code. The
 * three outcomes for the first target add up to about 100%. */
function OddsCard({ odds }: { odds: PlanOdds }) {
  const first = odds.targets[0];
  const parts = [
    { key: "target", label: "Target 1 first", value: first?.chance ?? 0 },
    { key: "stop", label: "Stop first", value: odds.stop_first },
    { key: "neither", label: "Neither in time", value: odds.neither },
  ];
  return (
    <section className="card" aria-labelledby="odds">
      <div className="card-head">
        <h2 id="odds">Odds</h2>
        <span className="caption">
          {odds.paths.toLocaleString("en-US")} replays of the last year&apos;s moves · not a forecast
        </span>
      </div>
      <div className="odds-bar" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}%`).join(", ")}>
        {parts.map((p) =>
          p.value > 0 ? <span key={p.key} className={`odds-${p.key}`} style={{ width: `${p.value}%` }} /> : null,
        )}
      </div>
      <ul className="odds-key">
        {parts.map((p) => (
          <li key={p.key}>
            <span className={`odds-dot odds-${p.key}`} aria-hidden="true" />
            {p.label} <strong className="num">{p.value}%</strong>
          </li>
        ))}
      </ul>
      <ul className="ladder" aria-label="Chance of each target">
        {odds.targets.map((t, i) => (
          <li key={t.price} className="up">
            <span>
              Target {i + 1} at {usd(t.price)}
              {t.typical_days !== null && <span className="caption"> · typically {t.typical_days} trading days</span>}
            </span>
            <span className="num">{t.chance}%</span>
          </li>
        ))}
        <li className="down">
          <span>Stop at {usd(odds.stop)} before target 1</span>
          <span className="num">{odds.stop_first}%</span>
        </li>
      </ul>
      <p className="caption">
        Starting from {usd(odds.reference)}, the stock&apos;s own daily moves were shuffled week by week over the plan&apos;s{" "}
        {odds.days} trading days, with no lean up or down. It shows how reachable the prices are, not where the stock
        will go.
      </p>
    </section>
  );
}

export function PlanPage() {
  const { id = "" } = useParams();
  const detail = useQuery({ queryKey: ["plan", id], queryFn: () => api<PlanDetail>(`/investments/plans/${id}`) });
  const data = detail.data;
  const plan = data?.plan;
  const sources = new Map((plan?.sources ?? []).map((s) => [s.id, s]));
  const risks = plan ? [...plan.bear, ...plan.risks] : [];
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
          <h1>{plan ? `${plan.symbol} plan` : "Plan"}</h1>
          {data && plan && (
            <p className="muted">
              Closing price {usd(plan.close)} on {formatShortDate(plan.as_of, "UTC")} · made {formatDate(data.brief.created_at)}
              {data.brief.expired && " · expired: ask for a fresh one"}
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
          <section className={`card verdict ${verdictTone(plan.verdict)}`} aria-labelledby="verdict">
            <p className="caption">The verdict</p>
            <h2 id="verdict">{plan.verdict_text}</h2>
            <p className="verdict-reason">{plan.reason}</p>
            {plan.held && (
              <p className="muted">
                You hold {plan.held}
                {plan.held_gain_percent !== null && (
                  <>
                    {" "}
                    ·{" "}
                    <span className={Number(plan.held_gain_percent) >= 0 ? "up" : "down"}>
                      {Number(plan.held_gain_percent) >= 0 ? "+" : ""}
                      {plan.held_gain_percent}%
                    </span>{" "}
                    on what you paid
                  </>
                )}
              </p>
            )}
            <p>{plan.summary}</p>
            {plan.incomplete && plan.incomplete.length > 0 && (
              <p className="callout" role="note">
                ⚠️ The write-up is missing {plan.incomplete.join(" and ")} this time; the prices and game plan are complete.
              </p>
            )}
          </section>

          <Following brief={data.brief} />

          <section className="card" aria-labelledby="game-plan">
            <div className="card-head">
              <h2 id="game-plan">Your game plan</h2>
              <span className="caption">Prices worked out from daily closes</span>
            </div>
            <GamePlan steps={planSteps(plan)} />
            <p className="callout">
              <strong>What would prove it wrong:</strong> {plan.invalidation}
            </p>
          </section>

          {plan.odds && <OddsCard odds={plan.odds} />}

          <section className="card" aria-labelledby="chart">
            <div className="card-head">
              <h2 id="chart">Where those prices sit</h2>
            </div>
            <PlanChart closes={data.closes} plan={plan} />
          </section>

          <section className="card" aria-labelledby="why">
            <div className="card-head">
              <h2 id="why">Why</h2>
            </div>
            <div className="debate">
              <List title="What's going for it" items={plan.bull} tone="up" />
              <List title="What could go wrong" items={risks} tone="down" />
            </div>
            <h3>In the news</h3>
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
            <details className="more">
              <summary>The chart reading and the numbers behind it</summary>
              <p>{plan.technical}</p>
              <ul>
                {plan.levels.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
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
