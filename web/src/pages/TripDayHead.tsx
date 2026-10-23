import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Booking, type Trip, type TripWeather } from "../api";
import { Icon } from "../components/Icon";
import { formatShortDate } from "../format";
import { degrees, WeatherIcon } from "./TripExtras";

/** What a day's panel on the Plan tab says about the day beyond its plans: the weather on
 * one line and the night's stay as a strip (``DayWeather``, ``StayStrip``); and the pieces
 * those share with a plan's open row: a Google Maps link and a copy button. */

const shortDay = (iso: string) => formatShortDate(iso, "UTC");

/** A Google Maps search for the place, which opens the Maps app on a phone. */
const mapsLink = (query: string) => `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;

function Copy({ text, label, children = "Copy" }: { text: string; label: string; children?: string }) {
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
    <button type="button" className="btn btn-soft btn-small" onClick={() => void copy()} aria-label={label}>
      {copied ? "Copied" : children}
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

/** A link to directions and, with an address, a copy button for a taxi driver. */
export function PlaceActions({ name, address, copyText = "Copy" }: { name: string; address: string | null; copyText?: string }) {
  return (
    <span className="quick">
      <a className="btn btn-soft btn-small" href={mapsLink(address ? `${name}, ${address}` : name)} target="_blank" rel="noopener noreferrer" aria-label={`Open ${name} in Maps`}>
        Maps
      </a>
      {address && (
        <Copy text={address} label={`Copy the address of ${name}`}>
          {copyText}
        </Copy>
      )}
    </span>
  );
}

/** The trip's weather by day: the forecast once it reaches the trip, before that the same
 * dates in recent years. Nothing for a finished trip. */
export function useTripWeather(trip: Trip): TripWeather | null | undefined {
  return useQuery({
    queryKey: ["trip-weather", trip.id, trip.start, trip.end, trip.destination],
    queryFn: () => api<TripWeather | null>(`/travel/trips/${trip.id}/weather`),
    staleTime: 60 * 60 * 1000,
    enabled: trip.status !== "finished",
  }).data;
}

/** One day's weather on a line: the picture, high and low, the chance of rain. */
export function DayWeather({ weather, day }: { weather: TripWeather | null | undefined; day: string }) {
  const forecast = weather?.days.find((d) => d.day === day);
  if (!weather || !forecast) return null;
  return (
    <p className="day-weather">
      <WeatherIcon code={forecast.code} summary={forecast.summary} size={20} />
      <span className="num">
        {degrees(forecast.high)} <span className="caption">{degrees(forecast.low)}</span>
      </span>
      {forecast.rain !== null && <span className={`caption${forecast.rain >= 50 ? " is-wet" : ""}`}>{forecast.rain}% rain</span>}
      {weather.kind === "typical" && <span className="caption">typical for the date</span>}
    </p>
  );
}

/** Where they sleep that night, on one line: the hotel with a link to directions and a
 * copy button for its address. Its address, check-out day and booking reference are
 * under a fold, so the strip stays small on a phone. */
export function StayStrip({ booking }: { booking: Booking }) {
  const name = booking.hotel ?? booking.title;
  return (
    <div className="day-stay">
      <div className="day-stay-row">
        <span className="day-stay-name">
          <Icon name="stay" size={16} className="icon-inline" />
          <strong>{name}</strong>
        </span>
        <PlaceActions name={name} address={booking.address} copyText="Copy address" />
      </div>
      <details className="day-stay-more">
        <summary>Address and booking</summary>
        <div className="day-stay-body">
          {booking.address && <span>{booking.address}</span>}
          {booking.check_out && <span className="caption">Check out {shortDay(booking.check_out)}</span>}
          <Reference booking={booking} />
        </div>
      </details>
    </div>
  );
}
