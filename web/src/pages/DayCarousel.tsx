import { type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useDayPill } from "./TripArrange";

const HOLD_TO_OPEN_MS = 600;

const smooth = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

/** A day's pill: opens the day, and takes a dragged plan (held over it, it opens the
 * day so the plan can be put in its place there). */
function DayPill({ iso, label, current, onOpen }: { iso: string; label: string; current: boolean; onOpen: () => void }) {
  const pill = useDayPill(`day:${iso}`);
  // The page redraws all through a drag: the timer only restarts when the hold does.
  const open = useRef(onOpen);
  open.current = onOpen;
  useEffect(() => {
    if (!pill.over || current) return;
    const timer = window.setTimeout(() => open.current(), HOLD_TO_OPEN_MS);
    return () => window.clearTimeout(timer);
  }, [pill.over, current]);
  return (
    <button
      data-pill={pill.pill}
      type="button"
      className={`day-pill${pill.over ? " drop-over" : ""}`}
      aria-current={current ? "true" : undefined}
      onClick={onOpen}
    >
      {label}
    </button>
  );
}

/** The itinerary a day at a time: swipe between days, or pick one from the pills.
 * Every day stays on the page (so travel times, links and moves work as before); only
 * the one in view sets the height. */
export function DayCarousel({
  days,
  start,
  follow,
  pill,
  name,
  children,
}: {
  days: string[];
  /** The day to open on. */
  start: string;
  /** A day to bring into view, like where a plan carried by keyboard would land. */
  follow?: string | null;
  pill: (iso: string) => string;
  /** How the day is read out: "Day 2 · Wed, 21 Oct". */
  name: (iso: string) => string;
  /** A day's content; ``near`` for the day in view and those either side. */
  children: (iso: string, near: boolean) => ReactNode;
}) {
  const track = useRef<HTMLDivElement>(null);
  const strip = useRef<HTMLElement>(null);
  const [index, setIndex] = useState(() => Math.max(0, days.indexOf(start)));
  const [height, setHeight] = useState<number | undefined>(undefined);
  const shown = Math.min(index, Math.max(0, days.length - 1));

  const go = useCallback(
    (i: number, behavior: ScrollBehavior = smooth()) => {
      const el = track.current;
      const next = Math.max(0, Math.min(days.length - 1, i));
      setIndex(next);
      if (el) el.scrollTo({ left: next * el.clientWidth, behavior });
    },
    [days.length],
  );

  // Open on the start day, without a slide across.
  useLayoutEffect(() => {
    go(Math.max(0, days.indexOf(start)), "auto");
    // Only once: later the user's swipes decide.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!follow) return;
    const i = days.indexOf(follow);
    if (i >= 0 && i !== shown) go(i);
  }, [follow, days, shown, go]);

  // A swipe (or focus moving into another day) scrolls the track: follow it.
  function onScroll() {
    const el = track.current;
    if (!el || el.clientWidth === 0) return;
    const i = Math.round(el.scrollLeft / el.clientWidth);
    if (i !== index) setIndex(i);
  }

  // The track is as tall as the day in view, not the longest day.
  useEffect(() => {
    const el = track.current?.children[shown] as HTMLElement | undefined;
    if (!el) return;
    const fit = () => setHeight(el.offsetHeight);
    fit();
    if (typeof ResizeObserver === "undefined") return;
    const watch = new ResizeObserver(fit);
    watch.observe(el);
    return () => watch.disconnect();
  }, [shown, days.length]);

  // Keep the day's pill in view in the strip, moving it only when it's out of view
  // (so a pill a plan is held over stays under it).
  useEffect(() => {
    const bar = strip.current;
    const chosen = bar?.children[shown] as HTMLElement | undefined;
    if (!bar || !chosen) return;
    const start = chosen.offsetLeft - bar.offsetLeft;
    if (start >= bar.scrollLeft && start + chosen.offsetWidth <= bar.scrollLeft + bar.clientWidth) return;
    const left = start - (bar.clientWidth - chosen.offsetWidth) / 2;
    bar.scrollTo?.({ left: Math.max(0, left), behavior: smooth() });
  }, [shown]);

  const iso = days[shown];
  return (
    <div className="day-carousel" role="region" aria-roledescription="carousel" aria-label="Days of the trip">
      <nav ref={strip} className="day-strip" aria-label="Days">
        {days.map((d, i) => (
          <DayPill key={d} iso={d} label={pill(d)} current={i === shown} onOpen={() => go(i)} />
        ))}
      </nav>
      {days.length > 1 && (
        <div className="day-controls">
          <button type="button" className="btn btn-ghost btn-small" onClick={() => go(shown - 1)} disabled={shown === 0} aria-label="Previous day">
            ‹
          </button>
          <span className="caption" aria-live="polite">
            {iso && <span className="sr-only">{name(iso)}, </span>}
            {shown + 1} of {days.length}
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-small"
            onClick={() => go(shown + 1)}
            disabled={shown === days.length - 1}
            aria-label="Next day"
          >
            ›
          </button>
        </div>
      )}
      <div ref={track} className="day-track" onScroll={onScroll} style={height ? { height } : undefined}>
        {days.map((d, i) => (
          <div
            key={d}
            className="day-slide"
            role="group"
            aria-roledescription="slide"
            aria-label={`${name(d)}, ${i + 1} of ${days.length}`}
          >
            {children(d, Math.abs(i - shown) <= 1)}
          </div>
        ))}
      </div>
    </div>
  );
}
