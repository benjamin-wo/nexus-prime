import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { api, type Trip, type TripShare } from "../api";
import { Sheet } from "../components/Sheet";
import { PeopleSection } from "./TripPeople";

/** The trip's share sheet. People: who is on the trip, inviting someone (the owner) or leaving
 * (a member). Read-only link, for the owner only: made, copied, replaced or stopped here;
 * whoever has it sees the plan and nothing else. ``onLeft``: a member left the trip. */
export function ShareSheet({ trip, onClose, onLeft }: { trip: Trip; onClose: () => void; onLeft?: () => void }) {
  const member = trip.role === "member";
  return (
    <Sheet title={member ? "People on this trip" : "Share the plan"} titleId="share-sheet-title" className="share-sheet" onClose={onClose}>
      <PeopleSection trip={trip} onLeft={onLeft ?? onClose} />
      {!member && <ReadOnlyLink trip={trip} />}
    </Sheet>
  );
}

/** The read-only link and its switch: the owner's alone. */
function ReadOnlyLink({ trip }: { trip: Trip }) {
  const client = useQueryClient();
  const key = ["trip-share", trip.id];
  const share = useQuery({ queryKey: key, queryFn: () => api<TripShare>(`/travel/trips/${trip.id}/share`) });
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Before there is a link the switch only picks what the new link will start with.
  const [draft, setDraft] = useState(true);
  const [saved, setSaved] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const token = share.data?.token ?? null;
  const showBookings = token ? (share.data?.show_bookings ?? true) : draft;
  const link = token ? `${window.location.origin}/shared/${token}` : null;

  async function change(call: () => Promise<TripShare | undefined>): Promise<boolean> {
    setBusy(true);
    setError(null);
    setCopied(false);
    setSaved(false);
    try {
      const result = await call();
      client.setQueryData(key, result ?? { token: null, show_bookings: true });
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't change the link. Try again.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  const create = () => change(() => api<TripShare>(`/travel/trips/${trip.id}/share`, { method: "POST", body: { show_bookings: draft } }));
  const renew = () => {
    if (!window.confirm("Make a new link? The old one stops working, so anyone using it needs the new one.")) return;
    void change(() => api<TripShare>(`/travel/trips/${trip.id}/share`, { method: "POST", body: { renew: true } }));
  };
  async function toggleBookings(on: boolean) {
    if (!token) {
      setDraft(on);
      return;
    }
    const ok = await change(() => api<TripShare>(`/travel/trips/${trip.id}/share`, { method: "POST", body: { show_bookings: on } }));
    setSaved(ok);
  }
  const stop = () => {
    if (!window.confirm("Stop sharing? The link stops working for everyone who has it.")) return;
    void change(() => api<undefined>(`/travel/trips/${trip.id}/share`, { method: "DELETE" }));
  };

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Some in-app browsers block the clipboard: select it to copy by hand.
      field.current?.select();
    }
  }

  return (
    <section className="share-section" aria-labelledby="share-readonly">
      <h3 id="share-readonly">Read-only link</h3>
      <p className="caption">Shows the days, plans and ideas. Never money, booking references, notes or who's going.</p>
      <label className="share-switch">
        <input
          type="checkbox"
          role="switch"
          checked={showBookings}
          disabled={busy || !share.isSuccess}
          onChange={(e) => void toggleBookings(e.target.checked)}
        />
        <span>Show bookings (flights, stays, tickets)</span>
      </label>
      <p className="caption share-saved" role="status">
        {saved ? "Saved" : ""}
      </p>
      {share.isLoading && <p className="caption">Loading…</p>}
      {share.isError && (
        <p className="error-text" role="alert">
          Couldn't check the link. Try again.
        </p>
      )}
      {share.isSuccess && !link && (
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void create()}>
          {busy ? "Making the link…" : "Create a link"}
        </button>
      )}
      {link && (
        <>
          <div className="share-link">
            <label className="sr-only" htmlFor="share-link">
              The trip's link
            </label>
            <input id="share-link" ref={field} className="input" value={link} readOnly onFocus={(e) => e.target.select()} />
            <button type="button" className="btn btn-primary" onClick={() => void copy()}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <div className="share-actions">
            <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={renew}>
              Make a new link
            </button>
            <button type="button" className="btn btn-ghost btn-danger btn-small" disabled={busy} onClick={stop}>
              Stop sharing
            </button>
          </div>
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
