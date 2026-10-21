import { Link } from "react-router-dom";

import type { Booking, Budget, Money, Portfolio, Setup, TripDetail } from "../api";
import { type Pace } from "../brief";
import { Block } from "../components/Block";
import { Icon } from "../components/Icon";
import { PriceWhen } from "../components/PriceWhen";
import { formatChange, formatMoney, formatPercent, formatShortDate } from "../format";
import { daySpot, spotsOf } from "./TripArrange";
import { landingOn, landsOnly, leavingOn, todayIso } from "./TripBits";

/* Home's small cards: the glance column, the trip card for a trip that is on, and the
 * setup checklist. Each is given what it shows, so Home owns the queries. */

/** This month's spending and how it is going, against the overall budget or else last
 * month by this date. */
export function MoneyGlance({ spent, overall, pace }: { spent?: Money; overall?: Budget; pace: Pace | null }) {
  return (
    <Block
      id="glance-money"
      title="Money this month"
      className="glance"
      action={
        <Link className="btn btn-small" to="/accounting">
          Details
        </Link>
      }
    >
      {!spent ? (
        <p className="state">Loading…</p>
      ) : (
        <>
          <span className="glance-figure">{formatMoney(spent)}</span>
          {pace?.label && <p className={`glance-line${pace.ahead ? " pace-ahead" : ""}`}>{pace.label}</p>}
          {overall && (
            <div
              className={`meter${overall.percent >= 100 ? " meter-over" : overall.percent >= 80 ? " meter-warn" : ""}`}
              role="meter"
              aria-label="Budget used"
              aria-valuenow={Math.min(overall.percent, 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <span style={{ width: `${Math.min(100, overall.percent)}%` }} />
            </div>
          )}
          {pace && <p className="caption">{pace.detail}</p>}
          {!pace && <p className="muted">Set a budget on the Plan page to see how it is going.</p>}
        </>
      )}
    </Block>
  );
}

/** The portfolio's value in the home currency and how it moved in the latest session. */
export function PortfolioGlance({ portfolio }: { portfolio?: Portfolio }) {
  const totals = portfolio?.totals;
  return (
    <Block
      id="glance-portfolio"
      title="Portfolio today"
      className="glance"
      action={
        <Link className="btn btn-small" to="/investment">
          Open
        </Link>
      }
    >
      {!portfolio ? (
        <p className="state">Loading…</p>
      ) : portfolio.holdings.length === 0 ? (
        <p className="muted">
          No holdings yet. <Link to="/investment">Add your stocks</Link>.
        </p>
      ) : (
        <>
          <span className="glance-figure">{totals?.value ? formatMoney(totals.value) : "No prices yet"}</span>
          {totals?.day_change && (
            <p className={`glance-line ${Number(totals.day_change.amount) >= 0 ? "up" : "down"}`}>
              {formatChange(totals.day_change)}
              {totals.day_percent !== null && ` (${formatPercent(totals.day_percent)})`}
            </p>
          )}
          {totals && (totals.as_of || totals.as_of_at) && (
            <PriceWhen kind={totals.price_kind} at={totals.as_of_at} day={totals.as_of} />
          )}
        </>
      )}
    </Block>
  );
}

/** The trip that is coming up: "Tokyo in 12 days", or a way to plan one. */
export function TripGlance({ detail }: { detail?: TripDetail | null }) {
  const t = detail?.trip;
  const coming = t && t.status === "upcoming" ? t : null;
  const gaps = detail?.ready.nights_without_stay.length ?? 0;
  return (
    <Block
      id="glance-trip"
      title="Next trip"
      className="glance"
      action={
        coming ? (
          <Link className="btn btn-small" to={`/travel/trips/${coming.id}`}>
            Open
          </Link>
        ) : undefined
      }
    >
      {detail === undefined ? (
        <p className="state">Loading…</p>
      ) : coming ? (
        <>
          <span className="glance-figure">
            {coming.destination} {coming.days_until === 1 ? "tomorrow" : `in ${coming.days_until} days`}
          </span>
          <p className="caption">
            {formatShortDate(coming.start, "UTC")} to {formatShortDate(coming.end, "UTC")}
            {gaps > 0 && ` · ${gaps} ${gaps === 1 ? "night" : "nights"} with no place to stay yet`}
          </p>
        </>
      ) : (
        <p className="muted">
          No trip coming up. <Link to="/travel">Plan a trip</Link>.
        </p>
      )}
    </Block>
  );
}

const DAY_MS = 86400000;
const timeOf = (iso: string | null) => (iso && iso.length > 11 ? iso.slice(11, 16) : null);

/** The date of a trip's current day: the trip's own day count, else the browser's today. */
export function tripDay(trip: TripDetail["trip"]): string {
  return trip.day_number ? new Date(Date.parse(trip.start) + (trip.day_number - 1) * DAY_MS).toISOString().slice(0, 10) : todayIso();
}

/** One entry of a day, as one line: its time (when it has one) and what it is. */
type Line = { id: string; time: string | null; text: string };

function lineOf(b: Booking, day: string): Line {
  if (landsOnly(b, day)) {
    const last = landingOn(b, day).at(-1)!;
    return { id: b.id, time: timeOf(last.arrives), text: `${b.kind === "flight" ? "Land" : "Arrive"} ${last.destination ?? ""}`.trim() };
  }
  if (b.kind === "flight" || b.kind === "rail") {
    const leaving = leavingOn(b, day);
    const first = leaving[0] ?? b.segments[0];
    const last = leaving.at(-1) ?? b.segments.at(-1);
    const route = [first?.origin, last?.destination].filter(Boolean).join(" → ");
    return { id: b.id, time: timeOf(first?.departs ?? null) ?? b.at, text: `${b.kind === "flight" ? "Flight" : "Train"} ${route || b.title}` };
  }
  if (b.kind === "hotel") {
    const name = b.hotel ?? b.title;
    return { id: b.id, time: null, text: b.check_out === day && b.check_in !== day ? `Check out of ${name}` : `Check in at ${name}` };
  }
  return { id: b.id, time: b.at, text: b.title };
}

/** What is planned on a day, in the itinerary's order (plans, flights, trains and stays, and a
 * stay the trip leaves that morning). */
export function dayLines(detail: TripDetail, day: string): Line[] {
  const outs = detail.bookings.filter((b) => b.scheduled && b.kind === "hotel" && b.check_out === day && b.starts !== day);
  const planned = spotsOf(detail).get(daySpot(day)) ?? [];
  return [...outs, ...planned].map((b) => lineOf(b, day));
}

/** What is next today: the first thing with a time at or after `now` (HH:MM), else the first
 * with no time. Null when nothing is left. */
export function nextToday(lines: Line[], now: string): Line | null {
  return lines.find((l) => l.time !== null && l.time >= now) ?? lines.find((l) => l.time === null) ?? null;
}

/** The next flight, train or stay still to come after today. */
export function nextBooking(detail: TripDetail, day: string): Booking | null {
  const later = detail.bookings
    .filter((b) => b.scheduled && (b.kind === "flight" || b.kind === "rail" || b.kind === "hotel") && b.starts > day)
    .sort((a, b) => a.starts.localeCompare(b.starts));
  return later[0] ?? null;
}

/** The time of day in a time zone, as HH:MM. */
export function clock(timezone: string, now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: timezone }).format(now);
}

