import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, apiForm, ApiError, type ChatHistory, type Reply } from "../api";
import { openExternal } from "../telegram";
import { clock, MAX_VOICE_SECONDS, NO_MIC_HINT, canRecord, useVoiceRecorder, type Recorded } from "../useVoiceRecorder";
import { Icon } from "./Icon";

type Message = {
  from: "user" | "bot";
  text: string;
  buttons: Reply["buttons"];
  telegram?: boolean;
  at?: string;
};

function fromHistory(history: ChatHistory): Message[] {
  return history.lines.map((line) => ({
    from: line.role === "user" ? "user" : "bot",
    text: line.text,
    buttons: [],
    telegram: line.channel === "telegram",
    at: line.at,
  }));
}

/** What the person's side of the chat says while a voice note is on its way. */
const VOICE_PLACEHOLDER = "🎙 Voice note…";

/** Why a voice note was refused, in the server's words when it gave some. */
function voiceFailure(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.message) return error.message;
    if (error.status === 413) return "That's too long — keep voice notes under 2 minutes.";
    if (error.status === 415) return "That audio format isn't supported.";
    if (error.status === 429) return "Too many voice notes just now — try again in a moment.";
    if (error.status === 503) return "Voice notes aren't available right now — try again later.";
  }
  return "Couldn't send that voice note. Try again.";
}

// After this long, the typing bubble also says it's still going.
const STILL_WORKING_MS = 10_000;

/** Nexus's side of the chat while a reply is worked out: three dots, then a word
 * that it's still going, so a slow reply never looks like nothing is happening. */
function Typing() {
  const [long, setLong] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setLong(true), STILL_WORKING_MS);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <div
      className="msg msg-bot typing"
      role="status"
      aria-label="Nexus is typing"
    >
      <span className="typing-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      {long && <span className="typing-note">Still working on it…</span>}
    </div>
  );
}

const WHEN = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  hour: "numeric",
  minute: "2-digit",
});

/** The same agent and conversation as Telegram, with the same confirmation buttons.
 * It opens on the running chat so far (from the web or Telegram; notifications
 * aren't part of it), with older messages a tap away. */
