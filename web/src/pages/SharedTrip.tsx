import { useQuery } from "@tanstack/react-query";
import { type CSSProperties, useEffect } from "react";
import { useParams } from "react-router-dom";

import { api, ApiError, type SharedBooking, type SharedTrip } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { formatShortDate } from "../format";
import { PhotoCredit, coverStyle, legTimes, stopOfDay, todayIso, tripWhen } from "./TripBits";

const DAY_MS = 86400000;
const day = (iso: string) => formatShortDate(iso, "UTC");
const isoDay = (t: number) => new Date(t).toISOString().slice(0, 10);
const longDay = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(iso));
const KIND_ICON: Record<SharedBooking["kind"], IconName> = { flight: "flight", hotel: "stay", rail: "train", activity: "place" };

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

/** One plan or booking on a day: the time (or the booking's line icon) in a 48px column, then
 * the title with one quiet line under it, then its Maps link. */
function Entry({ booking, iso }: { booking: SharedBooking; iso: string }) {
  if (booking.kind === "hotel") {
    const name = booking.hotel ?? booking.title;
    const out = booking.check_out === iso && booking.check_in !== iso;
    return (
      <li className="shared-row">
        <span className="shared-lead">
          <Icon name="stay" size={18} />
        </span>
        <span className="shared-main">
          <strong>{name}</strong>
          {!out && (booking.check_out || booking.address) && (
            <span className="caption">
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
      <li className="shared-row">
        <span className="shared-lead">
          <Icon name={KIND_ICON[booking.kind]} size={18} />
        </span>
        <span className="shared-main">
          <strong>
            {booking.title}
            {booking.provider && <span className="caption"> · {booking.provider}</span>}
          </strong>
          {booking.segments.map((s, n) => (
            <span key={n} className="caption">
              {booking.segments.length > 1 && `${[s.number, [s.origin, s.destination].filter(Boolean).join(" → ")].filter(Boolean).join(" ")} · `}
              {legTimes(s.departs, s.arrives)}
            </span>
          ))}
        </span>
      </li>
    );
  }
  const meta = [booking.category, booking.address].filter(Boolean).join(" · ");
  return (
    <li className="shared-row">
      <span className="shared-lead shared-time">{booking.at}</span>
      <span className="shared-main">
        <strong>{booking.title}</strong>
        {meta && <span className="caption">{meta}</span>}
      </span>
      {booking.address && <MapsLink query={`${booking.title}, ${booking.address}`} name={booking.title} />}
    </li>
  );
}

/** What an empty day says: a day a hidden booking falls on is a travel day, not a free one. */
export function emptyDayText(iso: string, hiddenDays: readonly string[]): string {
  return hiddenDays.includes(iso) ? "Travel day" : "Free day";
}

/** The trip day by day, as anyone with the link sees it: nothing here can be changed. */
export function SharedDays({ trip }: { trip: SharedTrip }) {
  const today = todayIso();
  // Each day as the itinerary has it: the server sends them in that order.
  const sorted = [...trip.bookings].sort((a, b) => a.starts.localeCompare(b.starts));
  const stays = sorted.filter((b) => b.kind === "hotel" && b.check_in && b.check_out);
  const days = new Set<string>();
  for (let t = Date.parse(trip.start); t <= Date.parse(trip.end); t += DAY_MS) days.add(isoDay(t));
  for (const b of sorted) days.add(b.starts);
  // A day only a hidden booking falls on (the day before, say) still shows, as a travel day.
  const hiddenDays = trip.show_bookings ? [] : (trip.hidden_days ?? []);
  for (const d of hiddenDays) days.add(d);
  const dayNumber = (iso: string) => Math.round((Date.parse(iso) - Date.parse(trip.start)) / DAY_MS) + 1;
  const inTrip = (iso: string) => iso >= trip.start && iso <= trip.end;

  // While the trip is on, open at today.
  useEffect(() => {
    if (trip.status === "ongoing") document.getElementById(`day-${today}`)?.scrollIntoView({ block: "start" });
  }, [trip.status, today]);

  return (
    <section className="shared-plan" aria-labelledby="shared-plan">
      <h2 id="shared-plan" className="sr-only">
        The plan
      </h2>
      {[...days].sort().map((d) => {
        const entries = sorted.filter((b) => b.starts === d);
        const outs = stays.filter((b) => b.check_out === d && b.starts !== d);
        const staying = stays.filter((b) => nightsOf(b).includes(d));
        const n = dayNumber(d);
        const meta = inTrip(d) ? `Day ${n} · ${longDay(d)}` : longDay(d);
        // The day's own name, else the stop it falls in.
        const title = trip.day_labels[d] || stopOfDay(trip.stops ?? [], d)?.name;
        const empty = entries.length === 0 && outs.length === 0 && staying.length === 0;
        return (
          <div key={d} id={`day-${d}`} className="shared-day" aria-current={d === today ? "date" : undefined}>
            <h3 className="shared-day-head">
              <span className="shared-day-meta">
                {meta}
                {d === today && (
                  <>
                    {" "}
                    <span className="badge badge-in">Today</span>
                  </>
                )}
              </span>
              {title && (
                <>
                  {" "}
                  <span className="accent-serif shared-day-title">{title}</span>
                </>
              )}
            </h3>
            {staying.map((b) => (
              <p key={`${b.starts}-${b.title}`} className="shared-staying caption">
                <Icon name="stay" size={16} className="icon-inline" />
                Staying at {b.hotel ?? b.title}
              </p>
            ))}
            {(outs.length > 0 || entries.length > 0) && (
              <ul className="shared-rows" aria-label={meta}>
                {outs.map((b, i) => (
                  <Entry key={`out-${i}`} booking={b} iso={d} />
                ))}
                {entries.map((b, i) => (
                  <Entry key={i} booking={b} iso={d} />
                ))}
              </ul>
            )}
            {empty && <p className="shared-empty">{emptyDayText(d, hiddenDays)}</p>}
          </div>
        );
      })}
      <p className="caption">Times are local.</p>
    </section>
  );
}

/** The trip's photo for the cover, with no fade over it; the gradient fallback keeps its own. */
const heroStyle = (trip: Pick<SharedTrip, "photo" | "destination">): CSSProperties =>
  trip.photo ? { backgroundImage: `url("${trip.photo.url}")` } : coverStyle(trip);

/** "Tokyo, Kyoto and Osaka": the stops' places in order, each once. Nothing for no stops, or one
 * that is only the destination again. */
export function stopNames(stops: readonly { name: string }[], destination: string): string {
  const names = stops.map((s) => s.name.trim()).filter((name, i, all) => name && all.indexOf(name) === i);
  if (names.length === 0 || (names.length === 1 && names[0].toLowerCase() === destination.trim().toLowerCase())) return "";
  return names.length === 1 ? names[0] : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
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
  const stops = trip ? stopNames(trip.stops ?? [], trip.destination) : "";
  return (
    <main className="shared-page">
      <div className="shared-col">
        <header className="trip-hero shared-hero">
          <div className={`trip-hero-photo${trip?.photo ? "" : " no-photo"}`} style={trip ? heroStyle(trip) : undefined}>
            <div className="trip-hero-bar">
              <span className="trip-chip shared-chip">Shared with you · read only</span>
            </div>
            {trip?.photo && (
              <div className="trip-hero-credit">
                <PhotoCredit photo={trip.photo} />
              </div>
            )}
          </div>
          <div className="trip-hero-body">
            <h1 className="accent-serif shared-title">{trip?.destination ?? "A shared trip"}</h1>
            {trip && (
              <p className="trip-hero-meta">
                <span>
                  {day(trip.start)} – {day(trip.end)}
                  {stops && ` · ${stops}`}
                </span>
                <span className="pill">{tripWhen(trip)}</span>
              </p>
            )}
          </div>
        </header>
        <div className="shared-body">
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
          {trip && !trip.show_bookings && (
            <p className="shared-note" role="note">
              Bookings aren't shown on this link.
            </p>
          )}
          {trip && <SharedDays trip={trip} />}
          <p className="caption shared-foot">Shared from Nexus. No money, booking references, notes or travellers are shown.</p>
        </div>
      </div>
    </main>
  );
}
