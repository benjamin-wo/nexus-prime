import { type MouseEvent, type PointerEvent, useEffect, useMemo, useRef } from "react";

/** How long a finger must stay down, and how far it may wander, before it counts as a long press. */
export const LONG_PRESS_MS = 500;
export const LONG_PRESS_SLOP = 10;
/** Taps and buttons inside a pressable thing that keep their own meaning. */
const DEFAULT_IGNORE = "input, select, textarea, a";
/** How long after a long press the click that follows it is still swallowed (see `armSuppress`). */
const SUPPRESS_MS = 400;

export type LongPressOptions = {
  /** Milliseconds a press must last. Default 500. */
  delay?: number;
  /** Pixels the pointer may move before the press is taken for a scroll and dropped. Default 10. */
  slop?: number;
  /** Off, nothing is started (and the touch context menu is left alone). Default on. */
  enabled?: boolean;
  /** A mouse can long-press too. Off by default: on a desktop a held mouse button is a text selection. */
  mouse?: boolean;
  /** Presses starting on something matching this selector are left to it. Default: inputs, selects and links. */
  ignore?: string;
};

type Gesture = { id: number; x: number; y: number; timer: ReturnType<typeof setTimeout>; fired: boolean };

/**
 * A long press on a list's rows, with Pointer Events so it behaves in Telegram's phone web views and
 * under touch emulation alike. `bind(key)` gives the props for one row; `onLongPress(key)` runs once
 * when the finger has stayed put for `delay` ms.
 *
 * - Moving more than `slop` px first (a scroll), lifting early, `pointercancel` (the browser took
 *   the touch to scroll) or a second finger all drop the press.
 * - After a long press has fired, the click that follows the finger lifting is swallowed, so the row's
 *   own tap (opening it) doesn't also happen.
 * - On a touch screen the context menu (the iOS/Android callout) is prevented. A mouse's right-click
 *   keeps its menu, and is never a long press (only the primary button is).
 */
export function useLongPress<K>(onLongPress: (key: K) => void, options: LongPressOptions = {}) {
  const { delay = LONG_PRESS_MS, slop = LONG_PRESS_SLOP, enabled = true, mouse = false, ignore = DEFAULT_IGNORE } = options;
  const gesture = useRef<Gesture | null>(null);
  const suppress = useRef<ReturnType<typeof setTimeout> | null>(null);
  const touchLike = useRef(false);
  // Always the latest, so a row re-rendering mid-press doesn't restart anything.
  const latest = useRef({ onLongPress, delay, slop, enabled, mouse, ignore });
  latest.current = { onLongPress, delay, slop, enabled, mouse, ignore };

  const drop = () => {
    if (gesture.current) clearTimeout(gesture.current.timer);
    gesture.current = null;
  };
  const clearSuppress = () => {
    if (suppress.current) clearTimeout(suppress.current);
    suppress.current = null;
  };
  useEffect(
    () => () => {
      drop();
      clearSuppress();
    },
    [],
  );

  return useMemo(() => {
    /** A long press that fired is followed by a click on release, which must not open the row. If no
     * click comes (the finger slid off first) the flag must not outlive the gesture and eat a later tap. */
    const armSuppress = () => {
      clearSuppress();
      suppress.current = setTimeout(() => (suppress.current = null), SUPPRESS_MS);
    };
    return (key: K) => ({
      onPointerDown(e: PointerEvent<HTMLElement>) {
        const opts = latest.current;
        touchLike.current = e.pointerType !== "mouse";
        clearSuppress();
        // A second finger (or any other pointer) turns a press into something else: a pinch, say.
        if (!e.isPrimary || (gesture.current && gesture.current.id !== e.pointerId)) {
          drop();
          return;
        }
        if (!opts.enabled || e.button !== 0) return;
        if (e.pointerType === "mouse" && !opts.mouse) return;
        if (e.target instanceof Element && opts.ignore && e.target.closest(opts.ignore)) return;
        drop();
        const started: Gesture = {
          id: e.pointerId,
          x: e.clientX,
          y: e.clientY,
          fired: false,
          timer: setTimeout(() => {
            started.fired = true;
            latest.current.onLongPress(key);
          }, opts.delay),
        };
        gesture.current = started;
      },
      onPointerMove(e: PointerEvent<HTMLElement>) {
        const g = gesture.current;
        if (!g || g.fired || g.id !== e.pointerId) return;
        if (Math.hypot(e.clientX - g.x, e.clientY - g.y) > latest.current.slop) drop();
      },
      onPointerUp(e: PointerEvent<HTMLElement>) {
        const g = gesture.current;
        if (!g || g.id !== e.pointerId) return;
        const fired = g.fired;
        drop();
        if (fired) armSuppress();
      },
      onPointerCancel(e: PointerEvent<HTMLElement>) {
        // The browser took the touch (to scroll, say): no click follows, so nothing to swallow.
        if (gesture.current && gesture.current.id === e.pointerId) drop();
        else if (!e.isPrimary) drop();
      },
      onClickCapture(e: MouseEvent<HTMLElement>) {
        if (suppress.current === null) return;
        clearSuppress();
        e.preventDefault();
        e.stopPropagation();
      },
      onContextMenu(e: MouseEvent<HTMLElement>) {
        // The callout a long press raises on a touch screen; a mouse's right-click keeps its menu.
        if (latest.current.enabled && touchLike.current) e.preventDefault();
      },
    });
  }, []);
}
