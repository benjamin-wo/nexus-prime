import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { ApiError, api, type IssuedTripInvite, type Trip, type TripInvite, type TripMember, tripInvitesPath, tripMembersPath } from "../api";
import { formatShortDate } from "../format";
import { Companions } from "./TripBits";

/** Everyone on a trip, the owner first: the members list, reloaded when the window regains focus
 * so someone added or removed elsewhere shows up. */
export function useMembers(tripId: string, enabled = true) {
  return useQuery({
    queryKey: ["trip-members", tripId],
    queryFn: () => api<TripMember[]>(tripMembersPath(tripId)),
    enabled,
    refetchOnWindowFocus: true,
    // A 404 means the person isn't on the trip: asking again won't change it.
    retry: (failures, error) => !(error instanceof ApiError && error.status === 404) && failures < 3,
  });
}

/** The owner first, then the others in the order given. */
export const ownerFirst = (members: TripMember[]): TripMember[] => [...members.filter((m) => m.role === "owner"), ...members.filter((m) => m.role !== "owner")];

/** Whether anyone besides the owner is on the trip. */
export const hasMembers = (members: TripMember[] | undefined): boolean => (members?.length ?? 0) > 1;

/** The faces on the trip's cover: the people on a shared trip (owner first), else the names of
 * those the owner said are going. */
export function TripFaces({ trip, members }: { trip: Pick<Trip, "companions">; members: TripMember[] | undefined }) {
  return <Companions names={hasMembers(members) ? ownerFirst(members ?? []).map((m) => m.name) : trip.companions} />;
}

const dayOf = (iso: string) => formatShortDate(iso);

/** The People part of the share sheet. Everyone sees who is on the trip. The owner makes
 * single-use invite links, cancels the ones still open and removes people; a member can
 * leave. ``onLeft`` runs once they have. */
export function PeopleSection({ trip, onLeft }: { trip: Trip; onLeft: () => void }) {
  const client = useQueryClient();
  const owner = trip.role !== "member";
  const members = useMembers(trip.id);
  const invitesKey = ["trip-invites", trip.id];
  const invites = useQuery({ queryKey: invitesKey, queryFn: () => api<TripInvite[]>(tripInvitesPath(trip.id)), enabled: owner });
  const [issued, setIssued] = useState<IssuedTripInvite | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const people = ownerFirst(members.data ?? []);
  const me = people.find((m) => m.you);

  async function attempt(call: () => Promise<void>, failure: string) {
    setBusy(true);
    setError(null);
    try {
      await call();
    } catch (e) {
      setError(e instanceof Error ? e.message : failure);
    } finally {
      setBusy(false);
    }
  }

  const invite = () =>
    attempt(async () => {
      const made = await api<IssuedTripInvite>(tripInvitesPath(trip.id), { method: "POST" });
      setIssued(made);
      setCopied(false);
      await client.invalidateQueries({ queryKey: invitesKey });
    }, "Couldn't make the link. Try again.");

  const cancel = (id: string) =>
    attempt(async () => {
      await api<undefined>(tripInvitesPath(trip.id, id), { method: "DELETE" });
      if (issued?.id === id) setIssued(null);
      await client.invalidateQueries({ queryKey: invitesKey });
    }, "Couldn't cancel the link. Try again.");

  const remove = (member: TripMember) => {
    if (!window.confirm(`Remove ${member.name} from this trip? They'll lose access straight away.`)) return;
    void attempt(async () => {
      await api<undefined>(tripMembersPath(trip.id, member.id), { method: "DELETE" });
      await client.invalidateQueries({ queryKey: ["trip-members", trip.id] });
      // Their changes stay in the plan; the log of who did what keeps its lines.
      void client.invalidateQueries({ queryKey: ["trip-activity", trip.id] });
    }, "Couldn't remove them. Try again.");
  };

  const leave = () => {
    if (!me || !window.confirm("Leave this trip? You'll lose access straight away.")) return;
    void attempt(async () => {
      await api<undefined>(tripMembersPath(trip.id, me.id), { method: "DELETE" });
      client.removeQueries({ queryKey: ["trip", trip.id] });
      void client.invalidateQueries({ queryKey: ["trips"] });
      onLeft();
    }, "Couldn't leave the trip. Try again.");
  };

  async function copy() {
    if (!issued) return;
    try {
      await navigator.clipboard.writeText(issued.url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Some in-app browsers block the clipboard: select it to copy by hand.
      field.current?.select();
    }
  }

  return (
    <section className="share-section" aria-labelledby="share-people">
      {/* A member's sheet is already titled "People on this trip": the heading stays for screen readers. */}
      <h3 id="share-people" className={owner ? undefined : "sr-only"}>
        People
      </h3>
      {members.isLoading && <p className="caption">Loading…</p>}
      {members.isError && (
        <p className="error-text" role="alert">
          Couldn't load who is on the trip. Try again.
        </p>
      )}
      {people.length > 0 && (
        <ul className="people-list" aria-label="People on this trip">
          {people.map((m) => (
            <li key={m.id} className="people-row">
              <span className="wrap">
                <strong>{m.name}</strong>
                <br />
                <span className="caption">{[m.you ? "You" : null, m.role === "owner" ? "Owner" : "Member"].filter(Boolean).join(" · ")}</span>
              </span>
              {owner && m.role !== "owner" && (
                <button type="button" className="btn btn-ghost btn-danger btn-small" disabled={busy} onClick={() => remove(m)} aria-label={`Remove ${m.name}`}>
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {owner && (
        <>
          {issued ? (
            <div className="share-invite">
              <div className="share-link">
                <label className="sr-only" htmlFor="invite-link">
                  Invite link
                </label>
                <input id="invite-link" ref={field} className="input" value={issued.url} readOnly onFocus={(e) => e.target.select()} />
                <button type="button" className="btn btn-soft" onClick={() => void copy()}>
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <p className="caption">Works once, for 7 days.</p>
            </div>
          ) : null}
          {(invites.data ?? []).length > 0 && (
            <ul className="people-list" aria-label="Invite links not used yet">
              {(invites.data ?? []).map((i) => (
                <li key={i.id} className="people-row">
                  <span className="wrap">
                    <strong>Invite link</strong>
                    <br />
                    <span className="caption">
                      Made {dayOf(i.created_at)} · expires {dayOf(i.expires_at)}
                    </span>
                  </span>
                  <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={() => void cancel(i.id)} aria-label={`Cancel the invite made ${dayOf(i.created_at)}`}>
                    Cancel
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="share-actions">
            <button type="button" className="btn btn-soft" disabled={busy} onClick={() => void invite()}>
              Invite someone
            </button>
          </div>
        </>
      )}

      {!owner && me && (
        <div className="share-actions">
          <button type="button" className="btn btn-ghost btn-danger" disabled={busy} onClick={leave}>
            Leave trip
          </button>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
