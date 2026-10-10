import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { api, ApiError, type SharedBooking, type SharedTrip } from "../api";
import { formatShortDate } from "../format";
import { PhotoCredit, coverStyle, legTimes, sortKey, todayIso, tripWhen } from "./TripBits";

const DAY_MS = 86400000;
const day = (iso: string) => formatShortDate(iso, "UTC");
const isoDay = (t: number) => new Date(t).toISOString().slice(0, 10);
const longDay = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso));
const KIND_ICON: Record<SharedBooking["kind"], string> = { flight: "✈️", hotel: "🏨", rail: "🚆", activity: "📍" };

/** A Google Maps search for the place, opened in a new tab. The page's referrer policy
 * keeps the link itself from going with it. */
function MapsLink({ query, name }: { query: string; name: string }) {
  return (
    <a
      className="btn btn-ghost btn-small"
      href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`Open ${name} in Google Maps`}
    >
      Maps
    </a>
  );
}

function nightsOf(b: SharedBooking): string[] {
  const nights: string[] = [];
  if (!b.check_in || !b.check_out) return nights;
  for (let t = Date.parse(b.check_in) + DAY_MS; t < Date.parse(b.check_out); t += DAY_MS) nights.push(isoDay(t));
  return nights;
}

function Entry({ booking, iso, stop }: { booking: SharedBooking; iso: string; stop: number | null }) {
  if (booking.kind === "hotel") {
    const name = booking.hotel ?? booking.title;
    const out = booking.check_out === iso && booking.check_in !== iso;
    return (
      <li className="timeline-strip">
        <span aria-hidden="true">🏨</span>
        <span className="wrap">
          <strong>{name}</strong>
          {!out && (
            <span className="caption">
              <br />
              {booking.check_out && `Until ${day(booking.check_out)}`}
              {booking.address && `${booking.check_out ? " · " : ""}${booking.address}`}
            </span>
          )}
        </span>
        <span className={`badge ${out ? "badge-pending" : "badge-in"}`}>{out ? "Check out" : "Check in"}</span>
        {!out && <MapsLink query={[name, booking.address].filter(Boolean).join(", ")} name={name} />}
      </li>
    );
  }
  if (booking.kind === "flight" || booking.kind === "rail") {
    return (
      <li className="timeline-strip">
        <span aria-hidden="true">{KIND_ICON[booking.kind]}</span>
        <span className="wrap">
          <strong>{booking.title}</strong>
          {booking.provider && <span className="caption"> · {booking.provider}</span>}
          {booking.segments.map((s, n) => (
            <span key={n} className="caption">
              <br />
              {booking.segments.length > 1 && `${[s.number, [s.origin, s.destination].filter(Boolean).join(" → ")].filter(Boolean).join(" ")} · `}
              {legTimes(s.departs, s.arrives)}
            </span>
          ))}
        </span>
      </li>
    );
  }
  return (
    <li className="timeline-stop">
      <span className="stop-number" aria-hidden="true">
        {stop}
      </span>
      <span className="wrap">
        <strong>{booking.title}</strong>
        {booking.at && <span className="time-pill">{booking.at}</span>}
        {booking.category && <span className="caption"> · {booking.category}</span>}
        {booking.address && (
          <span className="caption">
            <br />
            {booking.address}
          </span>
        )}
      </span>
      {booking.address && <MapsLink query={`${booking.title}, ${booking.address}`} name={booking.title} />}
    </li>
  );
}

