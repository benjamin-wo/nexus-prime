import { type ReactNode, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { useDayPill } from "./TripArrange";

const HOLD_TO_OPEN_MS = 600;

const smooth = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";

/** A day's pill: opens the day, and takes a dragged plan (held over it, it opens the
 * day so the plan can be put in its place there). */
function DayPill({ iso, label, current, mark, title, onOpen }: { iso: string; label: string; current: boolean; mark?: ReactNode; title?: string; onOpen: () => void }) {
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
      title={title}
      onClick={onOpen}
    >
      {mark}
      {label}
    </button>
  );
}

/** One day, as tall as its content: the carousel's track takes the height of the day in
 * view (``measure`` is handed this slide's element while it's the one in view). */
function DaySlide({ label, current, measure, children }: { label: string; current: boolean; measure: (el: HTMLDivElement | null) => void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (current) measure(box.current);
  }, [current, measure]);
  return (
    <div ref={box} className="day-slide" role="group" aria-roledescription="slide" aria-label={label}>
      {children}
    </div>
  );
}

/** The itinerary a day at a time: swipe between days, or pick one from the pills.
 * Every day stays on the page (so travel times, links and moves work as before), and
 * the track is as tall as the day in view, growing and shrinking as the day does. The
 * day in view is the page's (``value``): a swipe or a pill asks for another with
 * ``onPick``. */
export function DayCarousel({
  days,
  value,
  onPick,
  follow,
  pill,
  mark,
  markTitle,
  name,
  children,
}: {
  days: string[];
  /** The day in view. */
  value: string;
  onPick: (iso: string) => void;
  /** A day to bring into view, like where a plan carried by keyboard would land. */
  follow?: string | null;
  pill: (iso: string) => string;
  /** Something small before a pill's text (a stop's dot, a travel icon): decoration, so
   * the pill is still named by its day; ``markTitle`` says what it means on hover. */
  mark?: (iso: string) => ReactNode;
  markTitle?: (iso: string) => string | undefined;
  /** How the day is read out: "Day 2 · Wed, 21 Oct". */
  name: (iso: string) => string;
  /** A day's content; ``near`` for the day in view and those either side. */
  children: (iso: string, near: boolean) => ReactNode;
}) {
  const track = useRef<HTMLDivElement>(null);
  const strip = useRef<HTMLElement>(null);
  const shown = Math.max(0, days.indexOf(value));
  // The slide a scroll we started is heading for: its in-between positions aren't swipes.
  const aim = useRef<{ index: number; timer: number } | null>(null);
  const opened = useRef(false);
  // The track's height: that of the day in view, found by watching its slide.
  const [height, setHeight] = useState<number | null>(null);
  const watched = useRef<{ el: HTMLDivElement; watch: ResizeObserver | null } | null>(null);
  const measure = useCallback((el: HTMLDivElement | null) => {
    watched.current?.watch?.disconnect();
    watched.current = null;
    if (!el) return;
    const read = () => {
      const h = Math.ceil(el.getBoundingClientRect().height);
      setHeight(h > 0 ? h : null);
    };
    read();
    // Plans added, opened or taken away change how much there is.
    const watch = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(read);
    watch?.observe(el);
    watched.current = { el, watch };
  }, []);
  useEffect(() => () => watched.current?.watch?.disconnect(), []);

  const scrollTo = useCallback((i: number, behavior: ScrollBehavior) => {
    const el = track.current;
    if (!el) return;
    if (aim.current) window.clearTimeout(aim.current.timer);
    if (behavior === "auto") {
      aim.current = null;
    } else {
      aim.current = { index: i, timer: window.setTimeout(() => (aim.current = null), 800) };
    }
    el.scrollTo({ left: i * el.clientWidth, behavior });
  }, []);

  const go = useCallback(
    (i: number) => {
      const next = days[Math.max(0, Math.min(days.length - 1, i))];
      if (next && next !== value) onPick(next);
    },
    [days, value, onPick],
  );

  // Open on the day without a slide across; later changes of day (a pill, the map, a
  // button elsewhere on the page) slide to it.
  useLayoutEffect(() => {
    const el = track.current;
    if (!el || el.clientWidth === 0) return;
    if (opened.current && Math.round(el.scrollLeft / el.clientWidth) === shown) return;
    scrollTo(shown, opened.current ? smooth() : "auto");
    opened.current = true;
  }, [shown, scrollTo]);

  useEffect(() => {
    if (follow && follow !== value && days.includes(follow)) onPick(follow);
  }, [follow, value, days, onPick]);

  // A swipe (or focus moving into another day) scrolls the track: follow it.
  function onScroll() {
    const el = track.current;
    if (!el || el.clientWidth === 0) return;
    if (aim.current) {
      if (Math.abs(el.scrollLeft - aim.current.index * el.clientWidth) > 2) return;
      window.clearTimeout(aim.current.timer);
      aim.current = null;
    }
    const i = Math.round(el.scrollLeft / el.clientWidth);
    if (days[i] && days[i] !== value) onPick(days[i]);
  }

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
          <DayPill key={d} iso={d} label={pill(d)} mark={mark?.(d)} title={markTitle?.(d)} current={i === shown} onOpen={() => go(i)} />
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
      <div ref={track} className="day-track" style={height === null ? undefined : { height }} onScroll={onScroll}>
        {days.map((d, i) => (
          <DaySlide key={d} label={`${name(d)}, ${i + 1} of ${days.length}`} current={i === shown} measure={measure}>
            {children(d, Math.abs(i - shown) <= 1)}
          </DaySlide>
        ))}
      </div>
    </div>
  );
}
