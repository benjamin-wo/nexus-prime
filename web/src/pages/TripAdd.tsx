import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, type Reply, type Trip } from "../api";
import { formatShortDate } from "../format";
import { EntryEditor, type EntryKind } from "./TripEntry";
import { useHome } from "./TripBits";
import { SavePlaces } from "./TripPlaces";

export type AddPreset = {
  kind: EntryKind;
  day?: string;
  /** Straight to finding a place, saved as a plan on ``day`` at this time. */
  find?: boolean;
  at?: string;
};

/** The three things a trip holds, each with its own short form. */
const CHOICES: { form: "booking" | "plan" | "idea"; title: string; text: string; kind: EntryKind }[] = [
  { form: "booking", title: "A booking", text: "Flight, stay, train or ticket. It sits at its time on its day.", kind: "flight" },
  { form: "plan", title: "A plan", text: "Something you mean to do on a day. Time is optional.", kind: "activity" },
  { form: "idea", title: "An idea", text: "A place you might go. Put it on a day later.", kind: "place" },
];

/** The form a preset opens straight into. */
const formFor = (kind: EntryKind): "booking" | "plan" | "idea" =>
  kind === "place" ? "idea" : kind === "activity" ? "plan" : "booking";

const FORM_TITLES = { booking: "Add a booking", plan: "Add a plan", idea: "Add an idea" };

const ICONS = {
  booking: <path d="M4 7h16v3a2 2 0 0 0 0 4v3H4v-3a2 2 0 0 0 0-4zM14 7v10" />,
  plan: <path d="M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM3 10h18M8 3v4M16 3v4" />,
  idea: <path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11zM12 7.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z" />,
};

function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

const HINTS: Partial<Record<EntryKind, string>> = {
  hotel: 'e.g. "Hotel Ume 13 to 15 Nov, ref 8812, booked on Agoda"',
  flight: 'e.g. "SQ12 to Tokyo on 10 Nov at 08:25, ref ZK4P7Q"',
};
const HINT = 'e.g. "Dinner at Sushi Ten on Thursday at 7pm" or "Hotel Ume 13 to 15 Nov"';

type Line = { who: "you" | "nexus"; text: string; buttons?: Reply["buttons"] };

// On a phone the keyboard would open while the sheet is still sliding up, jolting
// it; there the field waits for a tap.
const finePointer = () => typeof window !== "undefined" && window.matchMedia?.("(pointer: fine)").matches === true;

/** Telling Nexus about a booking in a sentence, without leaving the trip. What it
 * reads is shown, and anything it changes waits for Confirm, as in the chat. */
function TypeIt({ trip, preset, onChanged }: { trip: Trip; preset: AddPreset | null; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const when = `${formatShortDate(trip.start, "UTC")} to ${formatShortDate(trip.end, "UTC")}`;

  // A block body: newer browsers return a promise from scrollIntoView, and an effect
  // must return nothing or a clean-up function.
  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest" });
  }, [lines]);

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
          autoFocus={finePointer()}
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

/** The trip's one way to add something: a booking, a plan or an idea in a short form,
 * or the quick ways: type it, show a screenshot, find a place. */
export function AddSheet({
  trip,
  preset,
  places,
  lists,
  viewing,
  onScreenshot,
  onChanged,
  onClose,
}: {
  trip: Trip;
  preset: AddPreset | null;
  places: boolean;
  onScreenshot: (file: File) => void;
  /** The trip's idea lists, for a new idea's list. */
  lists?: string[];
  /** The day open on Plan, where a new plan or booking goes by default. */
  viewing?: string | null;
  onChanged: () => void;
  onClose: () => void;
}) {
  const home = useHome();
  const [view, setView] = useState<"menu" | "type" | "booking" | "plan" | "idea" | "place">(
    preset?.find && places ? "place" : preset ? formFor(preset.kind) : "menu",
  );
  // Back to the choices and into another form: it starts on the kind picked there.
  const [kind, setKind] = useState<EntryKind>(preset?.kind ?? "flight");

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [onClose]);

  const form = view === "booking" || view === "plan" || view === "idea";
  const title = view === "type" ? "Type it" : view === "place" ? "Find a place" : form ? FORM_TITLES[view] : `Add to ${trip.destination}`;
  return (
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="add-sheet" role="dialog" aria-modal="true" aria-labelledby="add-sheet-title">
        <div className="add-sheet-head">
          {view !== "menu" && (
            <button type="button" className="btn btn-ghost btn-small" onClick={() => setView("menu")} aria-label="Back to the ways to add">
              ‹
            </button>
          )}
          <h2 id="add-sheet-title">{title}</h2>
          <button type="button" className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {view === "menu" && (
          <>
            <div className="ways">
              {CHOICES.map((c) => (
                <button
                  key={c.form}
                  type="button"
                  className="way main"
                  onClick={() => {
                    setKind(c.kind);
                    setView(c.form);
                  }}
                >
                  <span className="way-icon" aria-hidden="true">
                    <Icon name={c.form} />
                  </span>
                  <span>
                    <strong>{c.title}</strong>
                    <span className="caption">{c.text}</span>
                  </span>
                </button>
              ))}
            </div>
            <div className="quick-ways">
              <span className="caption">Quick ways</span>
              <div className="quick">
                <button type="button" className="btn" onClick={() => setView("type")}>
                  Type it
                </button>
                <label className="btn">
                  Screenshot or photo
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
                  <button type="button" className="btn" onClick={() => setView("place")}>
                    Find a place
                  </button>
                )}
              </div>
            </div>
          </>
        )}

        {view === "type" && <TypeIt trip={trip} preset={preset} onChanged={onChanged} />}

        {form && (
          <EntryEditor
            key={view}
            trip={trip}
            home={home || trip.currency}
            lists={lists}
            preset={{ kind, day: preset?.day ?? viewing ?? undefined }}
            onDone={(saved) => {
              if (saved) onChanged();
              onClose();
            }}
          />
        )}

        {view === "place" && <SavePlaces open day={preset?.find ? preset.day : undefined} at={preset?.find ? preset.at : undefined} onDone={onChanged} />}
      </section>
    </div>
  );
}
