import type { Idea, Place, SearchScope, TripStop } from "../api";
import { stopOfDay } from "./TripBits";
import { Rating } from "./TripPlaces";

/** Where a search for the trip looks: all of it, one of its stops, or round one day's places. */
export type Scope = {
  key: string;
  label: string;
  /** A stop's name, sent as `stop`. */
  stop?: string;
  /** A trip day (YYYY-MM-DD), sent as `day`. */
  day?: string;
  /** Day 1 is the trip's first day. */
  number?: number;
};

const DAY_MS = 86400000;

export const TRIP_SCOPE = "trip";

/** What the scope sends to the server: a stop's name, or a day, never both. */
export function scopeParams(scope: Scope | null | undefined): SearchScope {
  if (!scope) return {};
  return scope.day ? { day: scope.day } : scope.stop ? { stop: scope.stop } : {};
}

/** The scopes a finder offers: the whole trip; "In <stop>" for each stop once there are
 * two or more; and "Near Day N" (with the day's name when it has one) for ``day``, when
 * that is a day of the trip. */
export function findScopes({ stops, start, end, day, labels }: {
  stops: TripStop[];
  start: string;
  end: string;
  day?: string | null;
  labels?: Map<string, string>;
}): Scope[] {
  const scopes: Scope[] = [{ key: TRIP_SCOPE, label: "Whole trip" }];
  if (stops.length > 1) {
    for (const s of stops) {
      if (!scopes.some((x) => x.stop === s.name)) scopes.push({ key: `stop:${s.name}`, label: `In ${s.name}`, stop: s.name });
    }
  }
  if (day && day >= start && day <= end) {
    const number = Math.round((Date.parse(day) - Date.parse(start)) / DAY_MS) + 1;
    const name = labels?.get(day);
    scopes.push({ key: `day:${day}`, label: `Near Day ${number}${name ? ` · ${name}` : ""}`, day, number });
  }
  return scopes;
}

/** The scope a finder starts on: near the day it was opened from; else, on a trip with
 * several stops, the stop of the day being viewed; else the whole trip. */
export function firstScope(scopes: Scope[], { near, viewing, stops }: { near?: string | null; viewing?: string | null; stops: TripStop[] }): string {
  if (near) {
    const hit = scopes.find((s) => s.day === near);
    if (hit) return hit.key;
  }
  if (viewing && stops.length > 1) {
    const stop = stopOfDay(stops, viewing);
    const hit = stop && scopes.find((s) => s.stop === stop.name);
    if (hit) return hit.key;
  }
  return TRIP_SCOPE;
}

/** Quick searches. Each query is idea-ish, so guides and articles are read for it too. */
export const THEMES: { label: string; query: string }[] = [
  { label: "Food", query: "Best food" },
  { label: "Sights", query: "Top sights" },
  { label: "Museums", query: "Best museums" },
  { label: "Nature", query: "Best nature" },
  { label: "Shopping", query: "Best shopping" },
  { label: "Nightlife", query: "Best nightlife" },
  { label: "Rainy day", query: "Rainy day" },
];

/** A name as compared for duplicates: no accents, case, spaces or punctuation. */
export function normName(name: string): string {
  return name.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
}

/** One place in the merged list: from Google Maps, from a guide, or both. */
export type Found = {
  key: string;
  name: string;
  /** The neighbourhood, when a guide or Google says. */
  area: string | null;
  address: string | null;
  /** Google's kind, else the guide's. */
  kind: string | null;
  /** The guide's kind, else Google's: the list a saved idea is filed under. */
  listKind: string | null;
  price: string | null;
  /** Its Google Maps match, which has the rating. */
  place: Place | null;
  /** What the guide says, with the page it said it on. */
  why: string | null;
  source: { url: string; title: string } | null;
  from: ("google" | "guides")[];
};

/** Google Maps results and guide ideas as one list, each place once. Google's come first.
 * A guide idea for a place already listed (the same Google place, else the same name)
 * joins that card, which keeps the rating and adds the guide's words and link. */
