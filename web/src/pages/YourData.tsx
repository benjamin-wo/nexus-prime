import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { ApiError, deleteEverything, exportAll, setCsrf } from "../api";
import { downloadNote, inPhoneWebview } from "../telegram";

/** The word to type before everything is deleted; anything else, even a different case, keeps the button off. */
export function canConfirmDelete(typed: string): boolean {
  return typed === "DELETE";
}

/** Download all my data, and delete everything. */
export function YourDataSection() {
  const client = useQueryClient();
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const field = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);

  useEffect(() => {
    if (confirming) field.current?.focus();
    else if (wasConfirming.current) opener.current?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);

  async function download() {
    setExporting(true);
    setExported(false);
    setExportError(null);
    try {
      await exportAll();
      setExported(true);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Couldn't prepare your download. Please try again.");
    } finally {
      setExporting(false);
    }
  }

  function cancel() {
    setConfirming(false);
    setTyped("");
    setDeleteError(null);
  }

  async function remove() {
    if (!canConfirmDelete(typed) || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteEverything();
    } catch (e) {
      setDeleteError(
        e instanceof ApiError && e.status === 422
          ? "That didn't match. Type DELETE in capitals to confirm."
          : e instanceof Error
            ? e.message
            : "Couldn't delete your data. Please try again.",
      );
      setDeleting(false);
      return;
    }
    // The session is gone: show the signed-out screen, as Sign out does, and forget everything held for this person.
    setCsrf("");
    client.setQueryData(["me"], null);
    client.removeQueries({ predicate: (query) => query.queryKey[0] !== "me" });
  }

  const note = exported ? downloadNote(inPhoneWebview()) : null;
  return (
    <section className="card" aria-labelledby="your-data">
      <div className="card-head">
        <h2 id="your-data">Download or delete</h2>
        <span className="caption">Everything Nexus keeps for you</span>
      </div>
      <div className="setting">
        <p>
          <strong>Download all my data</strong>
        </p>
        <p className="caption">Your ledger, budgets, trips, investments, memories and settings, as a zip.</p>
        <div className="actions tz-actions">
          <button type="button" className="btn btn-small" disabled={exporting} aria-busy={exporting} onClick={() => void download()}>
            {exporting ? "Preparing…" : "Download"}
          </button>
        </div>
        {exported && (
          <p className="caption" role="status">
            Downloaded.
            {note && <> {note}</>}
          </p>
        )}
        {exportError && (
          <p className="error-text" role="alert">
            {exportError}
          </p>
        )}
      </div>
      <div className="settings-group setting">
        <p>
          <strong>Delete everything</strong>
        </p>
        <p className="caption">
          Deletes your ledger, trips, investments, memories and settings, and disconnects email. Trips you shared stop being shared. This
          can't be undone, and you'd need a new invite to come back.
        </p>
        {!confirming && (
          <div className="actions tz-actions">
            <button ref={opener} type="button" className="btn btn-ghost btn-danger btn-small" onClick={() => setConfirming(true)}>
              Delete everything…
            </button>
          </div>
        )}
        {confirming && (
          <form
            className="confirm-box confirm-danger"
            onSubmit={(e) => {
              e.preventDefault();
              void remove();
            }}
          >
            <label className="field">
              Type DELETE to confirm
              <input
                ref={field}
                className="input"
                value={typed}
                autoComplete="off"
                autoCapitalize="off"
                spellCheck={false}
                disabled={deleting}
                onChange={(e) => setTyped(e.target.value)}
              />
            </label>
            <div className="people-actions">
              <button type="submit" className="btn btn-danger" disabled={!canConfirmDelete(typed) || deleting}>
                {deleting ? "Deleting…" : "Delete everything"}
              </button>
              <button type="button" className="btn" disabled={deleting} onClick={cancel}>
                Cancel
              </button>
            </div>
          </form>
        )}
        {deleteError && (
          <p className="error-text" role="alert">
            {deleteError}
          </p>
        )}
      </div>
    </section>
  );
}
