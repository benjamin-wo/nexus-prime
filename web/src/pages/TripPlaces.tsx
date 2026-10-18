import { useQuery } from "@tanstack/react-query";
import { createContext, type FormEvent, type ReactNode, useContext, useRef, useState } from "react";

import { api, type Booking, type Ideas, type LinkedPlace, type Place, placeSearchPath, type SearchScope, tripIdeasPath, type TripDetail } from "../api";
import { nearbyOf } from "./TripArrange";
import { stopsOf } from "./TripBits";
import { findScopes, firstScope, listFor, type Found, mergeResults, type PickCtx, ResultList, type Scope, ScopeRow, scopeParams, ThemeChips } from "./TripFind";

/** What the trip page knows about Google Maps: whether it's set up, and the details
 * of the entries linked to a place (fetched when shown; only place ids are kept); and
 * whether ideas from travel guides and articles can be asked for. */
type TripPlaces = {
  tripId: string;
  destination: string;
  enabled: boolean;
  ideas: boolean;
  linked: Map<string, LinkedPlace>;
  /** The trip, for the finder's stops and days; absent where there isn't one to hand. */
  detail: TripDetail | null;
  onChange: () => void;
};

const Context = createContext<TripPlaces | null>(null);

export function TripPlacesProvider({ tripId, destination, enabled, ideas = false, detail = null, onChange, children }: {
  tripId: string;
  destination: string;
  enabled: boolean;
  ideas?: boolean;
  detail?: TripDetail | null;
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
    detail,
    // Airports and stations go under their flight's id and name, apart from entries.
    linked: new Map((linked.data ?? []).map((l) => [l.station ? `${l.booking_id}#${l.station}` : l.booking_id, l])),
    onChange,
  };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** A linked place's Google Maps photo as a small thumbnail, credited to its author;
 * nothing at all when there's none. */
export function PlaceThumb({ booking }: { booking: Booking }) {
  const places = useContext(Context);
  if (!places?.enabled) return null;
  const place = places.linked.get(booking.id)?.place;
  return place ? <PlacePicture place={place} /> : null;
}

/** A place's Google Maps photo, credited to its author; nothing when it has none.
 * Large in a place's details, a thumbnail elsewhere. */
function PlacePicture({ place, large = false }: { place: Place; large?: boolean }) {
  if (!place.photo_url) return null;
  const credit = `Photo${place.photo_author ? ` by ${place.photo_author}` : ""}, Google Maps`;
  const size = large ? 240 : 64;
  return (
    <figure className={`place-thumb${large ? " place-photo" : ""}`}>
      <img src={place.photo_url} alt={`${place.name}`} loading="lazy" width={size} height={large ? 160 : size} />
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
      <PlacePicture place={place} large />
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

/** Search Google Maps, near the trip's destination, and pick a result. With ``ideas``, a
 * query that asks for ideas also reads travel guides and articles, merged into the same
 * list once they're in (they take longer). With ``scopes`` the search can look in one stop
 * or near a day, and ``themes`` adds quick searches. */
export function PlaceFinder({ initial, pickLabel, saveText, onPick, ideas: ideasOn = false, scopes, firstScopeKey, themes = false, onCancel }: {
  initial: string;
  pickLabel: string;
  /** The pick button's words when they say more than ``pickLabel`` (its name stays ``pickLabel``). */
  saveText?: string;
  onPick: (found: Found, ctx: PickCtx) => Promise<void>;
  ideas?: boolean;
  scopes?: Scope[];
  firstScopeKey?: string;
  themes?: boolean;
  onCancel: () => void;
}) {
  const places = useContext(Context);
  const [query, setQuery] = useState(initial);
  const [found, setFound] = useState<Place[] | null>(null);
  const [ideas, setIdeas] = useState<Ideas | null>(null);
  const [asked, setAsked] = useState<{ q: string; scope: SearchScope; theme: string | null } | null>(null);
  const [scopeKey, setScopeKey] = useState(firstScopeKey ?? scopes?.[0]?.key ?? "");
  const [theme, setTheme] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Only the latest search may show its answer: a slower earlier one is dropped.
  const latest = useRef(0);
  if (!places) return null;
  const tripId = places.tripId;
  const google = places.enabled;
  const withIdeas = ideasOn && places.ideas;
  const scope = scopes?.find((s) => s.key === scopeKey) ?? scopes?.[0] ?? null;
  const results = mergeResults(found ?? [], ideas?.ideas ?? []);
  const dayScope = scope?.day && scope.number ? scope : null;

  async function readIdeas(q: string, where: SearchScope, id: number) {
    setReading(true);
    setIdeas(null);
    try {
      const answer = await api<Ideas>(tripIdeasPath(tripId, q, where));
      if (id === latest.current) setIdeas(answer);
    } catch (err) {
      if (id === latest.current) setError(err instanceof Error ? err.message : "Couldn't read guides and articles");
    } finally {
      if (id === latest.current) setReading(false);
    }
  }

  async function search(e?: FormEvent, over: { q?: string; theme?: string | null; scope?: SearchScope } = {}) {
    e?.preventDefault();
    const q = (over.q ?? query).trim();
    if (!q) return;
    const where = over.scope ?? scopeParams(scope);
    const id = ++latest.current;
    setError(null);
    setIdeas(null);
    setFound(null);
    setReading(false);
    setAsked({ q, scope: where, theme: over.theme !== undefined ? over.theme : theme });
    // Ideas take longer: they're read alongside, and shown when they're in.
    if (withIdeas && (!google || wantsIdeas(q))) void readIdeas(q, where, id);
    if (!google) return;
    setBusy(true);
    try {
      const answer = await api<Place[]>(placeSearchPath(q, tripId, where));
      if (id === latest.current) setFound(answer);
    } catch (err) {
      if (id === latest.current) setError(err instanceof Error ? err.message : "Couldn't search Google Maps");
    } finally {
      if (id === latest.current) setBusy(false);
    }
  }

  async function pick(f: Found, to: "list" | "day") {
    setBusy(true);
    setError(null);
    try {
      await onPick(f, to === "day" && dayScope ? { list: null, day: dayScope.day ?? null, dayNumber: dayScope.number ?? null } : { list: listFor(f, asked?.theme ?? null), day: null, dayNumber: null });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save that");
      setBusy(false);
    }
  }

  const waiting = busy || reading;
  const shown = found !== null || ideas !== null;
  return (
    <div className="place-finder">
      <form role="search" aria-label={google ? "Search Google Maps" : "Find ideas"} onSubmit={(e) => void search(e)} className="inline-form">
        <input
          className="input"
          aria-label="Look for"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setTheme(null);
          }}
          placeholder={withIdeas ? `Best ramen, a rainy day, or a place's name` : `Ramen near ${places.destination}`}
          maxLength={120}
        />
        <button type="submit" className="btn btn-small btn-primary" disabled={waiting}>
          Search
        </button>
        <button type="button" className="btn btn-small btn-ghost" onClick={onCancel}>
          Cancel
        </button>
      </form>
      {scopes && (
        <ScopeRow
          scopes={scopes}
          value={scope?.key ?? ""}
          onPick={(s) => {
            setScopeKey(s.key);
            // Looking somewhere else asks the same question again.
            if (asked) void search(undefined, { q: asked.q, theme: asked.theme, scope: scopeParams(s) });
          }}
        />
      )}
      {themes && (
        <ThemeChips
          value={theme}
          disabled={waiting}
          onPick={(t) => {
            setQuery(t.query);
            setTheme(t.label);
            void search(undefined, { q: t.query, theme: t.label });
          }}
        />
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {results.length > 0 && (
        <ResultList
          results={results}
          label={withIdeas ? "Results" : "Google Maps results"}
          pickLabel={pickLabel}
          saveText={saveText}
          busy={busy}
          dayScope={dayScope}
          onPick={(f, to) => void pick(f, to)}
        />
      )}
      {found !== null && found.length === 0 && ideas === null && !reading && <p className="state">Nothing found on Google Maps.</p>}
      {reading && (
        <p className="caption" role="status">
          Looking in guides… this can take about 15 seconds.
        </p>
      )}
      {ideas && ideas.ideas.length === 0 && <p className="state">No specific places came up in guides or articles.</p>}
      {withIdeas && asked && !reading && !ideas && google && (
        <button type="button" className="btn btn-ghost btn-small" onClick={() => void readIdeas(asked.q, asked.scope, latest.current)}>
          💡 Ideas from guides and articles for “{asked.q}”
        </button>
      )}
      {found !== null && <p className="caption">From Google Maps</p>}
      {shown && ideas && ideas.ideas.length > 0 && <p className="caption">Guide ideas are their words, with a link to each page. Check opening times before you go.</p>}
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
    return <PlaceFinder initial={[name, booking.address].filter(Boolean).join(" ")} pickLabel="Link" onPick={async (f) => { if (f.place) await link(f.place.id); }} onCancel={() => setFinding(false)} />;
  }
  if (!booking.place_id) {
    return (
      <span className="caption place-find">
        <button type="button" className="link-btn" onClick={() => setFinding(true)} aria-label={`Find ${booking.title} on Google Maps`}>
          <span aria-hidden="true">📍</span> Find on Google Maps
        </button>
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
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)} aria-label={`${open ? "Hide" : "Show"} details for ${booking.title}`}>
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
          <button type="button" className="link-btn caption" onClick={() => void link(null)}>
            Not this place
          </button>
        </>
      )}
    </span>
  );
}

