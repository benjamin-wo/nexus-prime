import { type RefObject, useEffect, useRef } from "react";

import { reducedMotion } from "../../motion";
import { nativeHaptic } from "../../native";

/** Movement shorter than this is a tap, not a drag (the handle). */
const SLOP = 6;
/** Same, for a pull from the top of the scroller (as in usePullToRefresh). */
const TOUCH_SLOP = 8;
/** Letting go past this share of the panel's height closes it. */
const CLOSE_FRACTION = 0.25;
/** ...or a flick faster than this (px/ms, over the last VELOCITY_WINDOW_MS). */
const CLOSE_VELOCITY = 0.5;
const VELOCITY_WINDOW_MS = 80;
/** The backdrop dims to this opacity as the panel reaches the bottom. */
const BACKDROP_FLOOR = 0.3;
const SLIDE_MS = 200;
const FALLBACK_MS = 300;
const INTERACTIVE = "button, a, input, textarea, select";
/** A pull that starts on one of these is a text selection or a caret move, not a drag. */
const EDITABLE = "input, textarea, select, [contenteditable]";

type Options = {
  /** The grab area: dragging it moves the panel. A tap on a button, link or field inside it is left alone. */
  handle?: RefObject<HTMLElement | null>;
  /** What slides down. */
  panel: RefObject<HTMLElement | null>;
  /** Dimmed as the panel goes, when there is one. */
  backdrop?: RefObject<HTMLElement | null>;
  /** The scrolling body. A downward pull that starts in it while it is scrolled to the top drags the panel too. */
  scroller?: RefObject<HTMLElement | null>;
  onClose: () => void;
  enabled: boolean;
};

/**
 * Swipe down to close a bottom sheet or a full-screen panel. Two ways in, one state machine: dragging the
 * `handle` (pointer events), and pulling down from the top of the `scroller` (touch events, as in
 * usePullToRefresh: a non-passive touchmove takes the gesture once it is clearly downward). Only downward
 * movement counts: the panel follows the finger, and letting go past a quarter of its height (or in a quick
 * flick) slides it away and calls `onClose`; otherwise it springs back. Nothing re-renders while the finger
 * moves. With reduced motion there is no sliding: it closes or resets at once. Off when `enabled` is false.
 */
