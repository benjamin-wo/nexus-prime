import { type FormEvent, type ReactNode, useCallback, useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

import { Icon } from "./Icon";

/** Fields a sheet puts the cursor in as it opens. A file input is skipped: it is
 * a hidden control behind a button, not somewhere to type. */
const FIELD = "input:not([type=hidden]):not([type=file]):not(:disabled), select:not(:disabled), textarea:not(:disabled)";

/** The one sheet for the travel pages: a bottom sheet on a phone, a centred dialog on
 * a desktop. It brings the title, the close button (and a back button when ``onBack``
 * is given), Escape and a click outside to close, focus in and back out, and a page
 * behind that stays put. ``as="form"`` makes the dialog itself a form (give it
 * ``onSubmit``). ``footer`` stays in view below the scrolling body. */
export function Sheet({
  title,
  titleId,
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
  const dialog = useRef<HTMLElement | null>(null);
  const setDialog = useCallback((el: HTMLElement | null) => {
    dialog.current = el;
  }, []);
  // Read while rendering, before any child's effect can move the focus.
  const opener = useRef<Element | null>(typeof document === "undefined" ? null : document.activeElement);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  // Focus goes to the first field (unless a child already took it), else the dialog,
  // and comes back to where it was.
  useEffect(() => {
    const el = dialog.current;
    if (el && !el.contains(document.activeElement)) {
      const field = el.querySelector(".sheet-body")?.querySelector<HTMLElement>(FIELD);
      (field ?? el).focus({ preventScroll: true });
    }
    const back = opener.current;
    return () => {
      if (back instanceof HTMLElement && back.isConnected) back.focus({ preventScroll: true });
    };
  }, []);

  // The page behind does not scroll.
  useEffect(() => {
    const was = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = was;
    };
  }, []);

  const Tag = as;
  return createPortal(
    <div className="sheet-backdrop" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <Tag
        ref={setDialog}
        className={className ? `sheet-dialog ${className}` : "sheet-dialog"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        tabIndex={-1}
        onSubmit={as === "form" ? onSubmit : undefined}
      >
        <span className="sheet-grab" aria-hidden="true" />
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
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </Tag>
    </div>,
    document.body,
  );
}
