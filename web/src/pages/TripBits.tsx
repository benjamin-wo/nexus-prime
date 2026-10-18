import { useQuery } from "@tanstack/react-query";
import { type CSSProperties, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Booking, type Me, type Trip, type TripPhoto } from "../api";
import { formatMoney, formatShortDate } from "../format";
import { PlaceLine } from "./TripPlaces";

export const day = (iso: string) => formatShortDate(iso, "UTC");

/** Today in the browser's own time zone, as YYYY-MM-DD. */
export const todayIso = () => new Date().toLocaleDateString("en-CA");

/** A gradient for trips without a photo yet, the same for the same place. */
export function coverGradient(destination: string): string {
  let hash = 0;
  for (const ch of destination.toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  const hue = hash % 360;
  return `linear-gradient(160deg, hsl(${hue} 32% 22%) 0%, hsl(${(hue + 40) % 360} 24% 13%) 60%, #0f0f12 100%)`;
}

/** The cover behind a trip's header or card: its photo, or a gradient. */
export function coverStyle(trip: Pick<Trip, "photo" | "destination">): CSSProperties {
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
export function tripWhen(trip: Pick<Trip, "status" | "day_number" | "days" | "end" | "days_until">): string {
  if (trip.status === "ongoing") return trip.day_number ? `Day ${trip.day_number} of ${trip.days}` : "On now";
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

export const sortKey = (b: Pick<Booking, "starts" | "at" | "segments" | "kind">) => `${b.starts}T${b.at ?? b.segments[0]?.departs?.slice(11) ?? (b.kind === "hotel" ? "15:00" : "00:00")}`;

const words = (text: string) =>
  text
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);

/** Whether two words are the same allowing one letter's difference in longer ones
 * ("Cellar" and "Celler"). */
function alike(a: string, b: string): boolean {
  if (a === b) return true;
  if (Math.min(a.length, b.length) < 5 || Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  let j = 0;
  let edits = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      i += 1;
      j += 1;
      continue;
    }
    edits += 1;
    if (edits > 1) return false;
    if (a.length > b.length) i += 1;
    else if (b.length > a.length) j += 1;
    else {
      i += 1;
      j += 1;
    }
  }
  return edits + (a.length - i) + (b.length - j) <= 1;
}

/** An address that only repeats the entry's own name ("El Cellar" under "Girona ·
 * Sa Tuna · El Celler"): every word of it is already in the title. */
export function repeatsTitle(text: string, title: string): boolean {
  const mine = words(text);
  const theirs = words(title);
  return mine.length > 0 && mine.every((w) => theirs.some((t) => alike(w, t)));
}

/** A note that only says which day it is ("Day 3"), which the itinerary already shows. */
export const onlyNamesDay = (note: string) => /^\s*day\s*\d{1,2}\s*\.?\s*$/i.test(note);

type Leg = Booking["segments"][number];

/** A flight's or train's legs that leave on a day, and those that land on it. */
export const leavingOn = (b: Pick<Booking, "segments">, iso: string): Leg[] => b.segments.filter((s) => s.departs?.slice(0, 10) === iso);
export const landingOn = (b: Pick<Booking, "segments">, iso: string): Leg[] => b.segments.filter((s) => s.arrives?.slice(0, 10) === iso);

/** A flight or train on a day it only lands: shown as its arrival. */
export const landsOnly = (b: Pick<Booking, "kind" | "segments">, iso: string) =>
  (b.kind === "flight" || b.kind === "rail") && leavingOn(b, iso).length === 0 && landingOn(b, iso).length > 0;

/** "08:25 → 16:05", with the day when a leg lands on another one. Times are local
 * and always 24-hour, as on a boarding pass. */
export function legTimes(departs: string | null, arrives: string | null): string {
  const time = (iso: string) => iso.slice(11, 16);
  if (!departs) return arrives ? `arrives ${time(arrives)}` : "";
  if (!arrives) return `departs ${time(departs)}`;
  const nextDay = arrives.slice(0, 10) !== departs.slice(0, 10);
  return `${time(departs)} → ${time(arrives)}${nextDay ? ` (${day(arrives.slice(0, 10))})` : ""}`;
}

export function useHome(): string {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/me") });
  return me.data?.user.home_currency ?? "";
}

/** Where it was booked and its reference, which the user can copy for the counter or the app. */
export function BookedWith({ booking }: { booking: Booking }) {
  const [copied, setCopied] = useState(false);
  if (!booking.reference && !booking.booked_via) return null;
  async function copy() {
    try {
      await navigator.clipboard.writeText(booking.reference ?? "");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <span className="caption">
      {booking.booked_via && `Booked on ${booking.booked_via}`}
      {booking.booked_via && booking.reference && " · "}
      {booking.reference && (
        <>
          Ref <strong className="num">{booking.reference}</strong>{" "}
          <button type="button" className="link-btn" onClick={() => void copy()} aria-label={`Copy reference ${booking.reference}`}>
            {copied ? "Copied" : "Copy"}
          </button>
        </>
      )}
      <br />
    </span>
  );
}

export function BookingLines({ booking, noTime = false }: { booking: Booking; noTime?: boolean }) {
  return (
    <>
      <KindLines booking={booking} noTime={noTime} />
      <PlaceLine booking={booking} />
      <BookedWith booking={booking} />
    </>
  );
}

function KindLines({ booking, noTime }: { booking: Booking; noTime: boolean }) {
  // Nothing the entry's title or day already says.
  const note = booking.note && !onlyNamesDay(booking.note) && (
    <span className="caption">
      {booking.note}
      <br />
    </span>
  );
  if (booking.kind === "activity") {
    const address = booking.address && !repeatsTitle(booking.address, booking.title) ? booking.address : null;
    return (
      <>
        <span className="caption">
          {booking.at && !noTime && `${booking.at} · `}
          {address}
          {((booking.at && !noTime) || address) && <br />}
        </span>
        {note}
      </>
    );
  }
  if (booking.kind === "hotel") {
    return (
      <>
        <span className="caption">
          {booking.check_in && `Check in ${day(booking.check_in)}`}
          {booking.check_out && ` · out ${day(booking.check_out)}`}
          {booking.address && ` · ${booking.address}`}
          <br />
        </span>
        {note}
      </>
    );
  }
  return (
    <>
      {booking.segments.map((s, n) => (
        <span key={n} className="caption">
          {/* One leg is already named by the title; more get their own number and route. */}
          {booking.segments.length > 1 && `${[s.number, [s.origin, s.destination].filter(Boolean).join(" → ")].filter(Boolean).join(" ")} · `}
          {legTimes(s.departs, s.arrives)}
          <br />
        </span>
      ))}
    </>
  );
}

/** An entry's own link, to book or read more. */
export function OpenLink({ booking }: { booking: Booking }) {
  if (!booking.link) return null;
  return (
    <a className="caption entry-link" href={booking.link} target="_blank" rel="noopener noreferrer" aria-label={`Open the link for ${booking.title}`}>
      Open link ↗
    </a>
  );
}