/** Find places on Google Maps (and in guides and articles) and keep them as Ideas. It looks
 * over the whole trip, in one stop, or near a day. */
export function SavePlaces({ open = false, day, at, near, viewing, onDone }: {
  open?: boolean;
  /** Saved as a plan on this day (at this time) instead of an idea. */
  day?: string;
  at?: string;
  /** Looks near this day to begin with; its results can be saved as ideas or added to it. */
  near?: string | null;
  /** The day open on Plan: offered as "Near Day N", and its stop is where a trip with several stops begins. */
  viewing?: string | null;
  onDone?: () => void;
} = {}) {
  const places = useContext(Context);
  const [finding, setFinding] = useState(open);
  const [saved, setSaved] = useState<string | null>(null);
  if (!places || !(places.enabled || places.ideas)) return null;

  async function save(f: Found, ctx: PickCtx) {
    const onDay = day ?? ctx.day;
    const address = f.place?.address ?? f.area;
    await api(`/travel/trips/${places!.tripId}/bookings`, {
      method: "POST",
      body: {
        kind: "activity", name: f.name.slice(0, 120), address: address?.slice(0, 200) ?? null, category: f.kind?.slice(0, 30) ?? null, place_id: f.place?.id ?? null,
        day: onDay ?? null, at: day ? (at ?? null) : null, list_name: onDay ? null : ctx.list?.slice(0, 30) || null,
      },
    });
    setSaved(day ? `Saved ${f.name}.` : ctx.day ? `Added ${f.name} to Day ${ctx.dayNumber}.` : `Saved ${f.name} to Ideas.`);
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
            {saved}
          </p>
        )}
      </>
    );
  }
  const detail = places.detail;
  const stops = detail ? stopsOf(detail) : [];
  const from = near ?? day ?? null;
  const scopes = findScopes({
    stops,
    start: detail?.trip.start ?? "",
    end: detail?.trip.end ?? "",
    day: from ?? viewing,
    labels: detail ? nearbyOf(detail, places.linked).labels : undefined,
  });
  return (
    <PlaceFinder
      initial=""
      pickLabel={day ? "Add" : "Save"}
      saveText={day ? undefined : "Save to Ideas"}
      onCancel={() => setFinding(false)}
      onPick={save}
      ideas={places.ideas}
      scopes={scopes}
      firstScopeKey={firstScope(scopes, { near: from, viewing, stops })}
      themes
    />
  );
}

/** The trip's Google Maps details by entry id, for the map; empty when not set up. */
export function useLinkedPlaces(): Map<string, LinkedPlace> {
  return useContext(Context)?.linked ?? new Map();
}
