import { type FormEvent, type ReactNode, useId, useRef } from "react";

import { Icon } from "./Icon";
import { Overlay } from "./overlay/Overlay";

/** The one sheet for the travel pages: a bottom sheet on a phone, a centred dialog on
 * a desktop. It brings the title, the close button (and a back button when ``onBack``
 * is given), Escape and a click outside to close, a swipe down to close (from the grab
 * area, or by pulling down at the top of the body), focus in and back out, and a page
 * behind that stays put. ``as="form"`` makes the dialog itself a form (give it
 * ``onSubmit``). ``footer`` stays in view below the scrolling body. */
export function Sheet({
  title,
  titleId,
  describedBy,
  initialFocus,
  onClose,
  onBack,
  backLabel,
  className,
  as = "section",
  onSubmit,
  children,
  footer,
}: {
  title: string;
  titleId?: string;
  /** The id of an element that describes the dialog (an error, say). */
  describedBy?: string;
  /** Where focus goes as it opens: a selector, or "dialog" for the dialog itself. By default the first field of the body. */
  initialFocus?: string;
  onClose: () => void;
  onBack?: () => void;
  /** The back button's name; "Back" by default. */
  backLabel?: string;
  className?: string;
  as?: "section" | "form";
  onSubmit?: (event: FormEvent<HTMLFormElement>) => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const generated = useId();
  const id = titleId ?? `sheet-title-${generated}`;
  const handle = useRef<HTMLDivElement | null>(null);
  const body = useRef<HTMLDivElement | null>(null);

  return (
    <Overlay
      shape="sheet"
      labelledBy={id}
      describedBy={describedBy}
      onClose={onClose}
      as={as}
      onSubmit={onSubmit}
      className={className ? `sheet-dialog ${className}` : "sheet-dialog"}
      backdropClassName="sheet-backdrop"
      initialFocus={initialFocus ?? ".sheet-body"}
      handle={handle}
      scroller={body}
    >
      <div ref={handle} className="sheet-handle">
        <span className="overlay-grab sheet-grab" aria-hidden="true" />
        <div className="sheet-head">
          {onBack && (
            <button type="button" className="sheet-icon" onClick={onBack} aria-label={backLabel ?? "Back"}>
              <Icon name="chevronLeft" size={22} />
            </button>
          )}
          <h2 id={id}>{title}</h2>
          <button type="button" className="sheet-icon" onClick={onClose} aria-label="Close">
            <Icon name="x" size={22} />
          </button>
        </div>
      </div>
      <div ref={body} className="sheet-body">
        {children}
      </div>
      {footer && <div className="sheet-foot">{footer}</div>}
    </Overlay>
  );
}
