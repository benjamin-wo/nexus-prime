import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type RefObject, useEffect, useState } from "react";

import { api, type Booking, type Trip, type TripDetail } from "../api";
import { ConfirmBox } from "../components/ConfirmBox";
import { Icon } from "../components/Icon";
import { Sheet } from "../components/Sheet";
import { day } from "./TripBits";
import { type Go, nextUp } from "./TripStage";
import { GETTING_AROUND, MapAppPicker } from "./TripMap";
import { Button, Section } from "../components/ui";
import { BookingRow } from "./TripItinerary";

/** Public transport or a hire car: how longer hops go, unless one was picked. Reached from
 * the trip's menu (``TripMenu``), with the app directions open in. */
function GettingAroundPicker({ trip, onChange }: { trip: Trip; onChange: () => void }) {
  const [busy, setBusy] = useState(false);
  async function choose(by: string) {
    setBusy(true);
    await api(`/travel/trips/${trip.id}/getting-around`, { method: "PUT", body: { by } }).catch(() => undefined);
    setBusy(false);
    onChange();
  }
  return (
    <label className="caption map-app">
      Getting around{" "}
      <select value={trip.getting_around ?? "transit"} disabled={busy} onChange={(e) => void choose(e.target.value)}>
        <option value="transit">{GETTING_AROUND.transit}</option>
        <option value="car">{GETTING_AROUND.car}</option>
      </select>
    </label>
  );
}

/** Bookings from email that aren't on a trip yet: put each on one, or forget it. */
export function LooseBookings({ trips }: { trips: Trip[] }) {
  const client = useQueryClient();
  const loose = useQuery({ queryKey: ["loose-bookings"], queryFn: () => api<Booking[]>("/travel/bookings") });
  const ahead = trips.filter((t) => t.status !== "finished");
  if (!loose.data?.length) return null;

  async function move(booking: Booking, tripId: string) {
    if (tripId === "forget") await api(`/travel/bookings/${booking.id}`, { method: "DELETE" });
    else await api(`/travel/bookings/${booking.id}/trip`, { method: "PUT", body: { trip_id: tripId } });
    void client.invalidateQueries({ queryKey: ["loose-bookings"] });
    void client.invalidateQueries({ queryKey: ["home"] });
  }

  return (
    <Section id="loose-bookings" title="Bookings not on a trip" className="quiet-list">
      <ul className="quiet-rows">
        {loose.data.map((b) => (
          <BookingRow key={b.id} booking={b}>
            <select className="input quiet-select" aria-label={`Trip for ${b.title}`} value="" onChange={(e) => void move(b, e.target.value)}>
              <option value="" disabled>
                Put on a trip…
              </option>
              {ahead.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.destination} ({day(t.start)})
                </option>
              ))}
              <option value="forget">Not for a trip: forget it</option>
            </select>
          </BookingRow>
        ))}
      </ul>
    </Section>
  );
}

/** How longer hops go and which app directions open in: a small sheet off the trip's menu,
 * for the owner. Out in the body, since the cover's light text colours would carry into it. */
function WaysSheet({ trip, onChange, onClose }: { trip: Trip; onChange: () => void; onClose: () => void }) {
  return (
    <Sheet title="Getting around and directions" titleId="ways-sheet-title" className="ways-sheet" onClose={onClose}>
      <div className="trip-ways">
        <GettingAroundPicker trip={trip} onChange={onChange} />
        <MapAppPicker />
      </div>
    </Sheet>
  );
}

/** A trip's menu: its cover photo, changing it and deleting it, and (where the trip has maps
 * and routes) how it gets around. */
