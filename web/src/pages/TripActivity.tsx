import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, type TripActivity, tripActivityPath } from "../api";
import { Sheet } from "../components/Sheet";
import { formatShortDate } from "../format";

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** How long ago, in words: "just now", "5 min ago", "2 hours ago", "3 days ago", else the date. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const gone = Math.max(0, now - then);
  if (gone < MINUTE) return "just now";
  if (gone < HOUR) return `${Math.floor(gone / MINUTE)} min ago`;
  if (gone < DAY) {
    const hours = Math.floor(gone / HOUR);
    return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  }
  if (gone < 7 * DAY) {
    const days = Math.floor(gone / DAY);
    return `${days} ${days === 1 ? "day" : "days"} ago`;
  }
  return formatShortDate(iso);
}

/** "Alex added Dinner at Sushi Ten": who did it and what, as the server words it. */
export const activityText = (item: TripActivity): string => `${item.actor} ${item.summary}`;

/** The newest change from the last 7 days, or null when there is none (the list is newest first). */
export function recentActivity(items: TripActivity[], now: number = Date.now()): TripActivity | null {
  const [latest] = items;
  if (!latest) return null;
  const at = Date.parse(latest.at);
  return !Number.isNaN(at) && now - at <= 7 * DAY ? latest : null;
}

/** What changed in a shared trip's plan, newest first (the latest 20). Reloaded when the window
 * comes back into focus, so a change someone else made turns up without a refresh. */
export function useActivity(tripId: string, enabled: boolean) {
  return useQuery({
    queryKey: ["trip-activity", tripId],
    queryFn: () => api<TripActivity[]>(tripActivityPath(tripId)),
    enabled,
    refetchOnWindowFocus: true,
  });
}

/** One quiet line under Next up on a shared trip: the latest change. Tapping it opens the list.
 * Nothing when the trip isn't shared or nothing changed in the last week. */
export function ActivityLine({ tripId, shared }: { tripId: string; shared: boolean }) {
  const activity = useActivity(tripId, shared);
  const [open, setOpen] = useState(false);
  const items = activity.data ?? [];
  const latest = shared ? recentActivity(items) : null;
  if (!latest) return null;
  return (
    <>
      <button type="button" className="activity-line" onClick={() => setOpen(true)} aria-label={`${activityText(latest)}, ${timeAgo(latest.at)}. Show recent changes`}>
        <span className="wrap">{activityText(latest)}</span>
        <span className="activity-when"> · {timeAgo(latest.at)}</span>
      </button>
      {open && <ActivitySheet items={items} onClose={() => setOpen(false)} />}
    </>
  );
}

/** The last 20 changes to the plan, newest first. */
export function ActivitySheet({ items, onClose }: { items: TripActivity[]; onClose: () => void }) {
  return (
    <Sheet title="Recent changes" titleId="activity-sheet-title" onClose={onClose}>
      {items.length === 0 ? (
        <p className="caption">Nothing has changed yet.</p>
      ) : (
        <ul className="activity-list">
          {items.slice(0, 20).map((item, n) => (
            <li key={`${item.at}-${n}`}>
              <span className="wrap">{activityText(item)}</span>
              <span className="caption">{timeAgo(item.at)}</span>
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  );
}
