import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, type Trip, type TripShare } from "../api";

/** The trip's read-only link: made, copied, replaced or stopped here. Whoever has it
 * sees the plan and nothing else. */
export function ShareSheet({ trip, onClose }: { trip: Trip; onClose: () => void }) {
  const client = useQueryClient();
  const key = ["trip-share", trip.id];
  const share = useQuery({ queryKey: key, queryFn: () => api<TripShare>(`/travel/trips/${trip.id}/share`) });
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const token = share.data?.token ?? null;
  const link = token ? `${window.location.origin}/shared/${token}` : null;

  useEffect(() => {
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [onClose]);

  async function change(call: () => Promise<TripShare | undefined>) {
    setBusy(true);
    setError(null);
    setCopied(false);
    try {
      const result = await call();
      client.setQueryData(key, result ?? { token: null });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't change the link. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const create = () => change(() => api<TripShare>(`/travel/trips/${trip.id}/share`, { method: "POST", body: {} }));
  const renew = () => {
    if (!window.confirm("Make a new link? The old one stops working, so anyone using it needs the new one.")) return;
    void change(() => api<TripShare>(`/travel/trips/${trip.id}/share`, { method: "POST", body: { renew: true } }));
  };
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
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="add-sheet share-sheet" role="dialog" aria-modal="true" aria-labelledby="share-sheet-title">
        <div className="add-sheet-head">
          <h2 id="share-sheet-title">Share the plan</h2>
          <button type="button" className="btn btn-ghost btn-small" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="caption">
          Anyone with the link can see the days, times, flights, trains, places to stay and plans, with their addresses. Nobody can change anything.
        </p>
        <ul className="share-hidden" aria-label="Kept private">
          <li>Prices, the budget and spending</li>
          <li>Booking references and where it was booked</li>
          <li>Notes and who's going</li>
        </ul>
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
              <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={stop}>
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
    </div>
  );
}
