import { useQuery } from "@tanstack/react-query";
import { useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Me, type NotificationEntry } from "../api";
import { BackLink } from "../components/BackLink";
import { Block } from "../components/Block";
import { Icon } from "../components/Icon";
import { formatClock, isoDay } from "../format";

/** How many lines of a message show before "Show more". */
const LINES = 2;

/** The day before or after a YYYY-MM-DD, by the calendar (no clock, so no daylight-saving slip). */
function shiftDay(day: string, by: number): string {
  const date = new Date(`${day}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + by);
  return date.toISOString().slice(0, 10);
}

/** A day's heading: Today, Yesterday, then "Tue 20 Oct" (with the year once it isn't this one). */
function dayLabel(day: string, today: string): string {
  if (day === today) return "Today";
  if (day === shiftDay(today, -1)) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: day.slice(0, 4) === today.slice(0, 4) ? undefined : "numeric",
    timeZone: "UTC",
  }).format(new Date(`${day}T00:00:00Z`));
}

export type NotificationDay = { day: string; label: string; entries: NotificationEntry[] };

/** The messages grouped by the day they were made in the user's timezone, newest day first and
 * newest message first inside it. */
export function groupByDay(entries: NotificationEntry[], timeZone: string, now: Date = new Date()): NotificationDay[] {
  const today = isoDay(now.toISOString(), timeZone);
  const newest = [...entries].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  const days: NotificationDay[] = [];
  for (const entry of newest) {
    const day = isoDay(entry.created_at, timeZone);
    const last = days[days.length - 1];
    if (last && last.day === day) last.entries.push(entry);
    else days.push({ day, label: dayLabel(day, today), entries: [entry] });
  }
  return days;
}

/** What became of a message, in a few words. A held one says when it goes (the time, with the
 * day when that isn't today). */
export function statusLabel(entry: NotificationEntry, timeZone: string, now: Date = new Date()): string {
  switch (entry.status) {
    case "sent":
      return "Sent";
    case "digested":
      return "In a digest";
    case "dropped":
      return "Not sent — Telegram not linked";
    case "held": {
      if (!entry.held_until) return "Held for the next digest";
      const clock = formatClock(entry.held_until, timeZone);
      const today = isoDay(now.toISOString(), timeZone);
      const day = isoDay(entry.held_until, timeZone);
      if (day === today) return `Held until ${clock}`;
      if (day === shiftDay(today, 1)) return `Held until tomorrow ${clock}`;
      return `Held until ${dayLabel(day, today)} ${clock}`;
    }
  }
}

/** The message's words, two lines of them (the CSS clamp adds the one "…") until "Show more" (if it is longer). A message with a
 * link opens it from its text; the button is separate so both work. */
function MessageText({ entry }: { entry: NotificationEntry }) {
  const [open, setOpen] = useState(false);
  // Lines the text itself breaks count even before the browser has measured anything.
  const [long, setLong] = useState(() => entry.text.split("\n").length > LINES);
  const text = useRef<HTMLParagraphElement>(null);
  const id = `note-${entry.id}`;

  useLayoutEffect(() => {
    const el = text.current;
    if (!el || open) return;
    const measure = () => setLong(entry.text.split("\n").length > LINES || el.scrollHeight > el.clientHeight + 1);
    measure();
    const watcher = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    watcher?.observe(el);
    // The web font arrives after the first paint and changes where lines break.
    void document.fonts?.ready.then(measure);
    return () => watcher?.disconnect();
  }, [entry.text, open]);

  // Folded, the text runs on as one paragraph: a line break kept there would end a line on its full
  // stop and the clamp would add its "…" right after it ("session.…"). Opened, the breaks come back.
  const shown = open ? entry.text : entry.text.replace(/\s*\n\s*/g, " ");
  const words = entry.link?.startsWith("/") ? <Link to={entry.link}>{shown}</Link> : shown;
  return (
    <>
      <p id={id} ref={text} className={`note-text${open ? " open" : ""}`}>
        {words}
      </p>
      {long && (
        <button
          type="button"
          className="btn btn-ghost btn-small note-toggle"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
        >
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </>
  );
}

function NotificationRow({ entry, timeZone }: { entry: NotificationEntry; timeZone: string }) {
  const urgent = entry.level === "urgent";
  return (
    <li className={`row note${urgent ? " urgent" : ""}`}>
      <span className="row-icon" aria-hidden="true">
        <Icon name={urgent ? "alert" : "bell"} size={18} />
      </span>
      <div className="row-main">
        <MessageText entry={entry} />
        <div className="note-meta">
          <span className="caption">{formatClock(entry.created_at, timeZone)}</span>
          {urgent && <span className="caption note-urgent">Urgent</span>}
          <span className={`badge note-status note-${entry.status}`}>{statusLabel(entry, timeZone)}</span>
        </div>
      </div>
    </li>
  );
}

/** What Nexus sent (or meant to send) the user on Telegram in the last 30 days, a day at a time. */
export function NotificationsPage({ me }: { me: Me }) {
  const history = useQuery({
    queryKey: ["notification-history"],
    queryFn: () => api<NotificationEntry[]>("/notifications/history"),
  });
  const timeZone = me.user.timezone;
  const days = history.data ? groupByDay(history.data, timeZone) : [];
  return (
    <>
      <div className="page-head">
        <div>
          <BackLink to="/settings">Back to Settings</BackLink>
          <h1>Notifications</h1>
          <p className="muted">
            Urgent ones always come. The rest respect your quiet hours and daily limit, and what's left is gathered into
            one message.
          </p>
        </div>
      </div>
      {history.isLoading && <p className="state">Loading…</p>}
      {history.isError && <p className="state error-text">Couldn't load your notifications.</p>}
      {history.data && days.length === 0 && <p className="state">Nothing sent in the last 30 days.</p>}
      {days.map((d) => (
        <Block key={d.day} id={`notes-${d.day}`} title={d.label}>
          <ul className="rows">
            {d.entries.map((entry) => (
              <NotificationRow key={entry.id} entry={entry} timeZone={timeZone} />
            ))}
          </ul>
        </Block>
      ))}
    </>
  );
}

/** On the Settings page, under Notifications: the way in to the list of what was sent. */
export function NotificationsCard() {
  return (
    <section className="card" aria-labelledby="notifications-card">
      <div className="card-head">
        <h2 id="notifications-card">Notifications</h2>
        <Link className="btn" to="/settings/notifications">
          Open
        </Link>
      </div>
      <p className="caption">What Nexus sent you on Telegram in the last 30 days, and what is waiting.</p>
    </section>
  );
}
