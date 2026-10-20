import { type FormEvent, type RefObject, useEffect, useRef, useState } from "react";

import {
  api,
  tripDismissPath,
  tripNotesPath,
  tripTodosPath,
  type Cover,
  type CoverKind,
  type Prep,
  type PrepSuggestion,
  type Todo,
  type TodoIn,
  type Trip,
  type TripDetail,
} from "../api";
import { Icon } from "../components/Icon";
import { PackingCard, WeatherCard } from "./TripExtras";
import { AddTodoForm, CoverRow, CoverSheet, localDay, PrepChoiceSheet, TodoRow, type PrepChoice } from "./TripPrepParts";
import { useAppRole } from "./TripBits";
import { type Fix, sortedText, stillToSort } from "./TripStage";

const failure = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

/** The trip's notes, edited where they're read. Saves on the button or when the field is left. */
function NotesEditor({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const saved = trip.notes?.trim() ?? "";
  const [text, setText] = useState(saved);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sending = useRef(false);
  const changed = text.trim() !== saved;

  // Follow the trip when it's reloaded (a save, or an edit made elsewhere).
  useEffect(() => setText(saved), [saved]);
  useEffect(() => {
    if (!done) return;
    const timer = window.setTimeout(() => setDone(false), 2000);
    return () => window.clearTimeout(timer);
  }, [done]);

  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (!changed || sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
    try {
      // Its own endpoint, so it changes the notes and nothing else: the only way a member can, and the same for the owner.
      await api(tripNotesPath(trip.id), { method: "PUT", body: { notes: text.trim() || null } });
      onChange();
      setDone(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the notes");
    } finally {
      sending.current = false;
      setBusy(false);
    }
  }

  return (
    <section className="card prep-notes" aria-labelledby="trip-notes">
      <div className="card-head">
        <h2 id="trip-notes">Notes</h2>
        {done && (
          <span className="caption" role="status">
            Saved
          </span>
        )}
      </div>
      <form onSubmit={(e) => void save(e)} aria-label="Trip notes">
        <label className="field">
          Notes
          <textarea
            className="input"
            rows={5}
            value={text}
            maxLength={4000}
            onChange={(e) => setText(e.target.value)}
            onBlur={() => void save()}
            placeholder="Visa details, a friend's address, what to remember…"
          />
        </label>
        <div className="prep-notes-actions">
          <button type="submit" className="btn btn-primary" disabled={!changed || busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

const NO_TODOS: Todo[] = [];
const NO_COVERS: Cover[] = [];
const NO_SUGGESTIONS: PrepSuggestion[] = [];
const prepOf = (d: TripDetail): Prep => ({ todos: d.todos ?? NO_TODOS, covers: d.covers ?? NO_COVERS, prep_suggestions: d.prep_suggestions ?? NO_SUGGESTIONS });
const asIn = (t: Todo): TodoIn => ({ id: t.id, text: t.text, due: t.due, done: t.done });
/** The kind a suggested cover opens the sheet with: its own where it names one, else a document. */
const kindOfSuggestion = (s: PrepSuggestion): CoverKind => (s.key === "insurance" || s.key === "visa" ? s.key : "document");

/** Getting ready: what's still to sort, what Nexus suggests and the to-dos, in one list. Done to-dos sink to the bottom. */
function GettingReady({
  detail,
  prep,
  busy,
  error,
  onFix,
  onAddTodo,
  onToggle,
  onRemove,
  onDismiss,
  onCover,
  inputRef,
}: {
  detail: TripDetail;
  prep: Prep;
  busy: string | null;
  error: string | null;
  onFix: (fix: Fix) => void;
  onAddTodo: (text: string, due: string | null) => Promise<boolean>;
  onToggle: (id: string) => void;
  onRemove: (id: string) => void;
  onDismiss: (key: string) => void;
  onCover: (kind: CoverKind) => void;
  inputRef: RefObject<HTMLInputElement | null>;
}) {
  const finished = detail.trip.status === "finished";
  const gaps = finished ? [] : stillToSort(detail);
  const suggestions = finished ? [] : prep.prep_suggestions;
  const open = prep.todos.filter((t) => !t.done);
  const done = prep.todos.filter((t) => t.done);
  const count = gaps.length + suggestions.length + open.length;
  const today = localDay();
  // Once the trip is over there is nothing to get ready for; to-dos still left are shown, not added to.
  if (finished && prep.todos.length === 0) return null;
  return (
    <section className="card prep-card" aria-labelledby="prep-ready">
      <div className="card-head">
        <h2 id="prep-ready">Getting ready</h2>
        {count > 0 && <span className="caption">{count} to do</span>}
      </div>
      {count === 0 && !finished && (
        <p className="sorted-line" role="status">
          <Icon name="check" size={16} className="icon-inline" />
          {sortedText(detail)}
        </p>
      )}
      {count + done.length > 0 && (
        <ul className="prep-rows" aria-label="Things to do">
          {gaps.map((g) => (
            <li key={g.text} className="prep-row prep-gap">
              <span className="prep-icon is-warn" aria-hidden="true">
                <Icon name="alert" size={20} />
              </span>
              <div className="prep-main">
                <span className="prep-title">{g.text}</span>
              </div>
              <button type="button" className="btn btn-soft btn-small" onClick={() => onFix(g.fix)} aria-label={`${g.action}: ${g.text}`}>
                {g.action}
              </button>
            </li>
          ))}
          {suggestions.map((s) => (
            <li key={s.key} className="prep-row prep-suggestion">
              <span className="prep-icon" aria-hidden="true">
                <Icon name="sparkle" size={20} />
              </span>
              <div className="prep-main">
                <span className="prep-title">{s.text}</span>
                <span className="prep-sub">{s.sub}</span>
              </div>
              <div className="prep-actions">
                <button
                  type="button"
                  className="btn btn-soft btn-small"
                  disabled={busy !== null}
                  aria-label={`Add: ${s.text}`}
                  onClick={() => (s.action === "add_cover" ? onCover(kindOfSuggestion(s)) : void onAddTodo(s.text, null))}
                >
                  Add
                </button>
                <button type="button" className="btn btn-ghost btn-small prep-act" disabled={busy !== null} aria-label={`Not needed: ${s.text}`} onClick={() => onDismiss(s.key)}>
                  <Icon name="x" size={16} />
                  Not needed
                </button>
              </div>
            </li>
          ))}
          {[...open, ...done].map((t) => (
            <TodoRow key={t.id} todo={t} today={today} onToggle={() => onToggle(t.id)} onRemove={() => onRemove(t.id)} />
          ))}
        </ul>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {!finished && <AddTodoForm onAdd={onAddTodo} inputRef={inputRef} />}
    </section>
  );
}

/** Cover and documents: insurance, visas and other documents, with a way to call and to copy the reference. */
function CoverCard({
  trip,
  covers,
  onOpen,
  onLogged,
}: {
  trip: Trip;
  covers: Cover[];
  onOpen: (cover: Cover | null) => void;
  onLogged: (cover: Cover) => void;
}) {
  const role = useAppRole();
  // Once the trip is over nothing is added; what was kept is still there to read.
  if (trip.status === "finished" && covers.length === 0) return null;
  return (
    <section className="card prep-card" aria-labelledby="prep-cover">
      <div className="card-head">
        <h2 id="prep-cover">Cover and documents</h2>
      </div>
      {covers.length === 0 ? (
        <p className="state">Travel insurance, visas and other documents go here.</p>
      ) : (
        <ul className="prep-rows" aria-label="Cover and documents">
          {covers.map((c) => (
            <CoverRow key={c.id} cover={c} tripId={trip.id} onOpen={() => onOpen(c)} onLogged={onLogged} />
          ))}
        </ul>
      )}
      {trip.status !== "finished" && (
        <button type="button" className="btn btn-ghost prep-add-cover" onClick={() => onOpen(null)}>
          <Icon name="plus" size={16} />
          Add cover or a document
        </button>
      )}
      {/* A guest has no chat to tell. */}
      {trip.status !== "finished" && role !== "guest" && <p className="caption">Or tell Nexus: "Add travel insurance, Harbour Cover, SGD 89, policy TX-4471".</p>}
    </section>
  );
}

/** The Prep tab: getting ready (what's still to sort, suggestions and to-dos), cover and documents,
 * packing, the weather and the trip's notes. ``adding``: the tab's + was pressed, which asks what to add. */
export function PrepTab({ detail, onChange, onFix, adding, onAddDone }: { detail: TripDetail; onChange: () => void; onFix: (fix: Fix) => void; adding: boolean; onAddDone: () => void }) {
  const { trip } = detail;
  const [prep, setPrep] = useState<Prep>(() => prepOf(detail));
  // Follow the trip when it's reloaded (a save here, or a change made by someone else on it).
  useEffect(() => setPrep(prepOf(detail)), [detail.todos, detail.covers, detail.prep_suggestions]); // eslint-disable-line react-hooks/exhaustive-deps
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<"choose" | { cover: Cover | null; kind?: CoverKind } | null>(null);
  const [focus, setFocus] = useState<"todo" | "pack" | null>(null);
  const todoInput = useRef<HTMLInputElement>(null);
  const latest = useRef(prep);
  latest.current = prep;
  const sent = useRef(0);

  // The + asks what to add.
  useEffect(() => {
    if (!adding) return;
    setSheet("choose");
    onAddDone();
  }, [adding, onAddDone]);
  // A to-do chosen from there: bring its field into view and put the cursor in it.
  useEffect(() => {
    if (focus !== "todo") return;
    todoInput.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    todoInput.current?.focus({ preventScroll: true });
    setFocus(null);
  }, [focus]);

  /** Saves the whole to-do list. ``shown``: what to show while it saves (put back if it fails). */
  async function saveTodos(next: TodoIn[], shown?: Todo[]): Promise<boolean> {
    const mine = ++sent.current;
    const before = latest.current;
    setError(null);
    if (shown) setPrep({ ...before, todos: shown });
    try {
      const saved = await api<Prep>(tripTodosPath(trip.id), { method: "PUT", body: { todos: next } });
      if (mine === sent.current) setPrep(saved);
      onChange();
      return true;
    } catch (e) {
      if (shown && mine === sent.current) setPrep(before);
      setError(failure(e, "Couldn't save the to-dos"));
      return false;
    }
  }

  const todos = () => latest.current.todos;
  const toggle = (id: string) => {
    const next = todos().map((t) => (t.id === id ? { ...t, done: !t.done } : t));
    void saveTodos(next.map(asIn), next);
  };
  const remove = (id: string) => {
    const next = todos().filter((t) => t.id !== id);
    void saveTodos(next.map(asIn), next);
  };
  async function addTodo(text: string, due: string | null): Promise<boolean> {
    setBusy("todo");
    try {
      return await saveTodos([...todos().map(asIn), { text, due, done: false }]);
    } finally {
      setBusy(null);
    }
  }
  async function dismiss(key: string) {
    setBusy(key);
    setError(null);
    try {
      setPrep(await api<Prep>(tripDismissPath(trip.id), { method: "POST", body: { key } }));
      onChange();
    } catch (e) {
      setError(failure(e, "Couldn't do that"));
    } finally {
      setBusy(null);
    }
  }

  /** A cover that was added or changed, or logged: in the list at once, and the rest follows the reload. */
  function covered(saved: Cover) {
    setPrep((p) => {
      const has = p.covers.some((c) => c.id === saved.id);
      return {
        ...p,
        covers: has ? p.covers.map((c) => (c.id === saved.id ? saved : c)) : [...p.covers, saved],
        prep_suggestions: p.prep_suggestions.filter((s) => s.key !== saved.kind),
      };
    });
    onChange();
  }

  function pick(choice: PrepChoice) {
    if (choice === "cover") setSheet({ cover: null });
    else {
      setSheet(null);
      setFocus(choice);
    }
  }

  return (
    <>
      <GettingReady
        detail={detail}
        prep={prep}
        busy={busy}
        error={error}
        onFix={onFix}
        onAddTodo={addTodo}
        onToggle={toggle}
        onRemove={remove}
        onDismiss={(key) => void dismiss(key)}
        onCover={(kind) => setSheet({ cover: null, kind })}
        inputRef={todoInput}
      />
      <CoverCard trip={trip} covers={prep.covers} onOpen={(cover) => setSheet({ cover })} onLogged={covered} />
      <PackingCard key={`pack-${trip.id}`} trip={trip} onChange={onChange} adding={focus === "pack"} onAddDone={() => setFocus(null)} />
      <WeatherCard trip={trip} />
      <NotesEditor key={`notes-${trip.id}`} trip={trip} onChange={onChange} />
      {sheet === "choose" && <PrepChoiceSheet onPick={pick} onClose={() => setSheet(null)} />}
      {sheet !== null && sheet !== "choose" && (
        <CoverSheet
          key={sheet.cover?.id ?? `new-${sheet.kind ?? ""}`}
          trip={trip}
          cover={sheet.cover}
          kind={sheet.kind}
          onSaved={(saved) => {
            covered(saved);
            setSheet(null);
          }}
          onDeleted={(id) => {
            setPrep((p) => ({ ...p, covers: p.covers.filter((c) => c.id !== id) }));
            onChange();
            setSheet(null);
          }}
          onClose={() => setSheet(null)}
        />
      )}
    </>
  );
}
