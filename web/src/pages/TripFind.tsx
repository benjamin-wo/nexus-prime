import { type KeyboardEvent, type ReactNode, useEffect, useId, useRef, useState } from "react";

import type { Idea, Place, SearchScope, TripStop } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { stopOfDay } from "./TripBits";
import { PlacePicture, Rating } from "./TripPlaces";

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

/** Stop names as a sentence: "Tokyo", "Tokyo and Kyoto", "Tokyo, Kyoto and Osaka". */
const joinNames = (names: string[]) => (names.length < 2 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);

/** One line saying where a search looks, and whether guides are read with Google. */
export function whereCaption({ scope, scopes, destination, withIdeas }: { scope: Scope | null; scopes: Scope[]; destination: string; withIdeas: boolean }): string {
  let text: string;
  if (scope?.day) text = `Within about 2 km of Day ${scope.number}'s plans.`;
  else if (scope?.stop) text = `In ${scope.stop}.`;
  else {
    const stops = scopes.filter((s) => s.stop).map((s) => s.stop as string);
    text = stops.length > 1 ? `Across ${joinNames(stops)}.` : `Near ${destination}.`;
  }
  return withIdeas ? `${text} Google and guides together.` : text;
}

/** Where to look, as one chip with the current scope; it opens the whole trip, each stop
 * and near a day as a menu. */
export function ScopeMenu({ scopes, value, onPick }: { scopes: Scope[]; value: string; onPick: (scope: Scope) => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const chip = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    box.current?.querySelector<HTMLElement>('[role="menuitemradio"][aria-checked="true"]')?.focus();
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  if (scopes.length < 2) return null;
  const current = scopes.find((s) => s.key === value) ?? scopes[0];

  function key(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === "Escape") {
      // Closes the menu, not the sheet round it.
      e.stopPropagation();
      setOpen(false);
      chip.current?.focus();
    } else if (e.key === "Tab") {
      setOpen(false);
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const items = [...(box.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? [])];
      const at = items.indexOf(document.activeElement as HTMLElement);
      const next = e.key === "ArrowDown" ? (at + 1) % items.length : (at <= 0 ? items.length : at) - 1;
      items[next]?.focus();
    }
  }

  return (
    <div className="find-scope" role="group" aria-label="Look in" ref={box} onKeyDown={key}>
      <button
        ref={chip}
        type="button"
        className="day-pill find-scope-chip"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`Look in: ${current.label}`}
        onClick={() => setOpen(!open)}
      >
        {current.label}
        <Icon name="chevronDown" size={16} />
      </button>
      {open && (
        <div id={menuId} className="find-menu" role="menu" aria-label="Look in">
          {scopes.map((s) => (
            <button
              key={s.key}
              type="button"
              role="menuitemradio"
              aria-checked={s.key === current.key}
              className="find-menu-item"
              onClick={() => {
                setOpen(false);
                chip.current?.focus();
                if (s.key !== current.key) onPick(s);
              }}
            >
              {s.label}
              {s.key === current.key && <Icon name="check" size={16} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Quick themes that fill the search and run it, in one row that scrolls sideways. */
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

/** The icon on a result with no photo, by what it is. */
function tileIcon(f: Found): IconName {
  const kind = `${f.kind ?? ""} ${f.listKind ?? ""}`;
  if (/food|restaurant|ramen|sushi|caf[eé]|coffee|noodle|bakery|bar\b|izakaya|market/i.test(kind)) return "food";
  if (/hotel|stay|inn\b|hostel|ryokan|lodging/i.test(kind)) return "stay";
  if (/museum|gallery|ticket|theat|show/i.test(kind)) return "ticket";
  return "place";
}

/** Chains the parts of a meta line with a middle dot. */
function dotted(parts: ReactNode[]): ReactNode[] {
  return parts.flatMap((part, i) => (i === 0 ? [part] : [" · ", part]));
}

/** The merged results. ``pickLabel`` saves a result (as an idea unless the finder was
 * opened to add to a day); ``dayScope`` adds "Add to Day N" beside it. A saved result
 * says so and the list stays, so several can be saved. */
export function ResultList({ results, label, pickLabel, saveText, busy, dayScope, saved, onPick }: {
  results: Found[];
  label: string;
  pickLabel: string;
  /** The button's visible words, when they say more than ``pickLabel``. */
  saveText?: string;
  busy: boolean;
  /** When the search is near a day: the day the second button adds to. */
  dayScope: Scope | null;
  /** Keys of the results already saved. */
  saved?: ReadonlySet<string>;
  onPick: (found: Found, to: "list" | "day") => void;
}) {
  return (
    <ul className="find-results" aria-label={label}>
      {results.map((f) => {
        const where = f.area ?? f.address;
        const source = f.source ? (
          <a key="source" href={f.source.url} target="_blank" rel="noopener noreferrer nofollow" title={f.source.title} aria-label={`From a guide: ${f.source.title}`}>
            From a guide
          </a>
        ) : (
          "From a guide"
        );
        const guide = [...(f.why ? [<span key="why" className="idea-why">“{f.why}”</span>] : []), source];
        const meta = f.from.includes("google")
          ? dotted([...(f.place ? [<Rating key="rating" place={f.place} />] : []), ...(where ? [where] : []), "Google Maps"])
          : dotted(f.why ? guide : [...(where ? [where] : []), ...guide]);
        const isSaved = saved?.has(f.key) ?? false;
        return (
          <li key={f.key} className="find-card">
            {f.place?.photo_url ? (
              <PlacePicture place={f.place} tile />
            ) : (
              <span className="find-tile" aria-hidden="true">
                <Icon name={tileIcon(f)} size={24} />
              </span>
            )}
            <span className="find-text">
              <strong>{f.name}</strong>
              <span className="find-meta">{meta}</span>
              {f.from.includes("google") && f.from.includes("guides") && <span className="find-meta">{dotted(guide)}</span>}
              {/* Google asks for the photo's author to be shown with it. */}
              {f.place?.photo_url && (
                <span className="find-meta find-credit">
                  {f.place.photo_author_url ? (
                    <a href={f.place.photo_author_url} target="_blank" rel="noopener noreferrer">
                      Photo{f.place.photo_author ? ` by ${f.place.photo_author}` : ""}, Google Maps
                    </a>
                  ) : (
                    <>Photo{f.place.photo_author ? ` by ${f.place.photo_author}` : ""}, Google Maps</>
                  )}
                </span>
              )}
            </span>
            <span className="find-actions">
              {isSaved ? (
                <button type="button" className="btn find-saved" disabled aria-label={`${f.name} is saved`}>
                  <Icon name="check" size={16} />
                  Saved
                </button>
              ) : (
                <>
                  <button type="button" className="btn btn-soft" disabled={busy} onClick={() => onPick(f, "list")} aria-label={`${pickLabel}: ${f.name}`}>
                    {saveText ?? pickLabel}
                  </button>
                  {dayScope && (
                    <button type="button" className="btn btn-soft" disabled={busy} onClick={() => onPick(f, "day")} aria-label={`Add to Day ${dayScope.number}: ${f.name}`}>
                      Add to Day {dayScope.number}
                    </button>
                  )}
                </>
              )}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
