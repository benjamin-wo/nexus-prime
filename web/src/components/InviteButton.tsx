import { useState } from "react";

import { api } from "../api";

export function InviteButton() {
  const [link, setLink] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function create() {
    setError(null);
    try {
      const invite = await api<{ url: string }>("/invites", { method: "POST" });
      setLink(invite.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create an invite");
    }
  }
  return (
    <div>
      <button type="button" className="btn btn-ghost" onClick={create}>
        Invite someone
      </button>
      {link && (
        <label className="field">
          Single-use link, valid 24 hours
          <input className="input" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
        </label>
      )}
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
