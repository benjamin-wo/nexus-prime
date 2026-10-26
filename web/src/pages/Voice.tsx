import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, type VoiceSettings, type VoiceUpdate } from "../api";
import { previewReplies } from "../voice";

const KEY = ["settings", "voice"];
/** The longest a note can be. */
export const NOTE_LIMIT = 200;

type Dial = { name: "emoji" | "length" | "humour"; label: string; options: { value: string; label: string }[] };

const DIALS: Dial[] = [
  {
    name: "emoji",
    label: "Emoji",
    options: [
      { value: "none", label: "None" },
      { value: "some", label: "Some" },
      { value: "lots", label: "Lots" },
    ],
  },
  {
    name: "length",
    label: "Length",
    options: [
      { value: "short", label: "Short" },
      { value: "normal", label: "Normal" },
      { value: "detailed", label: "Detailed" },
    ],
  },
  {
    name: "humour",
    label: "Humour",
    options: [
      { value: "off", label: "Off" },
      { value: "light", label: "Light" },
      { value: "playful", label: "Playful" },
    ],
  },
];

/** What the settings will read once `update` is saved: a new preset takes its own dials unless dials are sent too. */
function applied(current: VoiceSettings, update: VoiceUpdate): VoiceSettings {
  const next = { ...current };
  if (update.preset && update.preset !== current.preset) {
    const preset = current.presets.find((p) => p.id === update.preset);
    next.preset = update.preset;
    if (preset) {
      next.emoji = preset.emoji;
      next.length = preset.length;
      next.humour = preset.humour;
    }
  }
  if (update.emoji) next.emoji = update.emoji;
  if (update.length) next.length = update.length;
  if (update.humour) next.humour = update.humour;
  if (update.note !== undefined) next.note = update.note === "" ? null : update.note;
  return next;
}

/** How Nexus words its replies: a vibe, three dials and a note, with a preview that follows every change. Only wording. */
export function VoiceCard() {
  const client = useQueryClient();
  const voice = useQuery({ queryKey: KEY, queryFn: () => api<VoiceSettings>("/settings/voice") });
  const [error, setError] = useState<string | null>(null);
  // The note while it is being typed; null when the field just shows what is saved.
  const [draft, setDraft] = useState<string | null>(null);

  const save = useMutation({
    mutationKey: KEY,
    mutationFn: (update: VoiceUpdate) => api<VoiceSettings>("/settings/voice", { method: "PUT", body: update }),
    onMutate: async (update) => {
      await client.cancelQueries({ queryKey: KEY });
      const before = client.getQueryData<VoiceSettings>(KEY);
      if (before) client.setQueryData(KEY, applied(before, update));
      setError(null);
      return { before };
    },
    onError: (e, _update, context) => {
      // Put back what was there before the tap, unless a later tap is still on its way.
      if (context?.before && client.isMutating({ mutationKey: KEY }) <= 1) client.setQueryData(KEY, context.before);
      setError(e instanceof Error && e.message ? e.message : "Couldn't save");
    },
    onSuccess: (saved) => {
      // The server's word wins, but not over a later change that hasn't come back yet.
      if (client.isMutating({ mutationKey: KEY }) <= 1) client.setQueryData(KEY, saved);
    },
  });

  const data = voice.data;
  const note = draft ?? data?.note ?? "";

  function commitNote() {
    if (!data || draft === null) return;
    const text = draft.trim();
    setDraft(null);
    if (text !== (data.note ?? "")) save.mutate({ note: text });
  }

  const replies = data ? previewReplies(data.preset, data) : [];

  return (
    <section className="card voice-card" aria-labelledby="voice-title">
      <div className="card-head">
        <h2 id="voice-title">How Nexus talks</h2>
      </div>
      <p className="muted voice-lead">Pick a vibe, then fine-tune. Only changes wording — never what Nexus can do.</p>
      {voice.isLoading && <p className="state">Loading…</p>}
      {voice.isError && <p className="state error-text">Couldn't load how Nexus talks.</p>}
      {data && (
        <>
          <div className="voice-presets" role="group" aria-label="Vibe">
            {data.presets.map((preset) => (
              <button
                key={preset.id}
                type="button"
                className="voice-preset"
                aria-pressed={data.preset === preset.id}
                onClick={() => {
                  if (data.preset !== preset.id) save.mutate({ preset: preset.id });
                }}
              >
                <span className="voice-preset-label">{preset.label}</span>
                <span className="voice-preset-blurb">{preset.blurb}</span>
              </button>
            ))}
          </div>

          <div className="voice-dials">
            {DIALS.map((dial) => {
              const id = `voice-dial-${dial.name}`;
              return (
                <div className="voice-dial" key={dial.name}>
                  <span className="voice-dial-label" id={id}>
                    {dial.label}
                  </span>
                  <div className="seg" role="group" aria-labelledby={id}>
                    {dial.options.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className="seg-btn"
                        aria-pressed={data[dial.name] === option.value}
                        onClick={() => {
                          if (data[dial.name] !== option.value) {
                            save.mutate({ [dial.name]: option.value } as VoiceUpdate);
                          }
                        }}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          <label className="field voice-note">
            Anything else?
            <input
              className="input"
              type="text"
              value={note}
              maxLength={NOTE_LIMIT}
              placeholder="e.g. call me boss, no exclamation marks"
              autoComplete="off"
              aria-describedby="voice-note-count"
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitNote}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
              }}
            />
          </label>
          <p className="caption voice-note-count" id="voice-note-count">
            <span data-testid="voice-note-count">
              {note.length}/{NOTE_LIMIT}
            </span>
            <span> · Your note applies in chat</span>
          </p>

          <div className="voice-preview" role="region" aria-label="Preview">
            <h3 className="voice-preview-title">Preview</h3>
            <ul className="voice-replies">
              {replies.map((reply) => (
                <li key={reply.said} className="voice-reply">
                  <span className="caption voice-said">You: {reply.said}</span>
                  <span className="voice-text" data-testid="voice-reply">
                    {reply.text}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
      {error && (
        <p className="error-text voice-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
