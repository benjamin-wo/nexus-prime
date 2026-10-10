import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Booking, type TripDetail, type TripWeather } from "../api";
import { formatShortDate } from "../format";
import { sortKey, todayIso } from "./TripBits";
import { degrees, icon } from "./TripExtras";

const DAY_MS = 86400000;
const shortDay = (iso: string) => formatShortDate(iso, "UTC");
const longDay = (iso: string) =>
  new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" }).format(new Date(iso));
const timeOf = (iso: string | null) => (iso && iso.length > 11 ? iso.slice(11, 16) : null);

/** A Google Maps search for the place, which opens the Maps app on a phone. */
const mapsLink = (query: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;

function tripDays(start: string, end: string): string[] {
  const days: string[] = [];
  for (let t = Date.parse(start); t <= Date.parse(end); t += DAY_MS) days.push(new Date(t).toISOString().slice(0, 10));
  return days;
}

function Copy({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button type="button" className="btn btn-small" onClick={() => void copy()} aria-label={label}>
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** The booking reference, big enough to read out at a counter, with a copy button. */
function Reference({ booking }: { booking: Booking }) {
  if (!booking.reference) return booking.booked_via ? <span className="caption">Booked on {booking.booked_via}</span> : null;
  return (
    <div className="pass-ref">
      <span className="caption">Ref</span>
      <span className="num">{booking.reference}</span>
      {booking.booked_via && <span className="caption">{booking.booked_via}</span>}
      <Copy text={booking.reference} label={`Copy booking reference ${booking.reference}`} />
    </div>
  );
}

/** Where it is, with a link to directions and a copy button for a taxi driver. */
function Address({ name, address }: { name: string; address: string | null }) {
  return (
    <div className="today-address">
      {address && <span>{address}</span>}
      <span className="quick">
        <a className="btn btn-small" href={mapsLink(address ? `${name}, ${address}` : name)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${name} in Maps`}>
          Open in Maps
        </a>
        {address && <Copy text={address} label={`Copy the address of ${name}`} />}
      </span>
    </div>
  );
}

function Plan({ booking, day, tonight }: { booking: Booking; day: string; tonight: boolean }) {
  if (booking.kind === "flight" || booking.kind === "rail") {
    const first = booking.segments[0];
    const last = booking.segments[booking.segments.length - 1];
    return (
      <li className="today-plan">
        <span className="time-pill">{timeOf(first?.departs ?? null) ?? booking.at ?? "Today"}</span>
        <div className="today-plan-body">
          <strong>
            {booking.kind === "flight" ? "✈️" : "🚆"} {[first?.origin, last?.destination].filter(Boolean).join(" → ") || booking.title}
          </strong>
          <span className="caption">
            {[booking.provider, ...booking.segments.map((s) => s.number)].filter(Boolean).join(" · ")}
            {timeOf(last?.arrives ?? null) && ` · arrives ${timeOf(last?.arrives ?? null)}`}
          </span>
          <Reference booking={booking} />
        </div>
      </li>
    );
  }
  if (booking.kind === "hotel") {
    const name = booking.hotel ?? booking.title;
    const out = booking.check_out === day && booking.check_in !== day;
    return (
      <li className="today-plan">
        <span className="time-pill">{out ? "Check out" : "Check in"}</span>
        <div className="today-plan-body">
          <strong>🏨 {name}</strong>
          {/* Its address and reference are under Tonight already. */}
          {!out && !tonight && <Address name={name} address={booking.address} />}
          {!out && !tonight && <Reference booking={booking} />}
        </div>
      </li>
    );
  }
  return (
    <li className="today-plan">
      <span className="time-pill">{booking.at ?? "Any time"}</span>
      <div className="today-plan-body">
        <strong>{booking.title}</strong>
        {booking.category && <span className="caption">{booking.category}</span>}
        {booking.note && <span className="caption">{booking.note}</span>}
        {(booking.address || booking.place_id) && <Address name={booking.title} address={booking.address} />}
        <Reference booking={booking} />
      </div>
    </li>
  );
}

/** One day of the trip on one screen, for use while travelling: the day's weather,
 * where they're sleeping tonight, the day's plans in time order with addresses and
 * booking references, and the first thing tomorrow. */
export function TodayView({ detail }: { detail: TripDetail }) {
  const trip = detail.trip;
  const days = tripDays(trip.start, trip.end);
  const today = todayIso();
  const [day, setDay] = useState(days.includes(today) ? today : days[0]);
  const weather = useQuery({
    queryKey: ["trip-weather", trip.id, trip.start, trip.end, trip.destination],
    queryFn: () => api<TripWeather | null>(`/travel/trips/${trip.id}/weather`),
    staleTime: 60 * 60 * 1000,
    enabled: trip.status !== "finished",
  });
  const index = days.indexOf(day);
  const scheduled = detail.bookings.filter((b) => b.scheduled).sort((a, b) => sortKey(a).localeCompare(sortKey(b)));
  const stays = scheduled.filter((b) => b.kind === "hotel" && b.check_in);
  const outs = stays.filter((b) => b.check_out === day && b.starts !== day);
  const plans = [...outs, ...scheduled.filter((b) => b.starts === day)];
  const tonight = stays.find((b) => (b.check_in ?? "") <= day && (b.check_out ?? b.check_in ?? "") > day);
  const next = index >= 0 && index < days.length - 1 ? scheduled.find((b) => b.starts === days[index + 1]) : undefined;
  const forecast = weather.data?.days.find((d) => d.day === day);
  const label = trip.day_labels?.[day];
  const lastNight = day === trip.end;

  return (
    <section className="card today-view" aria-labelledby="today-title">
      <div className="today-head">
        <button type="button" className="btn btn-small" disabled={index <= 0} onClick={() => setDay(days[index - 1])} aria-label="Day before">
          ‹
        </button>
        <div className="today-title">
          <span className="caption">
            {day === today ? "Today · " : ""}Day {index + 1} of {days.length}
            {label && ` · ${label}`}
          </span>
          <h2 id="today-title">{longDay(day)}</h2>
        </div>
        <button type="button" className="btn btn-small" disabled={index >= days.length - 1} onClick={() => setDay(days[index + 1])} aria-label="Day after">
          ›
        </button>
      </div>

      {forecast && (
        <p className="today-weather">
          <span className="weather-icon" role="img" aria-label={forecast.summary ?? "Weather"}>
            {icon(forecast.code)}
          </span>
          <span className="num">
            {degrees(forecast.high)} <span className="caption">{degrees(forecast.low)}</span>
          </span>
          {forecast.rain !== null && <span className={`caption${forecast.rain >= 50 ? " is-wet" : ""}`}>{forecast.rain}% rain</span>}
          {weather.data?.kind === "typical" && <span className="caption">typical for the date</span>}
        </p>
      )}

      <div className="today-section">
        <h3>Tonight</h3>
        {tonight ? (
          <div className="today-stay">
            <strong>🏨 {tonight.hotel ?? tonight.title}</strong>
            <Address name={tonight.hotel ?? tonight.title} address={tonight.address} />
            {tonight.check_out && <span className="caption">Check out {shortDay(tonight.check_out)}</span>}
            <Reference booking={tonight} />
          </div>
        ) : (
          <p className="caption">{lastNight ? "Last day of the trip." : "Nowhere booked for tonight yet."}</p>
        )}
      </div>

      <div className="today-section">
        <h3>Plans</h3>
        {plans.length === 0 ? (
          <p className="caption">Nothing planned. A free day.</p>
        ) : (
          <ol className="today-plans" aria-label={`Plans for ${longDay(day)}`}>
            {plans.map((b) => (
              <Plan key={`${b.id}-${b.starts === day ? "in" : "out"}`} booking={b} day={day} tonight={b.id === tonight?.id} />
            ))}
          </ol>
        )}
      </div>

      {next && (
        <p className="caption today-next">
          Tomorrow first: <strong>{next.kind === "hotel" ? `check in at ${next.hotel ?? next.title}` : next.title}</strong>
          {(timeOf(next.segments[0]?.departs ?? null) ?? next.at) && ` at ${timeOf(next.segments[0]?.departs ?? null) ?? next.at}`}
        </p>
      )}
    </section>
  );
}
