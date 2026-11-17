import { useQuery } from "@tanstack/react-query";

import { api, ApiError, type TripDetail } from "../api";
import { formatMoney } from "../format";
import { level } from "../components/PastBudgets";
import type { PanelEvent } from "./types";

type Props = { event: Extract<PanelEvent, { kind: "travel.trip_budget" }> };

export const OWNER_ONLY = "Only the trip's owner can see its money";

/** The same call, and the same cache entry, as the trip's own page. */
export function useTripDetail(tripId: string | number, enabled = true) {
  const id = String(tripId);
  return useQuery({
    queryKey: ["trip", id],
    queryFn: () => api<TripDetail>(`/travel/trips/${encodeURIComponent(id)}`),
    retry: false,
    enabled,
  });
}

/** A trip's money is the owner's: the server leaves it out for a member (spending is null, role "member")
 * and may refuse the request outright. Either way no figure is shown. */
export function moneyIsHidden(detail: TripDetail | undefined, error: unknown): boolean {
  if (error instanceof ApiError && (error.status === 403 || error.status === 404)) return true;
  return Boolean(detail && (detail.trip.role !== "owner" || detail.spending === null));
}

/** The one figure a collapsed card shows: what is left of the trip's budget, or what is spent. */
export function TripBudgetHeadline({ event }: Props) {
  const trip = useTripDetail(event.params.trip_id);
  if (trip.isLoading) return <span className="caption">Loading…</span>;
  if (moneyIsHidden(trip.data, trip.error)) return <span className="caption">{OWNER_ONLY}</span>;
  const s = trip.data?.spending;
  if (!trip.data || !s) return <span className="caption">Not loaded</span>;
  return (
    <span className="panel-figure">
      <span className="num">{formatMoney(s.left ?? s.spent)}</span>
      <span className="caption">
        {s.left ? "left" : "spent"} · {trip.data.trip.destination}
      </span>
    </span>
  );
}

/** A trip's budget against what is spent, with its biggest categories. Read-only. */
export function TripBudgetPanel({ event }: Props) {
  const query = useTripDetail(event.params.trip_id);
  if (query.isLoading) return <p className="state">Loading…</p>;
  if (moneyIsHidden(query.data, query.error)) return <p className="state panel-refusal">{OWNER_ONLY}.</p>;
  if (query.isError || !query.data || !query.data.spending) return <p className="state error-text">Couldn't load this trip's budget.</p>;
  const { trip, spending: s } = query.data;
  const state = level(s.percent ?? 0);
  const biggest = Math.max(1, ...s.categories.map((c) => Number(c.spent.amount)));
  return (
    <div className="panel-trip">
      <p className="panel-summary">
        <strong>{trip.destination}</strong> <span className="caption">{trip.days} {trip.days === 1 ? "day" : "days"}</span>
      </p>
      <dl className="panel-rows" aria-label="Budget">
        {trip.budget && (
          <div className="panel-row">
            <dt>Budget</dt>
            <dd className="num">{formatMoney(trip.budget)}</dd>
          </div>
        )}
        <div className="panel-row">
          <dt>Spent</dt>
          <dd className="num">{formatMoney(s.spent)}</dd>
        </div>
        {s.left && (
          <div className="panel-row panel-row-strong">
            <dt>{Number(s.left.amount) < 0 ? "Over by" : "Left"}</dt>
            <dd className="num">{formatMoney(Number(s.left.amount) < 0 ? { ...s.left, amount: String(-Number(s.left.amount)) } : s.left)}</dd>
          </div>
        )}
        {s.per_day && Number(s.per_day.amount) > 0 && (
          <div className="panel-row">
            <dt>Average a day</dt>
            <dd className="num">{formatMoney(s.per_day)}</dd>
          </div>
        )}
      </dl>
      {s.percent !== null && (
        <div
          className={`meter meter-${state}`}
          role="meter"
          aria-label="Trip budget used"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.min(s.percent, 100)}
          aria-valuetext={`${s.percent}% used`}
        >
          <span style={{ width: `${Math.min(s.percent, 100)}%` }} />
        </div>
      )}
      {s.categories.length > 0 && (
        <ul className="bars" aria-label="Biggest categories">
          {s.categories.slice(0, 5).map((c) => (
            <li key={c.name} className="bar-row">
              <span className="wrap">{c.name}</span>
              <span className="bar-track">
                <span className="bar" style={{ width: `${(Number(c.spent.amount) / biggest) * 100}%` }} />
              </span>
              <span className="num">
                {formatMoney(c.spent)}
                {c.planned && <span className="caption"> of {formatMoney(c.planned)}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {s.categories.length === 0 && <p className="caption">Nothing spent yet.</p>}
      {s.unconverted > 0 && <p className="caption">{s.unconverted} expenses have no exchange rate yet and aren't counted.</p>}
    </div>
  );
}
