import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Frequency, type Updates } from "../api";

const ORDER: Frequency[] = ["instant", "hourly", "thrice_daily", "daily", "off"];

/** How often Nexus messages the user on Telegram about their transactions. */
export function UpdatesSection() {
  const client = useQueryClient();
  const updates = useQuery({ queryKey: ["notifications"], queryFn: () => api<Updates>("/notifications") });
  const [error, setError] = useState<string | null>(null);

  // The number being typed, kept apart from the saved one until the field is left.
  const [moveDraft, setMoveDraft] = useState<string | null>(null);
  const [capDraft, setCapDraft] = useState<string | null>(null);

  /** Sends only what changed. The screen follows at once, and goes back for just those fields if
   * the save fails; a slower answer to an earlier save never undoes a later change. */
  async function save(patch: Partial<Pick<Updates, "quiet_start" | "quiet_end" | "market_summary" | "daily_cap">> & { move_alert_percent?: number }) {
    setError(null);
    const keys = Object.keys(patch) as (keyof Updates)[];
    const apply = (from: Updates) => (old: Updates | undefined) =>
      old ? ({ ...old, ...Object.fromEntries(keys.map((k) => [k, from[k]])) } as Updates) : from;
    const before = client.getQueryData<Updates>(["notifications"]);
    if (before && patch.move_alert_percent === undefined) client.setQueryData(["notifications"], apply({ ...before, ...patch } as Updates));
    try {
      const saved = await api<Updates>("/notifications", { method: "PUT", body: patch });
      client.setQueryData(["notifications"], apply(saved));
    } catch (e) {
      if (before) client.setQueryData(["notifications"], apply(before));
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  async function choose(frequency: Frequency, dailyAt?: string) {
    setError(null);
    try {
      const body = dailyAt ? { frequency, daily_at: dailyAt } : { frequency };
      const saved = await api<Updates>("/notifications", { method: "PUT", body });
      client.setQueryData(["notifications"], saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    }
  }

  function leaveMove(current: number) {
    const typed = moveDraft?.trim();
    setMoveDraft(null);
    if (!typed) return;
    const value = Number(typed);
    if (Number.isNaN(value)) {
      setError("Enter a number from 1 to 20");
      return;
    }
    if (value !== current) void save({ move_alert_percent: value });
  }

  function leaveCap(current: number) {
    const typed = capDraft?.trim();
    setCapDraft(null);
    if (!typed) return;
    const value = Number(typed);
    if (!Number.isInteger(value) || value < 3 || value > 20) {
      setError("Enter a whole number from 3 to 20");
      return;
    }
    if (value !== current) void save({ daily_cap: value });
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
          {data.frequency === "daily" && (
            <label className="field">
              Daily summary at
              <input
                className="input"
                type="time"
                step={60}
                value={data.daily_at}
                onChange={(e) => {
                  if (e.target.value) void choose("daily", e.target.value);
                }}
              />
            </label>
          )}
          <p className="caption">
            {data.description}{" "}
            {data.frequency === "daily"
              ? "It goes at the time you pick, any hour; nothing is sent when nothing happened."
              : "Nothing is sent in your quiet hours, or when nothing happened."}
          </p>
          <div className="settings-group">
            <fieldset className="field-group setting">
              <legend>Quiet hours</legend>
              <div className="quiet-times">
                <label className="field">
                  From
                  <input
                    className="input"
                    type="time"
                    step={60}
                    value={data.quiet_start}
                    onChange={(e) => {
                      if (e.target.value) void save({ quiet_start: e.target.value });
                    }}
                  />
                </label>
                <label className="field">
                  To
                  <input
                    className="input"
                    type="time"
                    step={60}
                    value={data.quiet_end}
                    onChange={(e) => {
                      if (e.target.value) void save({ quiet_end: e.target.value });
                    }}
                  />
                </label>
              </div>
              <p className="caption">
                Nexus holds its messages in these hours. A broken stop on a stock you hold still comes through.
              </p>
            </fieldset>
          </div>
          <div className="settings-group">
            <div className="setting">
              <label className="field">
                Messages a day
                <input
                  className="input"
                  type="number"
                  inputMode="numeric"
                  min={3}
                  max={20}
                  step={1}
                  value={capDraft ?? String(data.daily_cap)}
                  aria-describedby="daily-cap-hint"
                  onChange={(e) => setCapDraft(e.target.value)}
                  onBlur={() => leaveCap(data.daily_cap)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") leaveCap(data.daily_cap);
                  }}
                />
              </label>
              <p id="daily-cap-hint" className="caption">
                After this many (3 to 20), the rest wait for a digest. Urgent messages, ones with buttons and your summaries still come.
              </p>
            </div>
          </div>
          <div className="settings-group">
            <h3>Investments</h3>
            <div className="setting">
            <label className="field">
              Big move alerts (%)
              <input
                className="input"
                type="number"
                inputMode="decimal"
                min={1}
                max={20}
                step="any"
                value={moveDraft ?? String(Number(data.move_alert_percent))}
                aria-describedby="move-alert-hint"
                onChange={(e) => setMoveDraft(e.target.value)}
                onBlur={() => leaveMove(Number(data.move_alert_percent))}
                onKeyDown={(e) => {
                  if (e.key === "Enter") leaveMove(Number(data.move_alert_percent));
                }}
              />
            </label>
            <p id="move-alert-hint" className="caption">
              Tell me when a stock I hold or watch moves this much in a day: 1 to 20%.
            </p>
            </div>
            <div className="setting">
            <label className="share-switch">
              <input
                type="checkbox"
                role="switch"
                checked={data.market_summary}
                onChange={(e) => void save({ market_summary: e.target.checked })}
                aria-describedby="market-summary-hint"
              />
              <span>Morning investment summary</span>
            </label>
            <p id="market-summary-hint" className="caption">
              At 8am after each US trading day.
            </p>
            </div>
          </div>
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
