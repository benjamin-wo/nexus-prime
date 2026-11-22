import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type Memory } from "../api";
import { ConfirmBox } from "../components/ConfirmBox";
import { Button, Section } from "../components/ui";

import "./settings.css";

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
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A forgotten memory can't be brought back, so it asks first, then says if it didn't work.
  async function forget() {
    setBusy(true);
    setError(null);
    try {
      await api(`/memories/${memory.id}`, { method: "DELETE" });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't forget that");
      setConfirming(false);
      setBusy(false);
    }
  }

  return (
    <li className="memory-row">
      <span className="wrap">
        {memory.happened_on && <span className="caption">{day(memory.happened_on)} · </span>}
        {memory.text}
      </span>
      {!confirming && (
        <Button variant="text" onClick={() => setConfirming(true)} aria-label={`Forget: ${memory.text}`}>
          Forget
        </Button>
      )}
      {confirming && (
        <ConfirmBox
          label={`Forget: ${memory.text}`}
          question="Forget this? Nexus won't remember it."
          confirm="Forget"
          busy={busy}
          onConfirm={() => void forget()}
          onKeep={() => setConfirming(false)}
        />
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** What Nexus has picked up from your own messages, with a way to forget any of it. */
export function MemorySection() {
  const client = useQueryClient();
  const memories = useQuery({ queryKey: ["memories"], queryFn: () => api<Memory[]>("/memories") });
  const [confirmAll, setConfirmAll] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function refresh() {
    void client.invalidateQueries({ queryKey: ["memories"] });
  }

  async function forgetAll() {
    setError(null);
    try {
      await api("/memories", { method: "DELETE" });
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't forget everything");
    } finally {
      setConfirmAll(false);
    }
  }

  const items = memories.data ?? [];
  return (
    <Section id="memory" title="What Nexus remembers">
      <p className="caption set-intro">Only from what you tell it</p>
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
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {items.length > 0 && (
        <div className="memory-foot">
          {confirmAll ? (
            <span className="quick">
              <span>Forget everything?</span>
              <Button variant="danger" onClick={forgetAll}>
                Forget all
              </Button>
              <Button onClick={() => setConfirmAll(false)}>
                Keep
              </Button>
            </span>
          ) : (
            <Button variant="text" onClick={() => setConfirmAll(true)}>
              Forget everything
            </Button>
          )}
        </div>
      )}
    </Section>
  );
}
