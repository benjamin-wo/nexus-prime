import { useEffect } from "react";

export type ToastAction = { label: string; run: () => void };

/** A line at the bottom of the page that goes away by itself. ``action`` is its one button (Undo,
 * Save rule); two buttons (``also``) stack under the words on a phone so neither wraps. */
export function Toast({
  message,
  action,
  also,
  onClose,
}: {
  message: string;
  action?: ToastAction;
  also?: ToastAction;
  onClose: () => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, 8000);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return (
    <div className={also ? "toast toast-two" : "toast"} role="status">
      <span>{message}</span>
      {action && (
        <button type="button" className="btn" onClick={action.run}>
          {action.label}
        </button>
      )}
      {also && (
        <button type="button" className="btn" onClick={also.run}>
          {also.label}
        </button>
      )}
      <button type="button" className="btn btn-ghost" aria-label="Dismiss" onClick={onClose}>
        ×
      </button>
    </div>
  );
}