function TripMenu({ trip, onEdit, onDelete, onChange }: { trip: Trip; onEdit: () => void; onDelete: () => void | Promise<void>; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  // Deleting asks inside the menu (never the browser's dialog), and says so if it fails.
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Only a trip with places and routes has anything to pick; the page already holds that.
  const detail = useQueryClient().getQueryData<TripDetail>(["trip", trip.id]);
  const ways = Boolean(detail?.routes && detail.places);
  const [waysOpen, setWaysOpen] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  async function photo(choice: "next" | "off" | "on") {
    setNote(null);
    try {
      await api<Trip>(`/travel/trips/${trip.id}/photo`, { method: "POST", body: { choice } });
      setOpen(false);
      onChange();
    } catch (e) {
      setNote(e instanceof Error ? e.message : "Couldn't change the photo");
    }
  }
  const item = (label: string, run: () => void, danger = false) => (
    <Button
      role="menuitem"
      variant={danger ? "danger" : "text"}
      onClick={() => {
        run();
      }}
    >
      {label}
    </Button>
  );
  return (
    <div className="trip-menu">
      <Button className="trip-bar-button trip-bar-button-icon" aria-label="Trip options" aria-haspopup="menu" aria-expanded={open} onClick={() => { setOpen(!open); setConfirming(false); }}>
        ⋯
      </Button>
      {open && confirming && (
        <div className="trip-menu-list">
          <ConfirmBox
            label={`Delete the trip to ${trip.destination}`}
            question={`Delete the trip to ${trip.destination}? Its expenses stay in the ledger.`}
            confirm="Delete trip"
            busy={deleting}
            onConfirm={async () => {
              setDeleting(true);
              setNote(null);
              try {
                await onDelete();
              } catch (e) {
                setNote(e instanceof Error ? e.message : "Couldn't delete the trip");
                setConfirming(false);
                setDeleting(false);
              }
            }}
            onKeep={() => setConfirming(false)}
          />
        </div>
      )}
      {open && !confirming && (
        <div className="trip-menu-list" role="menu" aria-label="Trip options">
          {item("Edit trip", () => {
            setOpen(false);
            onEdit();
          })}
          {ways &&
            item("Getting around and directions", () => {
              setOpen(false);
              setWaysOpen(true);
            })}
          {trip.photo_off ? item("Show a photo", () => void photo("on")) : item("Another photo", () => void photo("next"))}
          {!trip.photo_off && item("No photo", () => void photo("off"))}
          <hr className="trip-menu-sep" />
          {item("Delete trip", () => setConfirming(true), true)}
          {note && (
            <p className="caption" role="status">
              {note}
            </p>
          )}
        </div>
      )}
      {waysOpen && <WaysSheet trip={trip} onChange={onChange} onClose={() => setWaysOpen(false)} />}
    </div>
  );
}


/** The one thing to do next, as one quiet line in the trip's header on Plan. */
export function NextUpStrip({ detail, onGo }: { detail: TripDetail; onGo: (go: Go) => void }) {
  // The ideas that could fill a free day: everything not yet on a day.
  const ideas = detail.bookings.filter((b) => b.kind === "activity" && !b.scheduled).length;
  const next = nextUp(detail, () => ideas);
  if (!next) return null;
  return (
    <section className="next-up" aria-label="Next up">
      <p className="next-up-text">{next.text}</p>
      <Button variant="text" className="next-up-action" onClick={() => onGo(next.go)} aria-label={`${next.action}: ${next.text}`}>
        {next.action}
      </Button>
    </section>
  );
}

/** The trip's photo for the cover and the slim bar's thumbnail: the photo itself, with no fade over it. */

/** The header's actions, on the cover and in the slim bar: Share (People for a member), the
 * one Add on a wide screen, and the owner's ⋯ menu. */
export function TripActions({ trip, member, editing, add, onShare, onEdit, onDelete, onChange }: {
  trip: Trip;
  member: boolean;
  editing: boolean;
  add: { label: string; run: () => void } | null;
  onShare: () => void;
  onEdit: () => void;
  onDelete: () => void | Promise<void>;
  onChange: () => void;
}) {
  return (
    <div className="trip-actions">
      {!editing && (
        <Button className="trip-bar-button" onClick={onShare} aria-label={member ? "People on this trip" : "Share the plan"}>
          {member ? "People" : "Share"}
        </Button>
      )}
      {add && (
        <Button variant="primary" className="trip-add-desktop" onClick={add.run} aria-label={add.label}>
          <Icon name="plus" size={16} />
          Add
        </Button>
      )}
      {/* Editing the trip, its photo and deleting it are the owner's. */}
      {!editing && !member && <TripMenu trip={trip} onEdit={onEdit} onDelete={onDelete} onChange={onChange} />}
    </div>
  );
}

/** The height of the slim bar: the cover counts as gone once its photo is behind it. */
const SLIM_BAR = 56;

/** Whether the cover's photo has scrolled up behind the slim bar. Without an observer it never has. */
export function useCoverGone(photo: RefObject<HTMLElement | null>, on: boolean): boolean {
  const [gone, setGone] = useState(false);
  useEffect(() => {
    const el = photo.current;
    if (!on || !el || typeof IntersectionObserver === "undefined") {
      setGone(false);
      return;
    }
    const seen = new IntersectionObserver(([entry]) => setGone(!entry.isIntersecting), {
      root: el.closest(".main-viewport"),
      rootMargin: `-${SLIM_BAR}px 0px 0px 0px`,
    });
    seen.observe(el);
    return () => {
      seen.disconnect();
      setGone(false);
    };
  }, [photo, on]);
  return gone;
}