export function mergeResults(google: Place[], ideas: Idea[]): Found[] {
  const out: Found[] = [];
  const byId = new Map<string, Found>();
  const byName = new Map<string, Found>();
  const index = (f: Found, ...names: string[]) => {
    if (f.place) byId.set(f.place.id, f);
    for (const n of names.map(normName)) if (n && !byName.has(n)) byName.set(n, f);
  };

  for (const p of google) {
    if (byId.has(p.id) || byName.has(normName(p.name))) continue;
    const f: Found = {
      key: p.id, name: p.name, area: p.area ?? null, address: p.address, kind: p.kind, listKind: p.kind, price: p.price,
      place: p, why: null, source: null, from: ["google"],
    };
    out.push(f);
    index(f, p.name);
  }

  for (const i of ideas) {
    const hit = (i.place && byId.get(i.place.id)) || byName.get(normName(i.name)) || (i.place && byName.get(normName(i.place.name))) || null;
    if (hit) {
      if (!hit.why) {
        hit.why = i.why;
        hit.source = i.source;
      }
      if (!hit.place && i.place) {
        hit.place = i.place;
        hit.address = hit.address ?? i.place.address;
        hit.price = hit.price ?? i.place.price;
        hit.kind = hit.kind ?? i.place.kind;
      }
      hit.area = hit.area ?? i.area;
      if (!hit.from.includes("guides")) hit.listKind = i.kind ?? hit.listKind;
      hit.kind = hit.kind ?? i.kind;
      if (!hit.from.includes("guides")) hit.from.push("guides");
      index(hit, i.name);
      continue;
    }
    const f: Found = {
      key: i.place?.id ?? `idea:${normName(i.name) || i.name}`, name: i.name, area: i.area ?? i.place?.area ?? null,
      address: i.place?.address ?? null, kind: i.place?.kind ?? i.kind, listKind: i.kind ?? i.place?.kind ?? null,
      price: i.place?.price ?? null, place: i.place, why: i.why, source: i.source, from: ["guides"],
    };
    out.push(f);
    index(f, i.name);
  }
  return out;
}

/** The list a saved idea is filed under: the theme searched, else its kind. */
export const listFor = (f: Found, theme: string | null): string | null => theme ?? f.listKind ?? f.kind ?? null;

/** What a button saves: as an idea in ``list``, or as a plan on ``day``. */
export type PickCtx = { list: string | null; day: string | null; dayNumber: number | null };

/** The scope row: whole trip, each stop, and near a day. */
export function ScopeRow({ scopes, value, onPick }: { scopes: Scope[]; value: string; onPick: (scope: Scope) => void }) {
  if (scopes.length < 2) return null;
  return (
    <div className="chips find-scopes" role="group" aria-label="Look in">
      {scopes.map((s) => (
        <button key={s.key} type="button" className="day-pill" aria-pressed={s.key === value} onClick={() => onPick(s)}>
          {s.label}
        </button>
      ))}
    </div>
  );
}

/** Quick themes that fill the search and run it. */
export function ThemeChips({ value, disabled, onPick }: { value: string | null; disabled: boolean; onPick: (theme: { label: string; query: string }) => void }) {
  return (
    <div className="chips find-themes" role="group" aria-label="Themes">
      {THEMES.map((t) => (
        <button key={t.label} type="button" className="day-pill" aria-pressed={value === t.label} disabled={disabled} onClick={() => onPick(t)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

/** The merged results. ``pickLabel`` saves a result (as an idea unless the finder was
 * opened to add to a day); ``dayScope`` adds "Add to Day N" beside it. */
export function ResultList({ results, label, pickLabel, saveText, busy, dayScope, onPick }: {
  results: Found[];
  label: string;
  pickLabel: string;
  /** The button's visible words, when they say more than ``pickLabel``. */
  saveText?: string;
  busy: boolean;
  /** When the search is near a day: the day the second button adds to. */
  dayScope: Scope | null;
  onPick: (found: Found, to: "list" | "day") => void;
}) {
  return (
    <ul className="feed find-results" aria-label={label}>
      {results.map((f) => {
        const where = f.area ?? f.address;
        return (
          <li key={f.key} className="run-row idea-row find-card">
            <span className="wrap">
              <strong>{f.name}</strong> {f.place && <Rating place={f.place} />}
              <br />
              <span className="caption">{[f.kind, f.price, where].filter(Boolean).join(" · ")}</span>
              {f.why && f.source && (
                <>
                  <br />
                  <span className="idea-why">“{f.why}”</span>{" "}
                  <a className="caption" href={f.source.url} target="_blank" rel="noopener noreferrer nofollow">
                    {f.source.title}
                  </a>
                </>
              )}
              <span className="find-tags">
                {f.from.includes("google") && <span className="chip">Google Maps</span>}
                {f.from.includes("guides") && <span className="chip">From guides</span>}
              </span>
            </span>
            <span className="find-actions">
              <button type="button" className="btn btn-small" disabled={busy} onClick={() => onPick(f, "list")} aria-label={`${pickLabel}: ${f.name}`}>
                {saveText ?? pickLabel}
              </button>
              {dayScope && (
                <button type="button" className="btn btn-small" disabled={busy} onClick={() => onPick(f, "day")} aria-label={`Add to Day ${dayScope.number}: ${f.name}`}>
                  Add to Day {dayScope.number}
                </button>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