/** The trip day by day, as anyone with the link sees it: nothing here can be changed. */
function SharedDays({ trip }: { trip: SharedTrip }) {
  const today = todayIso();
  const sorted = [...trip.bookings].sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  const stays = sorted.filter((b) => b.kind === "hotel" && b.check_in && b.check_out);
  const days = new Set<string>();
  for (let t = Date.parse(trip.start); t <= Date.parse(trip.end); t += DAY_MS) days.add(isoDay(t));
  for (const b of sorted) days.add(b.starts);
  const dayNumber = (iso: string) => Math.round((Date.parse(iso) - Date.parse(trip.start)) / DAY_MS) + 1;
  const inTrip = (iso: string) => iso >= trip.start && iso <= trip.end;

  // While the trip is on, open at today.
  useEffect(() => {
    if (trip.status === "ongoing") document.getElementById(`day-${today}`)?.scrollIntoView({ block: "start" });
  }, [trip.status, today]);

  return (
    <section className="card" aria-labelledby="shared-plan">
      <div className="card-head">
        <h2 id="shared-plan">The plan</h2>
      </div>
      {[...days].sort().map((d) => {
        const entries = sorted.filter((b) => b.starts === d);
        const outs = stays.filter((b) => b.check_out === d && b.starts !== d);
        const staying = stays.filter((b) => nightsOf(b).includes(d));
        const n = dayNumber(d);
        const heading = inTrip(d) ? `Day ${n} · ${longDay(d)}` : longDay(d);
        const label = trip.day_labels[d];
        const empty = entries.length === 0 && outs.length === 0 && staying.length === 0;
        let stop = 0;
        return (
          <div key={d} id={`day-${d}`} className="itinerary-day" aria-current={d === today ? "date" : undefined}>
            <div className="day-rail" aria-hidden="true">
              <span className={`day-dot ${!inTrip(d) ? "day-dot-out" : empty ? "day-dot-empty" : "day-dot-planned"}`}>{inTrip(d) ? n : "·"}</span>
              <span className="day-line" />
            </div>
            <div className="day-body">
              <div className="day-head">
                <h3>{heading}</h3>
                {label && <span className="pill">{label}</span>}
                {d === today && <span className="badge badge-in">Today</span>}
              </div>
              {staying.map((b) => (
                <p key={`${b.starts}-${b.title}`} className="caption">
                  <span aria-hidden="true">🏨</span> Staying at {b.hotel ?? b.title}
                </p>
              ))}
              <ul className="timeline" aria-label={heading}>
                {outs.map((b, i) => (
                  <Entry key={`out-${i}`} booking={b} iso={d} stop={null} />
                ))}
                {entries.map((b, i) => {
                  if (b.kind === "activity") stop += 1;
                  return <Entry key={i} booking={b} iso={d} stop={b.kind === "activity" ? stop : null} />;
                })}
              </ul>
              {empty && <p className="caption">Nothing planned yet</p>}
            </div>
          </div>
        );
      })}
      <p className="caption">Times are local.</p>
    </section>
  );
}

/** A trip's read-only page, for whoever its link was sent to. No sign-in, and only the
 * plan: days, times and places. */
export function SharedTripPage() {
  const { token = "" } = useParams();
  const shared = useQuery({
    queryKey: ["shared-trip", token],
    queryFn: () => api<SharedTrip>(`/shared/trips/${encodeURIComponent(token)}`),
    retry: false,
  });
  const trip = shared.data;

  useEffect(() => {
    if (trip) document.title = `${trip.destination} · Nexus`;
  }, [trip]);

  const gone = shared.error instanceof ApiError && shared.error.status === 404;
  return (
    <main className="shared-page">
      <div className="trip-page">
        <header className="trip-cover trip-cover-compact" style={trip ? coverStyle(trip) : undefined}>
          <div className="trip-cover-top">
            <span className="cover-button shared-badge">Shared with you · read only</span>
          </div>
          <div className="trip-cover-main">
            <h1>{trip?.destination ?? "A shared trip"}</h1>
            {trip && (
              <p className="trip-meta">
                <span>
                  {day(trip.start)} – {day(trip.end)} · {trip.days} {trip.days === 1 ? "day" : "days"}
                </span>
                <span className="pill">{tripWhen(trip)}</span>
              </p>
            )}
            {trip?.photo && <PhotoCredit photo={trip.photo} />}
          </div>
        </header>
        {shared.isLoading && <p className="state">Loading…</p>}
        {shared.isError && (
          <p className="state error-text" role="alert">
            {gone
              ? "This link doesn't work any more. It may have been stopped or replaced: ask whoever sent it for a new one."
              : shared.error instanceof Error
                ? shared.error.message
                : "Couldn't load this trip. Try again in a minute."}
          </p>
        )}
        {trip && <SharedDays trip={trip} />}
        <p className="caption shared-foot">Planned with Nexus. Prices, booking references and notes stay private.</p>
      </div>
    </main>
  );
}
