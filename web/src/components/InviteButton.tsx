import { useRef, useState } from "react";

import { api } from "../api";
import { Button } from "./ui";

import "../pages/settings.css";

type Invite = { url: string; expires_at?: string };

/** "Fri 20 Nov, 14:05" in the viewer's own zone; nothing when the server sent no usable time. */
function until(expiresAt: string | undefined): string | null {
  const date = expiresAt ? new Date(expiresAt) : null;
  if (!date || Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** A fresh invite: the link to copy (or select by hand) and how long it works. "Copied" is announced. */
function InviteCard({ invite }: { invite: Invite }) {
  const field = useRef<HTMLInputElement>(null);
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const expires = until(invite.expires_at);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(invite.url);
      setCopy("copied");
    } catch {
      // No clipboard permission (or an old browser): select it, so a long press or Ctrl+C finishes the job.
      field.current?.select();
      setCopy("failed");
    }
  }

  return (
    <div className="invite-card">
      <p className="invite-note">Single-use link, valid for 24 hours{expires ? ` (until ${expires})` : ""}.</p>
      <label className="field">
        Invite link
        <input ref={field} className="input" readOnly value={invite.url} onFocus={(e) => e.currentTarget.select()} />
      </label>
      <div className="invite-actions">
        <Button size="sm" onClick={() => void copyLink()}>
          Copy
        </Button>
        <p className={`caption${copy === "failed" ? " error-text" : ""}`} role="status">
          {copy === "copied" ? "Copied" : copy === "failed" ? "Couldn't copy. Select the link and copy it." : ""}
        </p>
      </div>
    </div>
  );
}

/** Makes a single-use invite and shows its link. In the desktop rail it is a quiet button; as a Settings
 * row (`variant="row"`) it is a full-width row, so an owner on a phone can invite too. */
export function InviteButton({ variant = "rail" }: { variant?: "rail" | "row" }) {
  const [invite, setInvite] = useState<Invite | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      setInvite(await api<Invite>("/invites", { method: "POST" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create an invite");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={variant === "row" ? "invite invite-row" : "invite"}>
      {variant === "row" ? (
        <button type="button" className="row-line row-press" disabled={busy} onClick={() => void create()}>
          <span className="row-text">
            <span className="row-title">Invite someone</span>
            <span className="row-sub">Make a link that lets one person sign in</span>
          </span>
        </button>
      ) : (
        <Button variant="text" disabled={busy} onClick={() => void create()}>
          Invite someone
        </Button>
      )}
      {invite && <InviteCard key={invite.url} invite={invite} />}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
