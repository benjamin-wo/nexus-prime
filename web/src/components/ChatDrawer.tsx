import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, type Reply } from "../api";
import { openExternal } from "../telegram";

type Message = { from: "user" | "bot"; text: string; buttons: Reply["buttons"] };

/** The same agent and conversation as Telegram, with the same confirmation buttons. */
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
  const input = useRef<HTMLInputElement>(null);
  const end = useRef<HTMLDivElement>(null);

  // Effects use braces so nothing is returned: React would call a returned value as a
  // cleanup, and newer browsers return a promise from scrollIntoView().
  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function run(call: Promise<Reply[]>) {
    setBusy(true);
    try {
      const replies = await call;
      setMessages((m) => [...m, ...replies.map((r) => ({ from: "bot" as const, text: r.text, buttons: r.buttons }))]);
      onChanged();
    } catch (e) {
      const text = e instanceof Error ? e.message : "Something went wrong";
      setMessages((m) => [...m, { from: "bot", text: `Sorry: ${text}`, buttons: [] }]);
    } finally {
      setBusy(false);
    }
  }

  function say(text: string) {
    setMessages((m) => [...m, { from: "user", text, buttons: [] }]);
    void run(api<Reply[]>("/chat", { method: "POST", body: { message: text } }));
  }

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
    <aside className="drawer" role="dialog" aria-modal="false" aria-labelledby="chat-title">
      <header>
        <h2 id="chat-title">Chat</h2>
        <button type="button" className="btn btn-ghost" aria-label="Close chat" onClick={onClose}>
          ×
        </button>
      </header>
      <div className="messages" aria-live="polite">
        {messages.length === 0 && (
          <p className="muted">Try "coffee 5.50", "split dinner 90 with Ann and Ben" or "what did I spend on food?"</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg msg-${m.from}`}>
            {m.text}
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
                    <button key={b.data} type="button" className="btn" disabled={busy} onClick={() => press(i, b.data, b.label)}>
                      {b.label}
                    </button>
                  ),
                )}
              </div>
            )}
          </div>
        ))}
        {busy && <p className="muted">Thinking…</p>}
        <div ref={end} />
      </div>
      <form onSubmit={send}>
        <label className="sr-only" htmlFor="chat-input">
          Message
        </label>
        <input
          id="chat-input"
          ref={input}
          className="input"
          value={draft}
          maxLength={2000}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Tell me what happened"
        />
        <button type="submit" className="btn btn-primary" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}
