import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, type Reply, type Trip } from "../api";
import { formatShortDate } from "../format";
import type { EntryKind } from "./Trips";
import { SavePlaces } from "./TripPlaces";

export type AddPreset = { kind: EntryKind; day?: string };

const FORMS: { kind: EntryKind; label: string }[] = [
  { kind: "flight", label: "✈️ Flight" },
  { kind: "hotel", label: "🏨 Place to stay" },
  { kind: "rail", label: "🚆 Train" },
  { kind: "activity", label: "🗓️ Plan on a day" },
  { kind: "place", label: "📍 Place to visit" },
];

const HINTS: Partial<Record<EntryKind, string>> = {
  hotel: 'e.g. "Hotel Ume 13 to 15 Nov, ref 8812, booked on Agoda"',
  flight: 'e.g. "SQ12 to Tokyo on 10 Nov at 08:25, ref ZK4P7Q"',
};
const HINT = 'e.g. "Dinner at Sushi Ten on Thursday at 7pm" or "Hotel Ume 13 to 15 Nov"';

type Line = { who: "you" | "nexus"; text: string; buttons?: Reply["buttons"] };

/** Telling Nexus about a booking in a sentence, without leaving the trip. What it
 * reads is shown, and anything it changes waits for Confirm, as in the chat. */
function TypeIt({ trip, preset, onChanged }: { trip: Trip; preset: AddPreset | null; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const when = `${formatShortDate(trip.start, "UTC")} to ${formatShortDate(trip.end, "UTC")}`;

  useEffect(() => end.current?.scrollIntoView({ block: "nearest" }), [lines]);

  async function run(call: Promise<Reply[]>) {
    setBusy(true);
    try {
      const replies = await call;
      setLines((l) => [...l, ...replies.map((r) => ({ who: "nexus" as const, text: r.text, buttons: r.buttons }))]);
      onChanged();
    } catch (e) {
      setLines((l) => [...l, { who: "nexus", text: e instanceof Error ? e.message : "Couldn't reach Nexus. Try again." }]);
    } finally {
      setBusy(false);
    }
  }

  function send(event: FormEvent) {
    event.preventDefault();
    const said = text.trim();
    if (!said || busy) return;
    setText("");
    setLines((l) => [...l, { who: "you", text: said }]);
    // The trip goes with it, so "Thursday" and "the hotel" mean this trip's.
    const message = `For my ${trip.destination} trip (${when}), add this: ${said}`;
    void run(api<Reply[]>("/chat", { method: "POST", body: { message } }));
  }

  function press(index: number, data: string, label: string) {
    setLines((l) => [...l.map((line, i) => (i === index ? { ...line, buttons: [] } : line)), { who: "you", text: label }]);
    void run(api<Reply[]>("/chat/press", { method: "POST", body: { data } }));
  }

  return (
    <div className="type-it">
      {lines.length > 0 && (
        <div className="type-it-lines" aria-live="polite" aria-label="Nexus">
          {lines.map((line, i) => (
            <div key={i} className={`type-it-line ${line.who}`}>
              <p>{line.text}</p>
              {line.buttons && line.buttons.length > 0 && (
                <div className="quick">
                  {line.buttons.flat().map((b) => (
                    <button key={b.data} type="button" className="btn btn-small" disabled={busy} onClick={() => press(i, b.data, b.label)}>
                      {b.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
          <div ref={end} />
        </div>
      )}
      <form className="type-it-form" onSubmit={send}>
        <label className="sr-only" htmlFor="type-it-input">
          Tell Nexus about a booking
        </label>
        <input
          id="type-it-input"
          className="input"
          value={text}
          maxLength={500}
          autoFocus
          onChange={(e) => setText(e.target.value)}
          placeholder={(preset && HINTS[preset.kind]) ?? HINT}
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !text.trim()}>
          {busy ? "…" : "Send"}
        </button>
      </form>
    </div>
  );
}

/** The trip's one way to add something: type it, show a screenshot, find a place, or
 * fill in a form. */
export function AddSheet({
  trip,
  preset,
  places,
  onScreenshot,
  onForm,
  onChanged,
  onClose,
}: {
  trip: Trip;
  preset: AddPreset | null;
  places: boolean;
  onScreenshot: (file: File) => void;
  onForm: (preset: AddPreset) => void;
  onChanged: () => void;
  onClose: () => void;
}) {
  const [view, setView] = useState<"menu" | "type" | "forms" | "place">(preset ? "type" : "menu");

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const forPreset = preset ? FORMS.find((f) => f.kind === preset.kind) : undefined;
  return (
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="add-sheet" role="dialog" aria-modal="true" aria-labelledby="add-sheet-title">
        <div className="add-sheet-head">
          {view !== "menu" && (
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setView("menu")} aria-label="Back to the ways to add">
              ‹
            </button>
          )}
          <h2 id="add-sheet-title">{view === "type" ? "Type it" : view === "forms" ? "Fill in a form" : view === "place" ? "Find a place" : `Add to ${trip.destination}`}</h2>
          <button type="button" className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {view === "menu" && (
          <div className="ways">
            <button type="button" className="way main" onClick={() => setView("type")}>
              <span className="way-icon" aria-hidden="true">
                💬
              </span>
              <span>
                <strong>Type it</strong>
                <span className="caption">A flight, a stay or a plan, in your own words</span>
              </span>
            </button>
            <label className="way main">
              <span className="way-icon" aria-hidden="true">
                🖼️
              </span>
              <span>
                <strong>Screenshot or photo</strong>
                <span className="caption">A booking, ticket or itinerary page</span>
              </span>
              <input
                className="sr-only"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                aria-label="Screenshot or photo"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) {
                    onClose();
                    onScreenshot(file);
                  }
                }}
              />
            </label>
            {places && (
              <button type="button" className="way" onClick={() => setView("place")}>
                <span className="way-icon" aria-hidden="true">
                  📍
                </span>
                <span>
                  <strong>Find a place</strong>
                  <span className="caption">Search Google Maps and save it to visit</span>
                </span>
              </button>
            )}
            <button type="button" className="way" onClick={() => setView("forms")}>
              <span className="way-icon" aria-hidden="true">
                ✏️
              </span>
              <span>
                <strong>Fill in a form</strong>
                <span className="caption">Flight, place to stay, train or plan</span>
              </span>
            </button>
          </div>
        )}

        {view === "type" && (
          <>
            <TypeIt trip={trip} preset={preset} onChanged={onChanged} />
            {forPreset && (
              <button type="button" className="btn btn-ghost btn-small" onClick={() => onForm(preset!)}>
                Or fill in a form: {forPreset.label}
              </button>
            )}
          </>
        )}

        {view === "forms" && (
          <div className="ways ways-grid">
            {FORMS.map((f) => (
              <button key={f.kind} type="button" className="btn" onClick={() => onForm({ kind: f.kind, day: preset?.day })}>
                {f.label}
              </button>
            ))}
          </div>
        )}

        {view === "place" && <SavePlaces open onDone={onChanged} />}
      </section>
    </div>
  );
}