export function ChatDrawer({
  ask,
  onClose,
  onChanged,
}: {
  ask?: string; // a question asked on Home, sent as soon as the chat opens
  onClose: () => void;
  onChanged: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [more, setMore] = useState(false);
  const [oldest, setOldest] = useState<number | null>(null);
  // A line under the messages about the mic: the one-time "not available" hint or why a note failed.
  const [note, setNote] = useState<{ kind: "hint" | "error"; text: string } | null>(null);
  // The mic was refused (or broke) in this browser: stop offering it.
  const [micBlocked, setMicBlocked] = useState(false);
  const [micSupported] = useState(canRecord);
  const micAvailable = micSupported && !micBlocked;
  const input = useRef<HTMLInputElement>(null);
  const stopButton = useRef<HTMLButtonElement>(null);
  const end = useRef<HTMLDivElement>(null);
  // Keep to the newest message, except right after loading older ones.
  const stick = useRef(true);

  // Effects use braces so nothing is returned: React would call a returned value as a
  // cleanup, and newer browsers return a promise from scrollIntoView().
  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    if (stick.current) end.current?.scrollIntoView?.({ block: "end" });
    stick.current = true;
  }, [messages]);
  useEffect(() => {
    if (busy) end.current?.scrollIntoView?.({ block: "end" });
  }, [busy]);
  useEffect(() => {
    let live = true;
    api<ChatHistory>("/chat/history")
      .then((history) => {
        if (!live) return;
        const earlier = fromHistory(history);
        const pending = history.pending;
        if (pending) {
          const last = earlier.at(-1);
          if (last && last.from === "bot" && last.text === pending.text)
            last.buttons = pending.buttons;
          else
            earlier.push({
              from: "bot",
              text: pending.text,
              buttons: pending.buttons,
            });
        }
        setMore(history.more);
        setOldest(history.lines[0]?.id ?? null);
        setMessages((m) => [...earlier, ...m]);
      })
      .catch(() => undefined); // the chat still works without its history
    return () => {
      live = false;
    };
  }, []);

  async function loadEarlier() {
    if (!oldest) return;
    const history = await api<ChatHistory>(
      `/chat/history?before=${oldest}`,
    ).catch(() => null);
    if (!history) return;
    stick.current = false;
    setMore(history.more);
    setOldest(history.lines[0]?.id ?? oldest);
    setMessages((m) => [...fromHistory(history), ...m]);
  }
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run(call: Promise<Reply[]>, failed?: (e: unknown) => void) {
    setBusy(true);
    try {
      const replies = await call;
      setMessages((m) => [
        ...m,
        ...replies.map((r) => ({
          from: "bot" as const,
          text: r.text,
          buttons: r.buttons,
        })),
      ]);
      onChanged();
    } catch (e) {
      if (failed) {
        failed(e);
        return;
      }
      const text = e instanceof Error ? e.message : "Something went wrong";
      setMessages((m) => [
        ...m,
        { from: "bot", text: `Sorry: ${text}`, buttons: [] },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function say(text: string) {
    setMessages((m) => [...m, { from: "user", text, buttons: [] }]);
    void run(
      api<Reply[]>("/chat", { method: "POST", body: { message: text } }),
    );
  }

  function sendVoice({ blob, filename }: Recorded) {
    const placeholder: Message = { from: "user", text: VOICE_PLACEHOLDER, buttons: [] };
    setMessages((m) => [...m, placeholder]);
    const form = new FormData();
    form.append("audio", blob, filename);
    void run(apiForm<Reply[]>("/chat/voice", form), (e) => {
      // Nothing was understood, so there is nothing to show of what was said.
      setMessages((m) => m.filter((x) => x !== placeholder));
      setNote({ kind: "error", text: voiceFailure(e) });
    });
  }

  const voice = useVoiceRecorder({
    onDone: sendVoice,
    onUnavailable: () => {
      setMicBlocked(true);
      setNote({ kind: "hint", text: NO_MIC_HINT });
    },
    onEmpty: () => setNote({ kind: "error", text: "Didn't catch anything — try again." }),
  });

  function startVoice() {
    if (busy) return;
    if (!micAvailable) {
      setNote({ kind: "hint", text: NO_MIC_HINT });
      return;
    }
    setNote(null);
    void voice.start();
  }

  // The tap that started a recording moves to the stop button; the input gets focus back after.
  const wasRecording = useRef(false);
  useEffect(() => {
    if (voice.recording) stopButton.current?.focus();
    else if (wasRecording.current) input.current?.focus();
    wasRecording.current = voice.recording;
  }, [voice.recording]);

  const asked = useRef(false);
  useEffect(() => {
    // Once, even when React runs effects twice in development.
    if (ask && !asked.current) {
      asked.current = true;
      say(ask);
    }
  }, [ask]);

  function send(event: FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    say(text);
  }

  function press(index: number, data: string, label: string) {
    // A button works once: clear this message's buttons, as Telegram does.
    setMessages((m) => [
      ...m.map((msg, i) => (i === index ? { ...msg, buttons: [] } : msg)),
      { from: "user" as const, text: label, buttons: [] },
    ]);
    void run(api<Reply[]>("/chat/press", { method: "POST", body: { data } }));
  }

  return (
    <aside
      className="drawer"
      role="dialog"
      aria-modal="false"
      aria-labelledby="chat-title"
    >
      <header>
        <h2 id="chat-title">Chat</h2>
        <button
          type="button"
          className="btn btn-ghost"
          aria-label="Close chat"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <div className="messages" aria-live="polite">
        {more && (
          <button
            type="button"
            className="btn btn-small earlier"
            onClick={() => void loadEarlier()}
          >
            Earlier messages
          </button>
        )}
        {messages.length === 0 && (
          <p className="muted">
            Try "coffee 5.50", "split dinner 90 with Ann and Ben" or "what did I
            spend on food?"
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`msg msg-${m.from}`}
            title={m.at ? WHEN.format(new Date(m.at)) : undefined}
          >
            {m.text}
            {m.telegram && <span className="msg-via">on Telegram</span>}
            {m.buttons.length > 0 && (
              <div className="choices">
                {m.buttons.flat().map((b) =>
                  b.data.startsWith("url:") ? (
                    <a
                      key={b.data}
                      className="btn btn-primary"
                      href={b.data.slice(4)}
                      target="_blank"
                      rel="noopener noreferrer"
                      onClick={(e) => {
                        e.preventDefault();
                        openExternal(b.data.slice(4));
                      }}
                    >
                      {b.label}
                    </a>
                  ) : (
                    <button
                      key={b.data}
                      type="button"
                      className="btn"
                      disabled={busy}
                      onClick={() => press(i, b.data, b.label)}
                    >
                      {b.label}
                    </button>
                  ),
                )}
              </div>
            )}
          </div>
        ))}
        {busy && <Typing />}
        <div ref={end} />
      </div>
      <form onSubmit={send}>
        {voice.recording && (
          <div className="chat-line chat-rec" role="status">
            <span className="chat-rec-dot" aria-hidden="true" />
            <span>Recording</span>
            <span className="chat-rec-time" aria-hidden="true">
              {clock(voice.seconds)}
            </span>
            <span className="muted chat-rec-max" aria-hidden="true">
              / {clock(MAX_VOICE_SECONDS)}
            </span>
          </div>
        )}
        {!voice.recording && note && (
          <p className={`chat-line ${note.kind === "error" ? "error-text" : "muted"}`} role={note.kind === "error" ? "alert" : "status"}>
            {note.text}
          </p>
        )}
        <label className="sr-only" htmlFor="chat-input">
          Message
        </label>
        <input
          id="chat-input"
          ref={input}
          className="input"
          value={draft}
          maxLength={2000}
          disabled={voice.recording}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Tell me what happened"
        />
        {voice.recording ? (
          <>
            <button type="button" className="btn btn-ghost chat-cancel" aria-label="Cancel recording" onClick={voice.cancel}>
              <Icon name="x" />
            </button>
            <button ref={stopButton} type="button" className="btn btn-primary chat-action" aria-label="Stop and send" onClick={voice.stop}>
              <Icon name="stop" />
            </button>
          </>
        ) : draft.trim() ? (
          <button type="submit" className="btn btn-primary chat-action" disabled={busy}>
            Send
          </button>
        ) : (
          <button
            type="button"
            className={`btn btn-primary chat-action${micAvailable ? "" : " chat-mic-off"}`}
            aria-label="Record a voice note"
            aria-disabled={busy || !micAvailable ? true : undefined}
            onClick={startVoice}
          >
            <Icon name="mic" />
          </button>
        )}
      </form>
    </aside>
  );
}
