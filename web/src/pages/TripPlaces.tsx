import { useQuery } from "@tanstack/react-query";
import { createContext, type FormEvent, type ReactNode, useContext, useState } from "react";

import { api, type Booking, type Idea, type Ideas, type LinkedPlace, type Place } from "../api";

/** What the trip page knows about Google Maps: whether it's set up, and the details
 * of the entries linked to a place (fetched when shown; only place ids are kept); and
 * whether ideas from travel guides and articles can be asked for. */
type TripPlaces = {
  tripId: string;
  destination: string;
  enabled: boolean;
  ideas: boolean;
  linked: Map<string, LinkedPlace>;
  onChange: () => void;
};

const Context = createContext<TripPlaces | null>(null);

export function TripPlacesProvider({ tripId, destination, enabled, ideas = false, onChange, children }: {
  tripId: string;
  destination: string;
  enabled: boolean;
  ideas?: boolean;
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
    ideas,
    linked: new Map((linked.data ?? []).map((l) => [l.booking_id, l])),
    onChange,
  };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** A linked place's Google Maps photo as a small thumbnail, credited to its author;
 * a plain tile when there's none. */
export function PlaceThumb({ booking }: { booking: Booking }) {
  const places = useContext(Context);
  if (!places?.enabled) return null;
  const place = places.linked.get(booking.id)?.place;
  if (!place?.photo_url) return <span className="place-thumb place-thumb-empty" aria-hidden="true" />;
  const credit = `Photo${place.photo_author ? ` by ${place.photo_author}` : ""}, Google Maps`;
  return (
    <figure className="place-thumb">
      <img src={place.photo_url} alt={`${place.name}`} loading="lazy" width={64} height={64} />
      <figcaption>
        {place.photo_author_url ? (
          <a href={place.photo_author_url} target="_blank" rel="noopener noreferrer">
            {credit}
          </a>
        ) : (
          credit
        )}
      </figcaption>
    </figure>
  );
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

// Words that ask for ideas rather than name a place: "best ramen", "rainy day",
// "cheap eats near Dotonbori". A name ("Ichiran Shibuya") goes to Google Maps alone.
const IDEA_WORDS =
  /\b(best|good|great|cheap|top|favou?rite|where|what|ideas?|things?|to do|places|eats?|food|drinks?|bars?|caf[eé]s?|coffee|brunch|dinner|lunch|breakfast|dessert|rainy|kids|family|romantic|local|hidden|street|vegan|vegetarian|halal|sights?|views?|shopping|markets?|nightlife|museums?|day trips?|must)\b/i;

export function wantsIdeas(query: string): boolean {
  return IDEA_WORDS.test(query) || query.trim().split(/\s+/).length >= 4;
}

/** Ideas from travel guides and articles, each credited to its page, with its Google
 * Maps rating when it has one. */
function IdeaList({ found, busy, onPick }: { found: Ideas; busy: boolean; onPick: (idea: Idea) => void }) {
  if (found.ideas.length === 0) return <p className="state">No specific places came up in guides or articles.</p>;
  return (
    <ul className="feed" aria-label="Ideas from guides and articles">
      {found.ideas.map((idea) => (
        <li key={idea.name} className="run-row idea-row">
          <span className="wrap">
            <strong>{idea.name}</strong> {idea.place && <Rating place={idea.place} />}
            <br />
            <span className="caption">{[idea.kind, idea.area ?? idea.place?.address].filter(Boolean).join(" · ")}</span>
            <br />
            <span className="idea-why">“{idea.why}”</span>{" "}
            <a className="caption" href={idea.source.url} target="_blank" rel="noopener noreferrer nofollow">
              {idea.source.title}
            </a>
          </span>
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => onPick(idea)} aria-label={`Save: ${idea.name}`}>
            Save
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Search Google Maps, near the trip's destination, and pick a result. With
 * ``onPickIdea``, a query that asks for ideas also reads travel guides and articles,
 * shown below the Google Maps results once they're in (they take longer). */
export function PlaceFinder({ initial, pickLabel, onPick, onPickIdea, onCancel }: {
  initial: string;
  pickLabel: string;
  onPick: (place: Place) => Promise<void>;
  onPickIdea?: (idea: Idea) => Promise<void>;
  onCancel: () => void;
}) {
  const places = useContext(Context);
  const [query, setQuery] = useState(initial);
  const [found, setFound] = useState<Place[] | null>(null);
  const [ideas, setIdeas] = useState<Ideas | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!places) return null;
  const tripId = places.tripId;
  const google = places.enabled;
  const withIdeas = Boolean(onPickIdea) && places.ideas;

  async function readIdeas(q: string) {
    setReading(true);
    setIdeas(null);
    try {
      setIdeas(await api<Ideas>(`/travel/trips/${tripId}/ideas?q=${encodeURIComponent(q)}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't read guides and articles");
    } finally {
      setReading(false);
    }
  }

  async function search(e?: FormEvent) {
    e?.preventDefault();
    const q = query.trim();
    if (!q) return;
    setError(null);
    setIdeas(null);
    setAsked(q);
    // Ideas take longer: they're read alongside, and shown when they're in.
    if (withIdeas && (!google || wantsIdeas(q))) void readIdeas(q);
    if (!google) return;
    setBusy(true);
    try {
      setFound(await api<Place[]>(`/travel/places/search?q=${encodeURIComponent(q)}&trip_id=${tripId}`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't search Google Maps");
    } finally {
      setBusy(false);
    }
  }

  async function pick(run: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await run();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that");
      setBusy(false);
    }
  }

  return (
    <div className="place-finder">
      <form role="search" aria-label={google ? "Search Google Maps" : "Find ideas"} onSubmit={(e) => void search(e)} className="inline-form">
        <input
          className="input"
          aria-label="Look for"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={withIdeas ? `Best ramen, a rainy day, or a place's name` : `Ramen near ${places.destination}`}
          maxLength={120}
        />
        <button type="submit" className="btn btn-small btn-primary" disabled={busy || reading}>
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
                <button type="button" className="btn btn-small" disabled={busy} onClick={() => void pick(() => onPick(p))} aria-label={`${pickLabel}: ${p.name}`}>
                  {pickLabel}
                </button>
              </li>
            ))}
          </ul>
        ))}
      {found !== null && <p className="caption">From Google Maps</p>}
      {withIdeas && asked && !reading && !ideas && google && (
        <button type="button" className="btn btn-ghost btn-small" onClick={() => void readIdeas(asked)}>
          💡 Ideas from guides and articles for “{asked}”
        </button>
      )}
      {reading && (
        <p className="caption" role="status">
          Reading travel guides and articles… about 15 seconds.
        </p>
      )}
      {ideas && onPickIdea && (
        <section aria-label="From guides and articles" className="idea-section">
          <h3 className="eyebrow">From guides and articles</h3>
          <IdeaList found={ideas} busy={busy} onPick={(idea) => void pick(() => onPickIdea(idea))} />
          <p className="caption">Their words, with a link to each page. Check opening times before you go.</p>
        </section>
      )}
    </div>
  );
}

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
export function SavePlaces({ open = false, onDone }: { open?: boolean; onDone?: () => void } = {}) {
  const places = useContext(Context);
  const [finding, setFinding] = useState(open);
  const [saved, setSaved] = useState<string | null>(null);
  if (!places || !(places.enabled || places.ideas)) return null;

  async function save(name: string, address: string | null, category: string | null, placeId: string | null) {
    await api(`/travel/trips/${places!.tripId}/bookings`, {
      method: "POST",
      body: { kind: "activity", name: name.slice(0, 120), address: address?.slice(0, 200) ?? null, category: category?.slice(0, 30) ?? null, place_id: placeId },
    });
    setSaved(name);
    setFinding(false);
    places!.onChange();
    onDone?.();
  }

  if (!finding) {
    return (
      <>
        <button type="button" className="btn btn-ghost btn-small" onClick={() => setFinding(true)}>
          {places.ideas ? "🔎 Find places or ideas" : "🔎 Find places on Google Maps"}
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
      onPick={(p) => save(p.name, p.address, p.kind, p.id)}
      onPickIdea={places.ideas ? (i) => save(i.name, i.place?.address ?? i.area, i.kind, i.place?.id ?? null) : undefined}
    />
  );
}

/** The trip's Google Maps details by entry id, for the map; empty when not set up. */
export function useLinkedPlaces(): Map<string, LinkedPlace> {
  return useContext(Context)?.linked ?? new Map();
}
