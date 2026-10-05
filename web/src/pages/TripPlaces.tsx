import { useQuery } from "@tanstack/react-query";
import { createContext, type FormEvent, type ReactNode, useContext, useState } from "react";

import { api, type Booking, type LinkedPlace, type Place } from "../api";

/** What the trip page knows about Google Maps: whether it's set up, and the details
 * of the entries linked to a place (fetched when shown; only place ids are kept). */
type TripPlaces = { tripId: string; destination: string; enabled: boolean; linked: Map<string, LinkedPlace>; onChange: () => void };

const Context = createContext<TripPlaces | null>(null);

export function TripPlacesProvider({ tripId, destination, enabled, onChange, children }: {
  tripId: string;
  destination: string;
  enabled: boolean;
  onChange: () => void;
  children: ReactNode;
}) {
  const linked = useQuery({
    queryKey: ["trip-places", tripId],
    queryFn: () => api<LinkedPlace[]>(`/travel/trips/${tripId}/places`),
    enabled,
    staleTime: 10 * 60 * 1000,
  });
  const value: TripPlaces = {
    tripId,
    destination,
    enabled,
    linked: new Map((linked.data ?? []).map((l) => [l.booking_id, l])),
    onChange,
  };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

const linkable = (b: Booking) => b.kind === "activity" || b.kind === "hotel";

export function Rating({ place }: { place: Place }) {
  if (place.rating === null) return null;
  const count = place.ratings !== null ? ` (${place.ratings.toLocaleString("en-US")})` : "";
  return (
    <span className="place-rating" aria-label={`Rated ${place.rating} out of 5${count ? ` from ${place.ratings} ratings` : ""}`}>
      ★ {place.rating}
      <span className="caption">{count}</span>
    </span>
  );
}

/** Hours, a summary and a few reviews, credited to Google Maps and each reviewer. */
function PlaceDetails({ place }: { place: Place }) {
  return (
    <div className="place-details">
      {place.summary && <p className="muted">{place.summary}</p>}
      {place.hours.length > 0 && (
        <details>
          <summary className="caption">Regular hours</summary>
          <ul className="place-hours">
            {place.hours.map((h) => (
              <li key={h}>{h}</li>
            ))}
          </ul>
          <p className="caption">Holidays can differ.</p>
        </details>
      )}
      {place.reviews.length > 0 && (
        <ul className="place-reviews" aria-label={`Reviews of ${place.name}`}>
          {place.reviews.map((r, n) => (
            <li key={n}>
              {r.rating !== null && <span aria-label={`${r.rating} stars`}>{"★".repeat(r.rating)}</span>} {r.text}
              <br />
              <span className="caption">
                {r.author_url ? (
                  <a href={r.author_url} target="_blank" rel="noopener noreferrer nofollow">
                    {r.author ?? "A reviewer"}
                  </a>
                ) : (
                  (r.author ?? "A reviewer")
                )}
                {r.when && `, ${r.when}`}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="caption">
        {place.website && (
          <>
            <a href={place.website} target="_blank" rel="noopener noreferrer nofollow">
              Website
            </a>
            {" · "}
          </>
        )}
        {place.phone && <>{place.phone} · </>}
        From Google Maps
      </p>
    </div>
  );
}

/** Search Google Maps, near the trip's destination, and pick a result. */
export function PlaceFinder({ initial, pickLabel, onPick, onCancel }: {
  initial: string;
  pickLabel: string;
  onPick: (place: Place) => Promise<void>;
  onCancel: () => void;
}) {
  const places = useContext(Context);
  const [query, setQuery] = useState(initial);
  const [found, setFound] = useState<Place[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!places) return null;
  const tripId = places.tripId;

  async function search(e?: FormEvent) {
    e?.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setFound(await api<Place[]>(`/travel/places/search?q=${encodeURIComponent(query.trim())}&trip_id=${tripId}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't search Google Maps");
    } finally {
      setBusy(false);
    }
  }

  async function pick(p: Place) {
    setBusy(true);
    setError(null);
    try {
      await onPick(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that");
      setBusy(false);
    }
  }

  return (
    <div className="place-finder">
      <form role="search" aria-label="Search Google Maps" onSubmit={(e) => void search(e)} className="inline-form">
        <input aria-label="Look for" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={`Ramen near ${places.destination}`} maxLength={120} />
        <button type="submit" className="btn btn-small btn-primary" disabled={busy}>
          Search
        </button>
        <button type="button" className="btn btn-small btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {found !== null &&
        (found.length === 0 ? (
          <p className="state">Nothing found on Google Maps.</p>
        ) : (
          <ul className="feed" aria-label="Google Maps results">
            {found.map((p) => (
              <li key={p.id} className="run-row">
                <span className="wrap">
                  <strong>{p.name}</strong> <Rating place={p} />
                  <br />
                  <span className="caption">{[p.kind, p.price, p.address].filter(Boolean).join(" · ")}</span>
                </span>
                <button type="button" className="btn btn-small" disabled={busy} onClick={() => void pick(p)} aria-label={`${pickLabel}: ${p.name}`}>
                  {pickLabel}
                </button>
              </li>
            ))}
          </ul>
        ))}
      {found !== null && <p className="caption">From Google Maps</p>}
    </div>
  );
}

/** Under a plan, place to visit or hotel: its Google Maps rating and a heads-up when
 * it's usually closed that day, with details on tap; or a way to find it. */
export function PlaceLine({ booking }: { booking: Booking }) {
  const places = useContext(Context);
  const [open, setOpen] = useState(false);
  const [finding, setFinding] = useState(false);
  if (!places?.enabled || !linkable(booking)) return null;
  const linked = places.linked.get(booking.id);

  async function link(placeId: string | null) {
    await api(`/travel/bookings/${booking.id}/place`, { method: "PUT", body: { place_id: placeId } });
    setFinding(false);
    places?.onChange();
  }

  if (finding) {
    const name = booking.kind === "hotel" ? (booking.hotel ?? booking.title) : (booking.name ?? booking.title);
    return <PlaceFinder initial={[name, booking.address].filter(Boolean).join(" ")} pickLabel="Link" onPick={(p) => link(p.id)} onCancel={() => setFinding(false)} />;
  }
  if (!booking.place_id) {
    return (
      <span className="caption">
        <button type="button" className="btn btn-small btn-ghost" onClick={() => setFinding(true)} aria-label={`Find ${booking.title} on Google Maps`}>
          Find on Google Maps
        </button>
        <br />
      </span>
    );
  }
  if (!linked) return null; // still loading, or Google Maps didn't answer
  const p = linked.place;
  return (
    <span className="place-line">
      <span className="caption">
        <Rating place={p} />
        {p.price && ` · ${p.price}`}
        {p.maps_url && (
          <>
            {" · "}
            <a href={p.maps_url} target="_blank" rel="noopener noreferrer nofollow">
              Google Maps
            </a>
          </>
        )}
        {" · "}
        <button type="button" className="btn btn-small btn-ghost" aria-expanded={open} onClick={() => setOpen(!open)} aria-label={`${open ? "Hide" : "Show"} details for ${booking.title}`}>
          {open ? "Less" : "Details"}
        </button>
      </span>
      {linked.warning && (
        <span className="place-warning" role="note">
          ⚠️ {linked.warning}
        </span>
      )}
      {open && (
        <>
          <PlaceDetails place={p} />
          <button type="button" className="btn btn-small btn-ghost" onClick={() => void link(null)}>
            Not this place
          </button>
        </>
      )}
    </span>
  );
}

/** Find places on Google Maps and keep them as places to visit. */
export function SavePlaces() {
  const places = useContext(Context);
  const [finding, setFinding] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  if (!places?.enabled) return null;
  if (!finding) {
    return (
      <>
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setFinding(true)}>
          🔎 Find places on Google Maps
        </button>
        {saved && (
          <p className="caption" role="status">
            Saved {saved}.
          </p>
        )}
      </>
    );
  }
  return (
    <PlaceFinder
      initial=""
      pickLabel="Save"
      onCancel={() => setFinding(false)}
      onPick={async (p) => {
        await api(`/travel/trips/${places.tripId}/bookings`, {
          method: "POST",
          body: { kind: "activity", name: p.name.slice(0, 120), address: p.address?.slice(0, 200) ?? null, category: p.kind?.slice(0, 30) ?? null, place_id: p.id },
        });
        setSaved(p.name);
        setFinding(false);
        places.onChange();
      }}
    />
  );
}
