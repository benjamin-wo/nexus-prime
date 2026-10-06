import { type CSSProperties, type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import type { Booking, Trip, TripDetail, TripPhoto } from "../api";
import { formatMoney, formatShortDate } from "../format";

const day = (iso: string) => formatShortDate(iso, "UTC");
const DAY_MS = 86400000;

/** Today in the browser's own time zone, as YYYY-MM-DD. */
export const todayIso = () => new Date().toLocaleDateString("en-CA");

const daysBetween = (from: string, to: string) => Math.round((Date.parse(to) - Date.parse(from)) / DAY_MS);

/** A gradient for trips without a photo yet, the same for the same place. */
export function coverGradient(destination: string): string {
  let hash = 0;
  for (const ch of destination.toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = hash % 360;
  return `linear-gradient(160deg, hsl(${hue} 32% 22%) 0%, hsl(${(hue + 40) % 360} 24% 13%) 60%, #0f0f12 100%)`;
}

/** The cover behind a trip's header or card: its photo, or a gradient. */
export function coverStyle(trip: Trip): CSSProperties {
  const fade = "linear-gradient(180deg, rgba(9,9,11,0.15) 0%, rgba(9,9,11,0.35) 55%, rgba(9,9,11,0.92) 100%)";
  return trip.photo ? { backgroundImage: `${fade}, url("${trip.photo.url}")` } : { backgroundImage: `${fade}, ${coverGradient(trip.destination)}` };
}

/** The photo's credit, as its licence asks: the author, the licence, a link to the photo. */
export function PhotoCredit({ photo }: { photo: TripPhoto }) {
  const text = photo.spot ? `${photo.spot}. ${photo.credit}` : photo.credit;
  return photo.page ? (
    <a className="photo-credit" href={photo.page} target="_blank" rel="noopener noreferrer">
      {text}
    </a>
  ) : (
    <span className="photo-credit">{text}</span>
  );
}

const initials = (name: string) =>
  name
    .split(/\s+/)
    .map((w) => w[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();

/** Companions as overlapping initials, like a collaborator stack. */
export function Companions({ names }: { names: string[] }) {
  if (names.length === 0) return null;
  const shown = names.slice(0, 3);
  return (
    <span className="avatars" aria-label={`With ${names.join(", ")}`} title={names.join(", ")}>
      {shown.map((n) => (
        <span key={n} className="avatar" aria-hidden="true">
          {initials(n)}
        </span>
      ))}
      {names.length > shown.length && (
        <span className="avatar more" aria-hidden="true">
          +{names.length - shown.length}
        </span>
      )}
    </span>
  );
}

/** "In 35 days", "Day 3 of 10", "Ended 4 Jan". */
export function tripWhen(trip: Trip): string {
  if (trip.status === "ongoing") return `Day ${trip.day_number} of ${trip.days}`;
  if (trip.status === "finished") return `Ended ${day(trip.end)}`;
  if (trip.days_until === 1) return "Tomorrow";
  return `In ${trip.days_until} days`;
}

/** A trip on Travel's home: its cover, where, when and who. */
export function TripCard({ trip }: { trip: Trip }) {
  const nights = trip.days - 1;
  return (
    <li className="trip-card" style={coverStyle(trip)}>
      <span className="trip-card-chip">{tripWhen(trip)}</span>
      <span className="trip-card-body">
        <Link className="trip-card-link" to={`/travel/trips/${trip.id}`}>
          {trip.destination}
        </Link>
        <span className="trip-card-meta">
          {day(trip.start)} to {day(trip.end)} · {trip.days} {trip.days === 1 ? "day" : "days"}
          {nights > 0 && ` · ${nights} ${nights === 1 ? "night" : "nights"}`}
        </span>
        <span className="trip-card-foot">
          {trip.budget ? <span>Budget {formatMoney(trip.budget)}</span> : <span />}
          <Companions names={trip.companions} />
        </span>
      </span>
    </li>
  );
}

const sortKey = (b: Booking) => `${b.starts}T${b.at ?? b.segments[0]?.departs?.slice(11) ?? (b.kind === "hotel" ? "15:00" : "00:00")}`;

function untilLabel(iso: string, today: string): string {
  const n = daysBetween(today, iso);
  if (n <= 0) return "Today";
  if (n === 1) return "Tomorrow";
  return `In ${n} days`;
}

const KIND_WORD: Record<Booking["kind"], string> = {
  flight: "Flight",
  rail: "Train",
  hotel: "Check in",
  activity: "Plan",
};

function CopyRef({ reference }: { reference: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className="pass-ref">
      <span className="caption">Ref</span>
      <span className="num">{reference}</span>
      <button type="button" className="btn btn-small" onClick={() => void copy()} aria-label={`Copy booking reference ${reference}`}>
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="pass-field">
      <span className="caption">{label}</span>
      <span>{children}</span>
    </div>
  );
}

/** What comes next on the trip, as a boarding pass for a flight or train. */
export function NextUp({ detail }: { detail: TripDetail }) {
  const today = todayIso();
  const next = detail.bookings.filter((b) => b.scheduled && b.starts >= today).sort((a, b) => sortKey(a).localeCompare(sortKey(b)))[0];
  if (!next || detail.trip.status === "finished") return null;
  const word = KIND_WORD[next.kind];
  const first = next.segments[0];
  const last = next.segments[next.segments.length - 1];
  const travel = (next.kind === "flight" || next.kind === "rail") && first && last;
  return (
    <section className="next-pass" aria-label={`Next: ${word.toLowerCase()}`}>
      <div className="next-pass-band">
        <span>Next · {word}</span>
        <span>{untilLabel(next.starts, today)}</span>
      </div>
      <div className="next-pass-body">
        {travel ? (
          <div className="pass-route">
            <div>
              <span className="pass-code">{first.origin ?? "?"}</span>
              <span className="pass-time num">{first.departs?.slice(11, 16) ?? ""}</span>
            </div>
            <div className="pass-line" aria-hidden="true">
              <span />
              <span className="caption">
                {next.segments.length === 1 ? "direct" : `${next.segments.length - 1} stop${next.segments.length > 2 ? "s" : ""}`}
              </span>
            </div>
            <div className="pass-end">
              <span className="pass-code">{last.destination ?? "?"}</span>
              <span className="pass-time num">{last.arrives?.slice(11, 16) ?? ""}</span>
            </div>
          </div>
        ) : (
          <div className="pass-title">
            <strong>{next.kind === "hotel" ? (next.hotel ?? next.title) : next.title}</strong>
            {next.address && <span className="caption">{next.address}</span>}
          </div>
        )}
        <div className="pass-fields">
          {travel && first.number && <Field label={next.kind === "rail" ? "Train" : "Flight"}>{first.number}</Field>}
          <Field label="Date">{day(next.starts)}</Field>
          {next.at && <Field label="Time">{next.at}</Field>}
          {next.kind === "hotel" && next.check_out && <Field label="Check out">{day(next.check_out)}</Field>}
          {next.booked_via && <Field label="Booked via">{next.booked_via}</Field>}
          {!next.booked_via && next.provider && <Field label="With">{next.provider}</Field>}
        </div>
        {next.reference && <CopyRef reference={next.reference} />}
      </div>
    </section>
  );
}

/** Where they're staying: the stay on now or next, and how many nights are covered. */
export function StayCard({ detail, onAdd }: { detail: TripDetail; onAdd: () => void }) {
  const today = todayIso();
  const nights = Math.max(detail.trip.days - 1, 0);
  if (nights === 0 || detail.trip.status === "finished") return null;
  const covered = nights - detail.ready.nights_without_stay.length;
  const stays = detail.bookings.filter((b) => b.kind === "hotel" && b.check_in).sort((a, b) => (a.check_in ?? "").localeCompare(b.check_in ?? ""));
  const stay = stays.find((b) => (b.check_out ?? b.check_in ?? "") > today) ?? stays[0];
  return (
    <section className="stay-card" aria-label="Where you're staying">
      <span className="stay-icon" aria-hidden="true">
        🏨
      </span>
      <span className="wrap">
        <span className="caption">
          Stay · {covered} of {nights} {nights === 1 ? "night" : "nights"} booked
        </span>
        {stay ? (
          <>
            <strong>{stay.hotel ?? stay.title}</strong>
            <span className="caption">
              {stay.check_in && day(stay.check_in)}
              {stay.check_out && ` to ${day(stay.check_out)}`}
            </span>
          </>
        ) : (
          <strong>Nowhere to stay yet</strong>
        )}
      </span>
      {covered < nights && (
        <button type="button" className="btn btn-small" onClick={onAdd}>
          Add a place to stay
        </button>
      )}
    </section>
  );
}

/** A ring showing how much is done, with the share inside. */
export function Ring({ done, total, label }: { done: number; total: number; label: string }) {
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;
  return (
    <span className="ring" style={{ "--ring": `${percent}%` } as CSSProperties} role="img" aria-label={label}>
      <span className="ring-inner">{percent}%</span>
    </span>
  );
}

/** The trip's money at a glance: spent so far against the budget, and what's booked. */
export function MoneyCard({ detail, onOpen }: { detail: TripDetail; onOpen: () => void }) {
  const s = detail.spending;
  const budget = detail.trip.budget;
  const percent = Math.min(s.percent ?? 0, 100);
  return (
    <section className="card trip-money" aria-labelledby="trip-money">
      <div className="card-head">
        <h2 id="trip-money">Money</h2>
        <button type="button" className="btn btn-ghost btn-small" onClick={onOpen}>
          Details
        </button>
      </div>
      <p className="trip-money-figure">{formatMoney(s.spent)}</p>
      {budget && (
        <div className={`meter${(s.percent ?? 0) > 100 ? " meter-over" : ""}`} aria-hidden="true">
          <span style={{ width: `${percent}%` }} />
        </div>
      )}
      <p className="caption">
        {budget ? `spent of ${formatMoney(budget)}` : "spent so far · no budget yet"}
        {detail.booked && ` · ${formatMoney(detail.booked)} booked`}
      </p>
    </section>
  );
}