/** Leads Home while a trip is on: which day it is, what is next, today's spending against the
 * budget and the next booking. Only what the trip's own page data already holds. */
export function TripMode({ detail, timezone, now }: { detail: TripDetail; timezone: string; now?: Date }) {
  const t = detail.trip;
  const day = tripDay(t);
  const lines = dayLines(detail, day);
  const next = nextToday(lines, clock(timezone, now));
  const booking = nextBooking(detail, day);
  const s = detail.spending;
  const today = s?.today ?? null;
  const perDay = s?.per_day_left && Number(s.per_day_left.amount) > 0 ? s.per_day_left : null;
  return (
    <Block
      id="trip-mode"
      title={t.day_number ? `Day ${t.day_number} in ${t.destination}` : `On now in ${t.destination}`}
      className="trip-mode"
      action={
        <Link className="btn btn-small" to={`/travel/trips/${t.id}`}>
          Open trip
        </Link>
      }
    >
      <ul className="mode-lines">
        <li>
          <Icon name="clock" size={18} />
          <span>
            {next ? (
              <>
                <span className="caption">Next</span>
                <br />
                {next.time ? `${next.time} · ` : ""}
                {next.text}
              </>
            ) : (
              <span className="muted">{lines.length ? "Nothing more planned today." : "Nothing planned today."}</span>
            )}
          </span>
        </li>
        {today && (
          <li>
            <Icon name="receipt" size={18} />
            <span>
              <span className="caption">Spent today</span>
              <br />
              {Number(today.amount) > 0 ? formatMoney(today) : "Nothing yet"}
              {perDay && <span className="muted"> · {formatMoney(perDay)} a day left in your budget</span>}
            </span>
          </li>
        )}
        {booking && (
          <li>
            <Icon name={booking.kind === "hotel" ? "stay" : booking.kind === "rail" ? "train" : "flight"} size={18} />
            <span>
              <span className="caption">Next booking</span>
              <br />
              {booking.kind === "hotel" ? `Check in at ${booking.hotel ?? booking.title}` : booking.title}
              <span className="muted"> · {formatShortDate(booking.starts, "UTC")}</span>
            </span>
          </li>
        )}
      </ul>
    </Block>
  );
}

/** Done: a tick. To do: an empty ring. Both are named in words for a screen reader. */
function Tick({ done }: { done: boolean }) {
  return (
    <span className={`row-icon${done ? " in" : ""}`} aria-hidden="true">
      {done ? <Icon name="check" size={18} /> : <span className="ring" />}
    </span>
  );
}

/** The few things that make Nexus useful, until they are done or the person hides the list.
 * Each step opens the page where it is done, or asks Nexus for help with it (each `ask` is a
 * plain request with no values of its own). */
export function SetupCard({
  setup,
  busy,
  error,
  onHide,
  onAsk,
}: {
  setup: Setup;
  busy: boolean;
  error: string | null;
  onHide: () => void;
  onAsk: (text: string) => void;
}) {
  const left = setup.items.filter((i) => !i.done).length;
  return (
    <Block
      id="setup"
      title="Get set up"
      action={
        <button type="button" className="btn btn-small" disabled={busy} onClick={onHide}>
          Hide
        </button>
      }
    >
      <p className="caption setup-note">
        {left === 1 ? "One step left." : `${left} steps left.`}
      </p>
      <ul className="rows" aria-label="Setup steps">
        {setup.items.map((item) => (
          <li key={item.key} className={`row setup-row${item.done ? " is-done" : ""}`}>
            <Tick done={item.done} />
            <span className="row-main">
              <span className="wrap">{item.label}</span>
              {item.done && <span className="caption">Done</span>}
            </span>
            {!item.done && (
              <span className="setup-actions">
                <Link className="btn btn-soft btn-small" to={item.link}>
                  Set up<span className="sr-only"> {item.label}</span>
                </Link>
                <button type="button" className="btn btn-ghost btn-small" onClick={() => onAsk(item.ask)}>
                  Ask Nexus<span className="sr-only"> to {item.label.toLowerCase()}</span>
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Block>
  );
}
