import { type RefObject, useEffect, useRef, useSyncExternalStore } from "react";

import { reducedMotion } from "./motion";
import { nativeHaptic } from "./native";

/** Movement shorter than this is a tap, not a drag. */
const SLOP = 6;
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

/** Whether a media query matches now, kept current. False where `matchMedia` is missing. */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (notify) => {
      const list = typeof window !== "undefined" ? window.matchMedia?.(query) : undefined;
      list?.addEventListener?.("change", notify);
      return () => list?.removeEventListener?.("change", notify);
    },
    () => typeof window !== "undefined" && window.matchMedia?.(query).matches === true,
    () => false,
  );
}

type Options = {
  /** The grab area: dragging it moves the panel. A tap on a button, link or field inside it is left alone. */
  handle: RefObject<HTMLElement | null>;
  /** What slides down. */
  panel: RefObject<HTMLElement | null>;
  /** Dimmed as the panel goes, when there is one. */
  backdrop?: RefObject<HTMLElement | null>;
  onClose: () => void;
  enabled: boolean;
};

/**
 * Swipe down on a handle to close a bottom sheet or a full-screen panel. Only downward movement counts: the
 * panel follows the finger, and letting go past a quarter of its height (or in a quick flick) slides it away and
 * calls `onClose`; otherwise it springs back. Nothing re-renders while the finger moves. With reduced motion
 * there is no sliding: it closes or resets at once. Off when `enabled` is false.
 */
export function useDragToClose({ handle, panel, backdrop, onClose, enabled }: Options): void {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    const grip = handle.current;
    if (!grip || !enabled) return;
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

    const onDown = (e: PointerEvent) => {
      if (pointer !== null || (e.pointerType === "mouse" && e.button !== 0)) return;
      if (e.target instanceof Element && e.target.closest(INTERACTIVE)) return;
      clear();
      pointer = e.pointerId;
      startX = e.clientX;
      startY = e.clientY;
      dragging = false;
      dy = 0;
      samples = [{ t: performance.now(), y: 0 }];
    };
    const onMove = (e: PointerEvent) => {
      if (e.pointerId !== pointer) return;
      const x = e.clientX - startX;
      const y = e.clientY - startY;
      if (!dragging) {
        if (Math.abs(y) <= SLOP && Math.abs(x) <= SLOP) return;
        // Up, or more sideways than down, is not ours.
        if (y <= 0 || Math.abs(x) > Math.abs(y)) {
          pointer = null;
          return;
        }
        if (y <= SLOP) return;
        dragging = true;
        try {
          grip.setPointerCapture?.(e.pointerId);
        } catch {
          // A pointer that has already gone is no reason to stop.
        }
      }
      if (e.cancelable) e.preventDefault();
      dy = Math.max(0, y);
      const now = performance.now();
      samples.push({ t: now, y: dy });
      samples = samples.filter((s) => now - s.t <= VELOCITY_WINDOW_MS * 4);
      draw(dy);
    };
    const finishDrag = (cancelled: boolean) => {
      if (pointer === null) return;
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
    const onUp = (e: PointerEvent) => {
      if (e.pointerId === pointer) finishDrag(false);
    };
    const onCancel = (e: PointerEvent) => {
      if (e.pointerId === pointer) finishDrag(true);
    };
    grip.addEventListener("pointerdown", onDown);
    grip.addEventListener("pointermove", onMove);
    grip.addEventListener("pointerup", onUp);
    grip.addEventListener("pointercancel", onCancel);
    return () => {
      grip.removeEventListener("pointerdown", onDown);
      grip.removeEventListener("pointermove", onMove);
      grip.removeEventListener("pointerup", onUp);
      grip.removeEventListener("pointercancel", onCancel);
      clear();
    };
  }, [handle, panel, backdrop, enabled]);
}
