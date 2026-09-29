import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Frequency, type Updates } from "../api";

const ORDER: Frequency[] = ["instant", "hourly", "thrice_daily", "daily", "off"];

/** How often Nexus messages the user on Telegram about their transactions. */
export function UpdatesSection() {
  const client = useQueryClient();
  const updates = useQuery({ queryKey: ["notifications"], queryFn: () => api<Updates>("/notifications") });
  const [error, setError] = useState<string | null>(null);

  async function choose(frequency: Frequency) {
    setError(null);
    try {
      const saved = await api<Updates>("/notifications", { method: "PUT", body: { frequency } });
      client.setQueryData(["notifications"], saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  const data = updates.data;
  return (
    <section className="card" aria-labelledby="updates">
      <div className="card-head">
        <h2 id="updates">Telegram updates</h2>
        <span className="caption">Your transactions, sent to you</span>
      </div>
      {updates.isLoading && <p className="state">Loading…</p>}
      {updates.isError && <p className="state error-text">Couldn't load your updates setting.</p>}
      {data && (
        <>
          <label className="field">
            Send me my transactions
            <select
              className="input"
              value={data.frequency}
              onChange={(e) => void choose(e.target.value as Frequency)}
            >
              {ORDER.map((f) => (
                <option key={f} value={f}>
                  {data.options[f]}
                </option>
              ))}
            </select>
          </label>
          <p className="caption">
            {data.description} Nothing is sent between 10pm and 8am, or when nothing happened.
          </p>
        </>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
