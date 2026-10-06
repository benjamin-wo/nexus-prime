import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, type ChatHistory, type Reply } from "../api";
import { openExternal } from "../telegram";

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
  const input = useRef<HTMLInputElement>(null);
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

  async function run(call: Promise<Reply[]>) {
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
        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || !draft.trim()}
        >
          Send
        </button>
      </form>
    </aside>
  );
}
