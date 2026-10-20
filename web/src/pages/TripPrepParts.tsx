import { type FormEvent, type KeyboardEvent, type RefObject, useRef, useState } from "react";

import { api, tripCoverLogPath, tripCoversPath, type Cover, type CoverIn, type CoverKind, type Todo, type Trip } from "../api";
import { Icon, type IconName } from "../components/Icon";
import { Sheet } from "../components/Sheet";
import { formatMoney } from "../format";
import { isMember, useHome } from "./TripBits";
import { dayName } from "./TripEntry";

// The parts of the Prep tab: to-do rows and their form, cover and document rows and their sheet, the
// confirmation before a cover's cost is logged (Prep and Money both use it) and the + button's choice.

const failure = (e: unknown, fallback: string) => (e instanceof Error ? e.message : fallback);

export const COVER_KINDS: CoverKind[] = ["insurance", "visa", "document", "other"];
export const KIND_LABEL: Record<CoverKind, string> = { insurance: "Insurance", visa: "Visa", document: "Document", other: "Other" };
const KIND_ICON: Record<CoverKind, IconName> = { insurance: "shield", visa: "stamp", document: "document", other: "document" };

/** The day on this device, YYYY-MM-DD, which is what a to-do's date is compared with. */
export const localDay = (when: Date = new Date()) => when.toLocaleDateString("en-CA");

/** The dates a cover holds: "2–9 Dec", "28 Nov – 3 Dec", "2 Dec", "from 2 Dec" or "until 9 Dec". */
export function coverDates(starts: string | null, ends: string | null): string {
  const parts = (iso: string) => {
    const p = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).formatToParts(new Date(`${iso}T00:00:00Z`));
    const get = (type: string) => p.find((x) => x.type === type)?.value ?? "";
    return { day: get("day"), month: get("month"), year: get("year") };
  };
  if (starts && ends) {
    if (starts === ends) return `${parts(starts).day} ${parts(starts).month}`;
    const a = parts(starts);
    const b = parts(ends);
    if (a.month === b.month && a.year === b.year) return `${a.day}–${b.day} ${b.month}`;
    return `${a.day} ${a.month} – ${b.day} ${b.month}`;
  }
  if (starts) return `from ${parts(starts).day} ${parts(starts).month}`;
  if (ends) return `until ${parts(ends).day} ${parts(ends).month}`;
  return "";
}

/** A cover's one quiet line: "Insurance · TX-4471 · 2–9 Dec". */
export const coverSub = (c: Cover): string => [KIND_LABEL[c.kind], c.reference, coverDates(c.starts, c.ends)].filter(Boolean).join(" · ");

// --- to-dos -------------------------------------------------------------------------------

/** What a to-do's date line says: "By Tue 8 Dec", or "Overdue · Tue 8 Dec" in the warning colour once past and not done. */
export function dueLine(todo: Todo, today: string): { text: string; overdue: boolean } | null {
  if (!todo.due) return null;
  const overdue = !todo.done && todo.due < today;
  return { text: overdue ? `Overdue · ${dayName(todo.due)}` : `By ${dayName(todo.due)}`, overdue };
}

/** One to-do: a round checkbox named by its text, the date under it and a quiet remove button. */
export function TodoRow({ todo, today, onToggle, onRemove }: { todo: Todo; today: string; onToggle: () => void; onRemove: () => void }) {
  const id = `prep-todo-${todo.id}`;
  const due = dueLine(todo, today);
  return (
    <li className={`prep-row prep-todo${todo.done ? " is-done" : ""}`}>
      <input id={id} type="checkbox" className="prep-check" checked={todo.done} onChange={onToggle} aria-describedby={due ? `${id}-due` : undefined} />
      <div className="prep-main">
        <label htmlFor={id} className="prep-title">
          {todo.text}
        </label>
        {due && (
          <span id={`${id}-due`} className={`prep-sub${due.overdue ? " is-overdue" : ""}`}>
            {due.text}
          </span>
        )}
      </div>
      <button type="button" className="btn btn-ghost prep-remove" aria-label={`Remove ${todo.text}`} onClick={onRemove}>
        <Icon name="x" size={18} />
      </button>
    </li>
  );
}

