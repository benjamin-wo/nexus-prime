import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Memory } from "../api";

const KIND_LABEL: Record<Memory["kind"], string> = {
  fact: "About you",
  preference: "How you like things",
  episode: "Things that happened",
};
const ORDER: Memory["kind"][] = ["fact", "preference", "episode"];

function day(iso: string): string {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function MemoryRow({ memory, onChanged }: { memory: Memory; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);

  async function forget() {
    setBusy(true);
    try {
      await api(`/memories/${memory.id}`, { method: "DELETE" });
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  return (
    <li className="memory-row">
      <span className="wrap">
        {memory.happened_on && <span className="caption">{day(memory.happened_on)} · </span>}
        {memory.text}
      </span>
      <button type="button" className="btn btn-ghost" onClick={forget} disabled={busy} aria-label={`Forget: ${memory.text}`}>
        Forget
      </button>
    </li>
  );
}

/** What Nexus has picked up from your own messages, with a way to forget any of it. */
export function MemorySection() {
  const client = useQueryClient();
  const memories = useQuery({ queryKey: ["memories"], queryFn: () => api<Memory[]>("/memories") });
  const [confirmAll, setConfirmAll] = useState(false);

  function refresh() {
    void client.invalidateQueries({ queryKey: ["memories"] });
  }

  async function forgetAll() {
    await api("/memories", { method: "DELETE" });
    setConfirmAll(false);
    refresh();
  }

  const items = memories.data ?? [];
  return (
    <section className="card" aria-labelledby="memory">
      <div className="card-head">
        <h2 id="memory">What Nexus remembers</h2>
        <span className="caption">Only from what you tell it</span>
      </div>
      {memories.isLoading && <p className="state">Loading…</p>}
      {memories.isError && <p className="state error-text">Couldn't load memories.</p>}
      {memories.data?.length === 0 && (
        <p className="state">Nothing yet. Tell Nexus things like "Ann is my sister" or "keep replies short" and it will keep them in mind.</p>
      )}
      {ORDER.map((kind) => {
        const group = items.filter((m) => m.kind === kind);
        if (group.length === 0) return null;
        return (
          <div key={kind} className="memory-group">
            <h3 className="caption">{KIND_LABEL[kind]}</h3>
            <ul className="memory-list">
              {group.map((m) => (
                <MemoryRow key={m.id} memory={m} onChanged={refresh} />
              ))}
            </ul>
          </div>
        );
      })}
      {items.length > 0 && (
        <div className="memory-foot">
          {confirmAll ? (
            <span className="quick">
              <span>Forget everything?</span>
              <button type="button" className="btn btn-danger" onClick={forgetAll}>
                Forget all
              </button>
              <button type="button" className="btn" onClick={() => setConfirmAll(false)}>
                Keep
              </button>
            </span>
          ) : (
            <button type="button" className="btn btn-ghost" onClick={() => setConfirmAll(true)}>
              Forget everything
            </button>
          )}
        </div>
      )}
    </section>
  );
}