export function useDragToClose({ handle, panel, backdrop, scroller, onClose, enabled }: Options): void {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    const grip = handle?.current ?? null;
    const body = scroller?.current ?? null;
    if (!enabled || (!grip && !body)) return;
    let active: "pointer" | "touch" | null = null;
    let pointer: number | null = null;
    let startX = 0;
    let startY = 0;
    let dragging = false;
    let dy = 0;
    let samples: { t: number; y: number }[] = [];
    let timer: number | undefined;
    let ending: (() => void) | undefined;

    const clear = () => {
      window.clearTimeout(timer);
      ending?.();
      ending = undefined;
      const p = panel.current;
      const b = backdrop?.current;
      if (p) {
        p.style.transform = "";
        p.style.transition = "";
      }
      if (b) {
        b.style.opacity = "";
        b.style.transition = "";
      }
    };
    const draw = (y: number) => {
      const p = panel.current;
      if (!p) return;
      p.style.transition = "none";
      p.style.transform = `translateY(${y}px)`;
      const b = backdrop?.current;
      if (b) {
        const height = p.getBoundingClientRect().height || p.offsetHeight || 1;
        b.style.transition = "none";
        b.style.opacity = String(1 - (1 - BACKDROP_FLOOR) * Math.min(1, y / height));
      }
    };
    /** Runs `done` after the panel's transition ends (or a moment later, should it never fire). */
    const settle = (done: () => void) => {
      const p = panel.current;
      if (!p) return done();
      let finished = false;
      const finish = () => {
        if (finished) return;
        finished = true;
        window.clearTimeout(timer);
        p.removeEventListener("transitionend", onEnd);
        ending = undefined;
        done();
      };
      const onEnd = (e: Event) => {
        if (e.target === p) finish();
      };
      p.addEventListener("transitionend", onEnd);
      timer = window.setTimeout(finish, FALLBACK_MS);
      ending = () => p.removeEventListener("transitionend", onEnd);
    };
    const slide = (transform: string, opacity: string) => {
      const p = panel.current;
      if (p) {
        p.style.transition = `transform ${SLIDE_MS}ms ease-out`;
        p.style.transform = transform;
      }
      const b = backdrop?.current;
      if (b) {
        b.style.transition = `opacity ${SLIDE_MS}ms ease-out`;
        b.style.opacity = opacity;
      }
    };
    const velocity = () => {
      const last = samples[samples.length - 1];
      if (!last) return 0;
      const first = samples.find((s) => last.t - s.t <= VELOCITY_WINDOW_MS) ?? last;
      return last.t > first.t ? (last.y - first.y) / (last.t - first.t) : 0;
    };

    // The shared state machine: begin a gesture, follow it, release it.
    const begin = (kind: "pointer" | "touch", x: number, y: number) => {
      clear();
      active = kind;
      startX = x;
      startY = y;
      dragging = false;
      dy = 0;
      samples = [{ t: performance.now(), y: 0 }];
    };
    const follow = (y: number) => {
      dy = Math.max(0, y - startY);
      const now = performance.now();
      samples.push({ t: now, y: dy });
      samples = samples.filter((s) => now - s.t <= VELOCITY_WINDOW_MS * 4);
      draw(dy);
    };
    const release = (cancelled: boolean) => {
      if (active === null) return;
      active = null;
      pointer = null;
      if (!dragging) return;
      dragging = false;
      const p = panel.current;
      const height = p ? p.getBoundingClientRect().height || p.offsetHeight : 0;
      const shut = !cancelled && (dy > height * CLOSE_FRACTION || velocity() > CLOSE_VELOCITY);
      if (reducedMotion()) {
        if (shut) {
          nativeHaptic("light");
          close.current();
        } else clear();
        return;
      }
      if (shut) {
        slide("translateY(100%)", String(BACKDROP_FLOOR));
        settle(() => {
          nativeHaptic("light");
          close.current();
        });
      } else {
        slide("translateY(0)", "1");
        settle(clear);
      }
    };

    // Pointer path: the handle.
    const onDown = (e: PointerEvent) => {
      if (active !== null || (e.pointerType === "mouse" && e.button !== 0)) return;
      if (e.target instanceof Element && e.target.closest(INTERACTIVE)) return;
      pointer = e.pointerId;
      begin("pointer", e.clientX, e.clientY);
    };
    const onMove = (e: PointerEvent) => {
      if (active !== "pointer" || e.pointerId !== pointer) return;
      const x = e.clientX - startX;
      const y = e.clientY - startY;
      if (!dragging) {
        if (Math.abs(y) <= SLOP && Math.abs(x) <= SLOP) return;
        // Up, or more sideways than down, is not ours.
        if (y <= 0 || Math.abs(x) > Math.abs(y)) {
          active = null;
          pointer = null;
          return;
        }
        if (y <= SLOP) return;
        dragging = true;
        try {
          grip?.setPointerCapture?.(e.pointerId);
        } catch {
          // A pointer that has already gone is no reason to stop.
        }
      }
      if (e.cancelable) e.preventDefault();
      follow(e.clientY);
    };
    const onUp = (e: PointerEvent) => {
      if (active === "pointer" && e.pointerId === pointer) release(false);
    };
    const onCancel = (e: PointerEvent) => {
      if (active === "pointer" && e.pointerId === pointer) release(true);
    };

    // Touch path: a pull down from the top of the scroller.
    const onTouchStart = (e: TouchEvent) => {
      if (active !== null) return;
      if (e.touches.length !== 1 || !body || body.scrollTop > 0) return;
      if (e.target instanceof Element && e.target.closest(EDITABLE)) return;
      begin("touch", e.touches[0].clientX, e.touches[0].clientY);
    };
    const onTouchMove = (e: TouchEvent) => {
      if (active !== "touch" || !body) return;
      if (e.touches.length !== 1 || (!dragging && body.scrollTop > 0)) {
        if (dragging) release(true);
        else active = null;
        return;
      }
      const y = e.touches[0].clientY - startY;
      const x = e.touches[0].clientX - startX;
      if (!dragging) {
        // Up, or more sideways than down, is the content's own scroll or swipe.
        if (y < 0 || (Math.abs(x) > Math.abs(y) && Math.abs(x) > TOUCH_SLOP)) {
          active = null;
          return;
        }
        if (y < TOUCH_SLOP) return;
        dragging = true;
      }
      // Pulling down at the top would otherwise bounce the content or the page: take the gesture.
      if (e.cancelable) e.preventDefault();
      follow(e.touches[0].clientY);
    };
    const onTouchEnd = () => {
      if (active === "touch") release(false);
    };
    const onTouchCancel = () => {
      if (active === "touch") release(true);
    };

    grip?.addEventListener("pointerdown", onDown);
    grip?.addEventListener("pointermove", onMove);
    grip?.addEventListener("pointerup", onUp);
    grip?.addEventListener("pointercancel", onCancel);
    body?.addEventListener("touchstart", onTouchStart, { passive: true });
    body?.addEventListener("touchmove", onTouchMove, { passive: false });
    body?.addEventListener("touchend", onTouchEnd);
    body?.addEventListener("touchcancel", onTouchCancel);
    return () => {
      grip?.removeEventListener("pointerdown", onDown);
      grip?.removeEventListener("pointermove", onMove);
      grip?.removeEventListener("pointerup", onUp);
      grip?.removeEventListener("pointercancel", onCancel);
      body?.removeEventListener("touchstart", onTouchStart);
      body?.removeEventListener("touchmove", onTouchMove);
      body?.removeEventListener("touchend", onTouchEnd);
      body?.removeEventListener("touchcancel", onTouchCancel);
      clear();
    };
  }, [handle, panel, backdrop, scroller, enabled]);
}
