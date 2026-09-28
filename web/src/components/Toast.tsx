import { useEffect } from "react";

export function Toast({
  message,
  action,
  onClose,
}: {
  message: string;
  action?: { label: string; run: () => void };
  onClose: () => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, 8000);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return (
    <div className="toast" role="status">
      <span>{message}</span>
      {action && (
        <button type="button" className="btn" onClick={action.run}>
          {action.label}
        </button>
      )}
      <button type="button" className="btn btn-ghost" aria-label="Dismiss" onClick={onClose}>
        ×
      </button>
    </div>
  );
}
