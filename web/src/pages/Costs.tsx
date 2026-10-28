import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError, type Me } from "../api";
import { BackLink } from "../components/BackLink";
import { Block } from "../components/Block";
import { StatTile } from "../components/StatTile";
import {
  costDayLabel,
  type CostDay,
  type Costs,
  featureLabel,
  formatCount,
  formatShare,
  formatTokens,
  formatUsd,
  RANGES,
  type Range,
} from "../costs";

/** Daily cost as bars. Hover, focus or tap a bar and the line above names the day, its cost and its
 * calls; with nothing picked it is the latest day. */
export function DailyCostChart({ days }: { days: CostDay[] }) {
  const [picked, setPicked] = useState<string | null>(null);
  if (days.length === 0) return <p className="state">No model calls in this period.</p>;
  const shown = days.find((d) => d.day === picked) ?? days[days.length - 1]!;
  const top = Math.max(0, ...days.map((d) => Number(d.cost)));
  const height = (d: CostDay) => (top > 0 && Number(d.cost) > 0 ? `${Math.max(3, (Number(d.cost) / top) * 100)}%` : "2px");
  const calls = (n: number) => `${formatCount(n)} ${n === 1 ? "call" : "calls"}`;
  return (
    <div className="cost-chart">
      <p className="cost-readout" aria-live="polite">
        <strong>{costDayLabel(shown.day)}</strong>
        <span className="num">{formatUsd(shown.cost)}</span>
        <span className="caption">{calls(shown.calls)}</span>
      </p>
      <ul className="cost-bars" aria-label="Cost per day" onMouseLeave={() => setPicked(null)}>
        {days.map((d) => (
          <li key={d.day}>
            <button
              type="button"
              className={`cost-hit${d.day === shown.day ? " on" : ""}`}
              aria-label={`${costDayLabel(d.day)}: ${formatUsd(d.cost)}, ${calls(d.calls)}`}
              aria-pressed={d.day === shown.day}
              title={`${costDayLabel(d.day)}: ${formatUsd(d.cost)}`}
              onMouseEnter={() => setPicked(d.day)}
              onFocus={() => setPicked(d.day)}
              onClick={() => setPicked(d.day)}
            >
              <span className="cost-bar" style={{ height: height(d) }} />
            </button>
          </li>
        ))}
      </ul>
      <div className="cost-axis" aria-hidden="true">
        <span>{costDayLabel(days[0]!.day)}</span>
        <span>{costDayLabel(days[days.length - 1]!.day)}</span>
      </div>
    </div>
  );
}

const callsText = (n: number) => `${formatCount(n)} ${n === 1 ? "call" : "calls"}`;

/** What the AI models cost, for the owner. */
export function CostsPage({ me }: { me: Me }) {
  const owner = me.user.role === "owner";
  const [days, setDays] = useState<Range>(30);
  const costs = useQuery({
    queryKey: ["costs", days],
    queryFn: () => api<Costs>(`/ops/costs?days=${days}`),
    enabled: owner,
    placeholderData: keepPreviousData,
    // A 404 is the server saying this isn't for you; asking again won't change it.
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
  const hidden = !owner || (costs.error instanceof ApiError && costs.error.status === 404);
  const data = costs.data;

  return (
    <>
      <div className="page-head">
        <div>
          <BackLink to="/settings">Back to Settings</BackLink>
          <h1>Model costs</h1>
          {!hidden && <p className="muted">What the AI models cost to run Nexus.</p>}
        </div>
        {!hidden && (
          <div className="filters">
            <div className="tabs" role="group" aria-label="Days shown">
              {RANGES.map((r) => (
                <button key={r} type="button" className="tab" aria-pressed={days === r} onClick={() => setDays(r)}>
                  {r} days
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {hidden && <p className="state">Model costs aren't available.</p>}
      {!hidden && costs.isLoading && <p className="state">Loading…</p>}
      {!hidden && costs.isError && <p className="state error-text">Couldn't load the model costs.</p>}
      {!hidden && data && (
        <div className="stack">
          <div className="tiles">
            <StatTile
              label="This month so far"
              value={formatUsd(data.month.spent)}
              extra={`Day ${data.month.days_elapsed} of ${data.month.days_in_month} · ${formatShare(data.month.cached_share)} of input cached`}
            />
            <StatTile label="Projected for the month" value={formatUsd(data.month.projected)} />
            <StatTile label="Per active user per month" value={formatUsd(data.per_active_user_month)} />
          </div>

          <Block id="costs-days" title={`Last ${days} days`}>
            <DailyCostChart days={data.days} />
          </Block>

          <Block id="costs-features" title="By feature">
            {data.by_feature.length === 0 && <p className="state">No model calls in this period.</p>}
            <ul className="cost-list">
              {data.by_feature.map((f) => {
                const share = Math.round(f.share * 100);
                return (
                  <li key={f.feature}>
                    <div className="cost-line">
                      <span className="cost-name">{featureLabel(f.feature)}</span>
                      <span className="num">{formatUsd(f.cost)}</span>
                    </div>
                    <div className="meter" aria-hidden="true">
                      <span style={{ width: `${Math.min(100, Math.max(f.share > 0 ? 1 : 0, f.share * 100))}%` }} />
                    </div>
                    <span className="caption">
                      {share}% · {callsText(f.calls)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </Block>

          <Block id="costs-users" title="By user">
            {data.by_user.length === 0 && <p className="state">No model calls in this period.</p>}
            <ul className="cost-list">
              {data.by_user.map((u) => (
                <li key={u.user_id ?? "system"}>
                  <div className="cost-line">
                    <span className="cost-name">{u.name}</span>
                    <span className="num">{formatUsd(u.cost)}</span>
                  </div>
                  <span className="caption">{callsText(u.calls)}</span>
                </li>
              ))}
            </ul>
          </Block>

          <Block id="costs-models" title="By model">
            {data.by_model.length === 0 && <p className="state">No model calls in this period.</p>}
            <ul className="cost-list">
              {data.by_model.map((m) => (
                <li key={m.model}>
                  <div className="cost-line">
                    <span className="cost-name">{m.model}</span>
                    <span className="num">{formatUsd(m.cost)}</span>
                  </div>
                  <span className="caption">
                    {callsText(m.calls)} · {formatTokens(m.input_tokens)} in ({formatShare(m.cached_share)} cached) ·{" "}
                    {formatTokens(m.output_tokens)} out
                  </span>
                </li>
              ))}
            </ul>
          </Block>

          <p className="caption">
            Exact costs reported by OpenRouter. Search and Maps APIs are billed separately and aren't included.
          </p>
        </div>
      )}
    </>
  );
}

/** On the Settings page, for the owner only: the way in to the model costs. */
export function CostsCard() {
  return (
    <section className="card" aria-labelledby="costs-card">
      <div className="card-head">
        <h2 id="costs-card">Model costs</h2>
        <Link className="btn" to="/settings/costs">
          Open
        </Link>
      </div>
      <p className="caption">What the AI models cost this month, by feature, user and model.</p>
    </section>
  );
}
