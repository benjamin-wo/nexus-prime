import { type ReactNode, useEffect, useRef } from "react";

/** The one in-page "are you sure?": the question, the destructive button and a Keep button, where the
 * thing to remove already is (never the browser's own dialog). Focus lands on Keep, so a stray Enter
 * removes nothing. ``label`` names the group for screen readers. */
export function ConfirmBox({
  label,
  question,
  confirm,
  keep = "Keep",
  busy = false,
  onConfirm,
  onKeep,
}: {
  label: string;
  question: ReactNode;
  /** The destructive button's words: "Remove", "Delete trip". */
  confirm: string;
  keep?: string;
  busy?: boolean;
  onConfirm: () => void;
  onKeep: () => void;
}) {
  const keepButton = useRef<HTMLButtonElement>(null);
  useEffect(() => keepButton.current?.focus({ preventScroll: true }), []);
  return (
    <div className="confirm-box confirm-danger" role="group" aria-label={label}>
      <p>{question}</p>
      <div className="people-actions">
        <button type="button" className="btn btn-danger" disabled={busy} onClick={onConfirm}>
          {confirm}
        </button>
        <button ref={keepButton} type="button" className="btn" disabled={busy} onClick={onKeep}>
          {keep}
        </button>
      </div>
    </div>
  );
}
