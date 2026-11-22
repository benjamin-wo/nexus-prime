import { useEffect } from "react";

import { Button } from "./ui";

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
        <Button onClick={action.run}>
          {action.label}
        </Button>
      )}
      {also && (
        <Button onClick={also.run}>
          {also.label}
        </Button>
      )}
      <Button variant="text" aria-label="Dismiss" onClick={onClose}>
        ×
      </Button>
    </div>
  );
}