/** The inline form under the list. ``onAdd`` answers whether it went through; the fields clear when it did. */
export function AddTodoForm({ onAdd, inputRef }: { onAdd: (text: string, due: string | null) => Promise<boolean>; inputRef: RefObject<HTMLInputElement | null> }) {
  const [text, setText] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      if (await onAdd(text.trim(), due || null)) {
        setText("");
        setDue("");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="prep-add" onSubmit={(e) => void submit(e)} aria-label="Add a to-do">
      <div className="prep-add-row">
        <input ref={inputRef} className="input prep-add-text" value={text} maxLength={80} onChange={(e) => setText(e.target.value)} placeholder="Add a to-do, e.g. Book the airport taxi" aria-label="To-do" />
        <label className="field prep-add-date">
          By (optional)
          <input className="input" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-soft" disabled={!text.trim() || busy}>
          Add
        </button>
      </div>
      <p className="caption">With a date, Nexus reminds you the day before.</p>
    </form>
  );
}

// --- cover and documents ------------------------------------------------------------------

/** The reference, with a button that copies it for the counter or the app. */
export function CopyReference({ reference }: { reference: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(reference);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <button type="button" className="btn btn-ghost btn-small prep-act" onClick={() => void copy()} aria-label={`Copy reference ${reference}`}>
      <Icon name="copy" size={16} />
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/** Logging a cover's cost as an expense: asked first, in place. Nexus only writes it down. */
export function useCoverLog(tripId: string, cover: Cover, onLogged: (logged: Cover) => void) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function log() {
    setBusy(true);
    setError(null);
    try {
      const logged = await api<Cover>(tripCoverLogPath(tripId, cover.id), { method: "POST" });
      setConfirming(false);
      onLogged(logged);
    } catch (e) {
      setError(failure(e, "Couldn't log that"));
    } finally {
      setBusy(false);
    }
  }
  return {
    confirming,
    busy,
    error,
    ask: () => {
      setError(null);
      setConfirming(true);
    },
    cancel: () => setConfirming(false),
    log,
  };
}
export type CoverLog = ReturnType<typeof useCoverLog>;

/** The tinted box that asks before a cover's cost is recorded. */
export function LogConfirm({ cover, log }: { cover: Cover; log: CoverLog }) {
  if (!cover.cost) return null;
  return (
    <div className="confirm-box" role="group" aria-label={`Log ${cover.name}`}>
      <p>Record {formatMoney(cover.cost)} as spent on Travel? Nexus only records it.</p>
      <div className="people-actions">
        <button type="button" className="btn btn-primary" disabled={log.busy} onClick={() => void log.log()}>
          {log.busy ? "Logging…" : "Log it"}
        </button>
        <button type="button" className="btn btn-ghost" disabled={log.busy} onClick={log.cancel}>
          Not now
        </button>
      </div>
      {log.error && (
        <p className="error-text" role="alert">
          {log.error}
        </p>
      )}
    </div>
  );
}

/** "Logged" with a tick, or the soft Log it that asks first. Nothing for a cover with no cost. */
export function LogAction({ cover, log, label = "Log it" }: { cover: Cover; log: CoverLog; label?: string }) {
  if (!cover.cost) return null;
  if (cover.logged) {
    return (
      <span className="prep-logged">
        <Icon name="check" size={16} />
        Logged
      </span>
    );
  }
  if (log.confirming) return null;
  return (
    <button type="button" className="btn btn-soft btn-small" aria-label={`${label}: ${cover.name}`} onClick={log.ask}>
      {label}
    </button>
  );
}

/** One cover or document: its icon, name and one line; the cost and Logged/Log it for the owner;
 * Call and Copy underneath. The name opens it to change. */
export function CoverRow({ cover, tripId, onOpen, onLogged }: { cover: Cover; tripId: string; onOpen: () => void; onLogged: (logged: Cover) => void }) {
  const log = useCoverLog(tripId, cover, onLogged);
  const callable = cover.phone ? cover.phone.replace(/[^\d+]/g, "") : "";
  return (
    <li className="prep-cover">
      <div className="prep-row">
        <span className="prep-icon" aria-hidden="true">
          <Icon name={KIND_ICON[cover.kind]} size={20} />
        </span>
        <button type="button" className="prep-main prep-open" onClick={onOpen}>
          <span className="prep-title">{cover.name}</span>
          <span className="prep-sub">{coverSub(cover)}</span>
        </button>
        {cover.cost && (
          <span className="prep-cost">
            <span className="num">{formatMoney(cover.cost)}</span>
            <LogAction cover={cover} log={log} />
          </span>
        )}
      </div>
      {(cover.phone || cover.reference) && (
        <div className="prep-acts">
          {cover.phone && (
            <a className="btn btn-ghost btn-small prep-act" href={`tel:${callable}`}>
              <Icon name="phone" size={16} />
              Call {cover.phone}
            </a>
          )}
          {cover.reference && <CopyReference reference={cover.reference} />}
        </div>
      )}
      {log.confirming && <LogConfirm cover={cover} log={log} />}
    </li>
  );
}

/** Insurance, Visa, Document, Other: one choice, a radio group of chips. */
function KindChips({ value, onChange }: { value: CoverKind; onChange: (kind: CoverKind) => void }) {
  const chips = useRef<(HTMLButtonElement | null)[]>([]);
  function move(event: KeyboardEvent, from: number) {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const to = (from + step + COVER_KINDS.length) % COVER_KINDS.length;
    onChange(COVER_KINDS[to]);
    chips.current[to]?.focus();
  }
  return (
    <div className="chips" role="radiogroup" aria-label="Kind">
      {COVER_KINDS.map((k, i) => (
        <button
          key={k}
          ref={(el) => {
            chips.current[i] = el;
          }}
          type="button"
          role="radio"
          aria-checked={value === k}
          tabIndex={value === k ? 0 : -1}
          className="day-pill"
          onClick={() => onChange(k)}
          onKeyDown={(e) => move(e, i)}
        >
          {KIND_LABEL[k]}
        </button>
      ))}
    </div>
  );
}

const blank = (v: string) => v.trim() || null;

/** Add or change a cover or document, in a Sheet. The cost is the owner's: a member of the trip sees no
 * cost fields. ``kind`` presets a new one (from a suggestion). Delete is inside, asked first. */
export function CoverSheet({
  trip,
  cover,
  kind,
  onSaved,
  onDeleted,
  onClose,
}: {
  trip: Trip;
  cover: Cover | null;
  kind?: CoverKind;
  onSaved: (saved: Cover) => void;
  onDeleted: (id: string) => void;
  onClose: () => void;
}) {
  const home = useHome();
  const member = isMember(trip);
  const [form, setForm] = useState({
    kind: cover?.kind ?? kind ?? "insurance",
    name: cover?.name ?? "",
    reference: cover?.reference ?? "",
    phone: cover?.phone ?? "",
    starts: cover?.starts ?? "",
    ends: cover?.ends ?? "",
    cost: cover?.cost ? String(Number(cover.cost.amount)) : "",
    currency: null as string | null,
    note: cover?.note ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (key: "name" | "reference" | "phone" | "starts" | "ends" | "cost" | "note") => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const currency = form.currency ?? cover?.cost?.currency ?? (home || trip.currency);
  const insurance = form.kind === "insurance";

  async function save(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setError(null);
    const cost = form.cost.replace(/,/g, "").trim();
    if (!member && cost && !(Number(cost) > 0)) {
      setError("Enter the cost as a number, like 89.");
      return;
    }
    const body: CoverIn = {
      kind: form.kind,
      name: form.name.trim(),
      reference: blank(form.reference),
      phone: blank(form.phone),
      starts: form.starts || null,
      ends: form.ends || null,
      note: blank(form.note),
    };
    // The cost is the owner's: a member's request carries none (the server refuses one).
    if (!member) {
      body.cost = cost || null;
      body.currency = cost ? currency.trim().toUpperCase() : null;
    }
    setBusy(true);
    try {
      const saved = await api<Cover>(tripCoversPath(trip.id, cover?.id), { method: cover ? "PUT" : "POST", body });
      onSaved(saved);
    } catch (e) {
      setError(failure(e, "Couldn't save that"));
      setBusy(false);
    }
  }

  async function remove() {
    if (!cover || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api(tripCoversPath(trip.id, cover.id), { method: "DELETE" });
      onDeleted(cover.id);
    } catch (e) {
      setError(failure(e, "Couldn't delete that"));
      setBusy(false);
    }
  }

  return (
    <Sheet
      title={cover ? `Change ${cover.name}` : "Add cover or a document"}
      onClose={onClose}
      as="form"
      onSubmit={(e) => void save(e)}
      className="prep-sheet"
      footer={
        <div className="prep-sheet-foot">
          {cover && !asking && (
            <button type="button" className="btn btn-ghost btn-danger" disabled={busy} onClick={() => setAsking(true)}>
              <Icon name="trash" size={16} />
              Delete
            </button>
          )}
          <button type="submit" className="btn btn-primary" disabled={busy || !form.name.trim()}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      }
    >
      <div className="trip-form">
        <KindChips value={form.kind} onChange={(k) => setForm({ ...form, kind: k })} />
        <label className="field">
          {insurance ? "Insurer" : "Name"}
          <input className="input" value={form.name} maxLength={80} onChange={set("name")} placeholder={insurance ? "Harbour Cover" : form.kind === "visa" ? "Japan e-visa" : "Vaccination certificate"} required />
        </label>
        <label className="field">
          Policy or reference
          <input className="input" value={form.reference} maxLength={60} onChange={set("reference")} placeholder={insurance ? "TX-4471" : undefined} autoComplete="off" />
        </label>
        <label className="field">
          Emergency phone
          <input className="input" type="tel" value={form.phone} maxLength={30} onChange={set("phone")} placeholder="+65 6123 4567" autoComplete="off" />
        </label>
        <div className="trip-form-row">
          <label className="field">
            From
            <input className="input" type="date" value={form.starts} onChange={set("starts")} />
          </label>
          <label className="field">
            To
            <input className="input" type="date" value={form.ends} min={form.starts || undefined} onChange={set("ends")} />
          </label>
        </div>
        {!member && (
          <div className="trip-form-row">
            <label className="field">
              Cost
              <input className="input" inputMode="decimal" value={form.cost} onChange={set("cost")} placeholder="89" autoComplete="off" />
            </label>
            <label className="field">
              Currency
              <input className="input" value={currency} maxLength={3} onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} autoComplete="off" />
            </label>
          </div>
        )}
        <label className="field">
          Note
          <textarea className="input" rows={2} value={form.note} maxLength={200} onChange={set("note")} />
        </label>
        {asking && cover && (
          <div className="confirm-box" role="group" aria-label={`Delete ${cover.name}`}>
            <p>Delete {cover.name}? An expense you already logged for it stays in the ledger.</p>
            <div className="people-actions">
              <button type="button" className="btn btn-ghost btn-danger" disabled={busy} onClick={() => void remove()}>
                <Icon name="trash" size={16} />
                {busy ? "Deleting…" : `Delete ${cover.name}`}
              </button>
              <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setAsking(false)}>
                Keep it
              </button>
            </div>
          </div>
        )}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
      </div>
    </Sheet>
  );
}

// --- the + button -------------------------------------------------------------------------

export type PrepChoice = "todo" | "cover" | "pack";

const CHOICES: { choice: PrepChoice; icon: IconName; title: string; text: string }[] = [
  { choice: "todo", icon: "checkbox", title: "A to-do", text: "Something to sort before you go. With a date, you get a reminder." },
  { choice: "cover", icon: "shield", title: "Cover or a document", text: "Insurance, a visa or another document." },
  { choice: "pack", icon: "suitcase", title: "Something to pack", text: "Add it to the packing list." },
];

/** What the Prep tab's + adds. Picking one closes this and takes you to the matching form. */
export function PrepChoiceSheet({ onPick, onClose }: { onPick: (choice: PrepChoice) => void; onClose: () => void }) {
  return (
    <Sheet title="Add to prep" onClose={onClose}>
      <div className="ways">
        {CHOICES.map((c) => (
          <button key={c.choice} type="button" className="way" onClick={() => onPick(c.choice)}>
            <span className="way-icon" aria-hidden="true">
              <Icon name={c.icon} size={22} />
            </span>
            <span>
              <strong>{c.title}</strong>
              <span className="caption">{c.text}</span>
            </span>
          </button>
        ))}
      </div>
    </Sheet>
  );
}
