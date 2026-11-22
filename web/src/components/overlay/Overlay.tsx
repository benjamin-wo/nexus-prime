import { type FormEvent, type ReactNode, type RefObject, useCallback, useRef } from "react";
import { createPortal } from "react-dom";

import { COMPACT_QUERY, PHONE_QUERY, useMediaQuery } from "./breakpoints";
import "./overlay.css";
import { useDragToClose } from "./useDragToClose";
import { useEscapeStack } from "./useEscapeStack";
import { useFocusManagement } from "./useFocusManagement";
import { useScrollLock } from "./useScrollLock";

export type OverlayProps = {
  /** `sheet`: a backdrop and a panel, a centred dialog or (at 720px and below) a bottom sheet, always modal.
   * `panel`: no backdrop; the layer above lays it out (a side panel, full screen on a phone). */
  shape: "sheet" | "panel";
  /** The id of the element that names the dialog. */
  labelledBy: string;
  describedBy?: string;
  /** Escape, a click on the backdrop and a finished swipe all call this. */
  onClose: () => void;
  /** Whether the page behind is out of play (focus trapped, scroll locked, `aria-modal`). A sheet is always modal. */
  modal?: boolean;
  /** A selector for the part to put the cursor in (its first field), or "dialog" for the dialog itself.
   * By default the first field anywhere in the panel. */
  initialFocus?: string;
  as?: "div" | "section" | "form";
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
  className?: string;
  backdropClassName?: string;
  /** Set to the panel element, for the layer above. */
  panelRef?: RefObject<HTMLElement | null>;
  /** The grab area (the layer above renders it): dragging it down closes the overlay. */
  handle?: RefObject<HTMLElement | null>;
  /** The scrolling body: a pull down from its top closes a sheet. Not used by a panel. */
  scroller?: RefObject<HTMLElement | null>;
  children: ReactNode;
};

/**
 * The one overlay: every sheet, dialog and the chat panel are this with something inside. It always renders into
 * a portal on `document.body`, and brings Escape (newest overlay first), a click on the backdrop to close,
 * focus in, trapped and back out, a page behind that stays put, and a swipe down to close.
 */
export function Overlay({
  shape,
  labelledBy,
  describedBy,
  onClose,
  modal = true,
  initialFocus,
  as = "div",
  onSubmit,
  className,
  backdropClassName,
  panelRef,
  handle,
  scroller,
  children,
}: OverlayProps) {
  const sheet = shape === "sheet";
  const trapped = sheet || modal;
  const panel = useRef<HTMLElement | null>(null);
  const backdrop = useRef<HTMLDivElement | null>(null);
  const ownHandle = useRef<HTMLElement | null>(null);
  const setPanel = useCallback(
    (el: HTMLElement | null) => {
      panel.current = el;
      if (panelRef) panelRef.current = el;
    },
    [panelRef],
  );

  // A sheet drags from the handle and from the top of its body at the compact breakpoint; a panel from its handle on a phone.
  const compact = useMediaQuery(COMPACT_QUERY);
  const phone = useMediaQuery(PHONE_QUERY);
  useDragToClose({
    handle: handle ?? ownHandle,
    panel,
    backdrop: sheet ? backdrop : undefined,
    scroller: sheet ? scroller : undefined,
    onClose,
    enabled: sheet ? compact : phone,
  });
  useEscapeStack(onClose);
  useFocusManagement({ panel, modal: trapped, initialFocus });
  useScrollLock(trapped);

  const Tag = as;
  const classes = ["overlay-panel", sheet ? "overlay-sheet" : "overlay-panel-side", className].filter(Boolean).join(" ");
  const dialog = (
    <Tag
      ref={setPanel as never}
      className={classes}
      role="dialog"
      aria-modal={trapped ? "true" : "false"}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      tabIndex={-1}
      onSubmit={as === "form" ? (onSubmit as never) : undefined}
    >
      {children}
    </Tag>
  );
  return createPortal(
    sheet ? (
      <div
        ref={backdrop}
        className={backdropClassName ? `overlay-backdrop ${backdropClassName}` : "overlay-backdrop"}
        onClick={(e) => e.target === e.currentTarget && onClose()}
      >
        {dialog}
      </div>
    ) : (
      dialog
    ),
    document.body,
  );
}
