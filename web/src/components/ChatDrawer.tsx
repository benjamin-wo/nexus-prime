import { type FormEvent, Fragment, Suspense, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, apiForm, ApiError, type ChatHistory, type Demo, type Reply } from "../api";
import {
  RECOVER_EVERY_MS,
  RECOVER_TRIES,
  repliesAfter,
  StreamInterrupted,
  StreamNotStarted,
  streamChat,
  type ChatStep,
} from "../chatStream";
import { messagesLeft } from "../demo";
import { lazyNamed } from "../lazyPage";
import { openExternal } from "../telegram";
import { orderViews, useViewsEnabled } from "../views/hooks";
import type { CardView } from "../views/types";
import { clock, MAX_VOICE_SECONDS, NO_MIC_HINT, canRecord, useVoiceRecorder, type Recorded } from "../useVoiceRecorder";
import { Icon } from "./Icon";
import { NexusMark } from "./NexusMark";
import { PHONE_QUERY, useMediaQuery } from "./overlay/breakpoints";
import { Overlay } from "./overlay/Overlay";
import { Button, ButtonLink, Chip, ChipGroup } from "./ui";

// The cards under a line are fetched when first needed: they bring their charts and figures with them.
const ViewCards = lazyNamed(() => import("../views/ViewCard"), "ViewCards");

type Message = {
  from: "user" | "bot";
  text: string;
  buttons: Reply["buttons"];
  telegram?: boolean;
  at?: string;
  /** The views shown with this line (ADR 0005). From the history they carry only kind, params and focus. */
  views?: CardView[];
  /** The line came from the history: its cards load as they are scrolled to. */
  stored?: boolean;
};

/** How the page behind the chat is told to open a card's page. */
export type OpenView = (path: string, how: { phone: boolean; scroll: number }) => void;

function fromHistory(history: ChatHistory): Message[] {
  return history.lines.map((line) => ({
    from: line.role === "user" ? "user" : "bot",
    text: line.text,
    buttons: [],
    telegram: line.channel === "telegram",
    at: line.at,
    views: line.views?.map((v) => ({ kind: v.kind, params: v.params, focus: v.focus })),
    stored: true,
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

/** What to try when the chat is empty. */
const SUGGESTIONS = [
  "How's my dining budget?",
  "Plan Saturday in Kyoto",
  "I spent 12.50 on lunch at Kopi Corner",
  "What moved in my portfolio today?",
];

// After this long, the typing bubble also says it's still going.
const STILL_WORKING_MS = 10_000;

type Button = { label: string; data: string };

/** The in-app path and query of a link to this web app (same origin), else null: those open in the app, not a new window. */
export function inAppPath(url: string): string | null {
  try {
    const u = new URL(url, window.location.origin);
    return u.origin === window.location.origin ? `${u.pathname}${u.search}${u.hash}` : null;
  } catch {
    return null;
  }
}
const isSource = (b: Button) => b.data.startsWith("src:");

/** The pages a web answer came from (`src:<https url>`): small link chips under the reply,
 * not big buttons. The label ends in an arrow; the chip draws its own, hidden from readers. */
function Sources({ buttons }: { buttons: Button[] }) {
  const sources = buttons.filter((b) => isSource(b) && b.data.startsWith("src:https://"));
  if (sources.length === 0) return null;
  return (
    <div className="msg-sources" role="group" aria-label="Sources">
      {sources.map((b) => {
        const url = b.data.slice(4);
        return (
          <a
            key={b.data}
            className="src-chip"
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => {
              e.preventDefault();
              openExternal(url);
            }}
          >
            {b.label.replace(/\s*↗$/, "")}
            <span aria-hidden="true">↗</span>
          </a>
        );
      })}
    </div>
  );
}

/** What Nexus is doing, as it goes: a spinner on the step running now, a check on those done. */
type Progress = { label: string; done: boolean };

/** Shown when the reply stream broke after the turn began: the turn goes on, its reply is fetched. */
const STILL_WORKING_NOTE = "Still working… the reply will appear here";

/** A step finished: the oldest one still running with that label is done. */
function finish(steps: Progress[], label: string): Progress[] {
  const at = steps.findIndex((s) => s.label === label && !s.done);
  return at === -1 ? steps : steps.map((s, i) => (i === at ? { ...s, done: true } : s));
}

/** Nexus's side of the chat while a turn runs, once it has said what it is doing. The list sits
 * inside the chat's polite live region, so a screen reader hears each step as it starts. */
function Steps({ steps }: { steps: Progress[] }) {
  return (
    <div className="msg msg-bot steps" role="status" aria-label="What Nexus is doing">
      <NexusMark size={28} className="msg-avatar" />
      <ul className="steps-list">
        {steps.map((step, i) => (
          <li key={i} className={step.done ? "step-done" : "step-running"}>
            <span className={step.done ? "step-check" : "step-spin"} aria-hidden="true">
              {step.done ? "✓" : ""}
            </span>
            <span>
              {step.label}
              {step.done ? <span className="sr-only"> (done)</span> : "…"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Nexus's side of the chat while a reply is worked out: three dots, then a word
 * that it's still going, so a slow reply never looks like nothing is happening. */
function Typing({ note }: { note?: string }) {
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
      <NexusMark size={28} className="msg-avatar" />
      <span className="typing-dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      {note ? (
        <span className="typing-note">{note}</span>
      ) : (
        long && <span className="typing-note">Still working on it…</span>
      )}
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
  demo,
  restoreScroll,
  onOpenView,
  onClose,
  onChanged,
}: {
  ask?: string; // a question asked on Home, sent as soon as the chat opens
  demo?: Demo | null; // in the public demo: how many messages are left
  restoreScroll?: number; // coming back from a card's page: the list scrolls to where it was
  onOpenView?: OpenView; // a card's Open; without it the chat navigates itself
  onClose: () => void;
  onChanged: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  // The views of the turn running now, as they arrive (before its replies).
  const [shown, setShown] = useState<CardView[]>([]);
  const viewsOn = useViewsEnabled();
  const list = useRef<HTMLDivElement>(null);
  const restoring = useRef(restoreScroll !== undefined);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  // What the running turn has done so far, Stop was pressed on it, and its stream broke (so its reply
  // is being waited for in the history).
  const [steps, setSteps] = useState<Progress[]>([]);
  const [stopping, setStopping] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [more, setMore] = useState(false);
  // The history has come back (or failed), so an empty chat really is empty.
  const [loaded, setLoaded] = useState(false);
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
  // Full screen on a phone (the CSS's 480px breakpoint): the grab bar and header drag the chat down to close.
  const phone = useMediaQuery(PHONE_QUERY);
  const navigate = useNavigate();
  const handle = useRef<HTMLDivElement>(null);
  // Whether the list is scrolled to the newest message, so it can stay there when the keyboard resizes it.
  const atEnd = useRef(true);
  // Keep to the newest message, except right after loading older ones.
  const stick = useRef(true);

  // Effects use braces so nothing is returned: React would call a returned value as a
  // cleanup, and newer browsers return a promise from scrollIntoView().
  useEffect(() => {
    if (stick.current && !restoring.current) end.current?.scrollIntoView?.({ block: "end" });
    stick.current = true;
  }, [messages]);
  // Back from a card's page: once the history is in, the list goes back to where it was.
  useEffect(() => {
    if (!loaded || !restoring.current) return;
    restoring.current = false;
    if (list.current) list.current.scrollTop = restoreScroll ?? 0;
  }, [loaded, restoreScroll]);
  useEffect(() => {
    if (busy) end.current?.scrollIntoView?.({ block: "end" });
  }, [busy]);
  // The keyboard opening or closing resizes the visible screen (and with it the drawer): stay on the
  // newest message if that is where the person was.
  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const onResize = () => {
      if (atEnd.current) end.current?.scrollIntoView?.({ block: "end" });
    };
    vv.addEventListener("resize", onResize);
    return () => vv.removeEventListener("resize", onResize);
  }, []);
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
      .catch(() => undefined) // the chat still works without its history
      .finally(() => {
        if (live) setLoaded(true);
      });
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
  async function run(call: Promise<Reply[]>, failed?: (e: unknown) => void) {
    setBusy(true);
    setShown([]);
    const streamed: CardView[] = [];
    streaming.current = streamed;
    try {
      const replies = await call;
      setMessages((m) => [
        ...m,
        ...replies.map((r, i) => ({
          from: "bot" as const,
          text: r.text,
          buttons: r.buttons,
          // The server puts a turn's views on its last reply; ones seen on the stream stand in if it sent none.
          views: r.views?.length ? r.views : i === replies.length - 1 && streamed.length ? streamed : undefined,
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
      setShown([]);
      setSteps([]);
      setStopping(false);
      setRecovering(false);
    }
  }

  // The views the running turn has shown, kept for the replies; `shown` is the same list for the screen.
  const streaming = useRef<CardView[]>([]);
  const onView = (view: CardView) => {
    streaming.current.push(view);
    setShown((now) => [...now, view]);
  };
  const onStep = (step: ChatStep) =>
    setSteps((now) => (step.state === "running" ? [...now, { label: step.label, done: false }] : finish(now, step.label)));

  /** Wait for the reply of a turn whose stream broke after it began: it keeps running and keeps its
   * replies in the history, so look there. The message is never sent again. */
  async function recover(text: string, since: number): Promise<Reply[]> {
    setRecovering(true);
    for (let i = 0; i < RECOVER_TRIES; i++) {
      await new Promise((resolve) => setTimeout(resolve, RECOVER_EVERY_MS));
      const history = await api<ChatHistory>("/chat/history").catch(() => null);
      const found = history && repliesAfter(history, text, since);
      if (found) return found;
    }
    return [{ text: "I'm still working on that. The reply will show in this chat when it's done.", buttons: [] }];
  }

  /** A typed message: followed live through the stream; sent the usual way only when the stream
   * could not start (so nothing was sent twice). */
  async function turn(text: string): Promise<Reply[]> {
    try {
      return await streamChat(text, onStep, onView);
    } catch (e) {
      if (e instanceof StreamNotStarted) return api<Reply[]>("/chat", { method: "POST", body: { message: text } });
      if (e instanceof StreamInterrupted) return recover(text, e.startedAt);
      throw e;
    }
  }

  function say(text: string) {
    setMessages((m) => [...m, { from: "user", text, buttons: [] }]);
    void run(turn(text));
  }

  /** Ask for the running turn to end at its next step; the stream goes on until its replies come. */
  function stop() {
    setStopping(true);
    void api("/chat/stop", { method: "POST" }).catch(() => undefined);
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

  /** A card's Open: the page behind the chat goes to the card's page. On a phone the chat closes (the page
   * offers a way back); on a wide screen it stays. */
  function openView(path: string) {
    if (onOpenView) onOpenView(path, { phone, scroll: list.current?.scrollTop ?? 0 });
    else {
      navigate(path);
      if (phone) onClose();
    }
  }

  // In the body, not in the page: the page's pull-to-refresh listens on (and slides) everything inside
  // it, and a drag in the chat must neither refresh the page nor move the chat.
  return (
    <Overlay shape="panel" modal={phone} className="drawer" labelledBy="chat-title" initialFocus="#chat-input" onClose={onClose} handle={handle}>
      <div ref={handle} className="overlay-handle">
      <span className="overlay-grab" aria-hidden="true" />
      <header>
        <h2 id="chat-title">Chat</h2>
        {demo && (
          <span className="caption" role="status">
            {messagesLeft(demo.messages_left)}
          </span>
        )}
        <Button
          variant="text"
          aria-label="Close chat"
          onClick={onClose}
        >
          ×
        </Button>
      </header>
      </div>
      <div
        ref={list}
        className="messages"
        aria-live="polite"
        onScroll={(e) => {
          const el = e.currentTarget;
          atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
      >
        {more && (
          <Button
            size="sm"
            className="earlier"
            onClick={() => void loadEarlier()}
          >
            Earlier messages
          </Button>
        )}
        {messages.length === 0 && (
          <p className="muted">
            Just ask Nexus. Try "coffee 5.50", "split dinner 90 with Ann and Ben" or "what did I
            spend on food?"
          </p>
        )}
        {messages.length === 0 && loaded && !busy && (
          <ChipGroup aria-label="Suggestions">
            {SUGGESTIONS.map((suggestion) => (
              <Chip key={suggestion} onClick={() => say(suggestion)}>
                {suggestion}
              </Chip>
            ))}
          </ChipGroup>
        )}
        {messages.map((m, i) => (
          <Fragment key={i}>
          <div
            className={`msg msg-${m.from}`}
            title={m.at ? WHEN.format(new Date(m.at)) : undefined}
          >
            {m.from === "bot" && <NexusMark size={28} className="msg-avatar" />}
            {m.text}
            {m.telegram && <span className="msg-via">on Telegram</span>}
            {m.buttons.length > 0 && (
              <>
                {m.buttons.flat().some((b) => !isSource(b)) && (
                <div className="choices">
                  {m.buttons.flat().filter((b) => !isSource(b)).map((b) =>
                    b.data.startsWith("url:") ? (
                      <ButtonLink
                        variant="primary"
                        key={b.data}
                        href={b.data.slice(4)}
                        target={inAppPath(b.data.slice(4)) === null ? "_blank" : undefined}
                        rel="noopener noreferrer"
                        onClick={(e) => {
                          e.preventDefault();
                          const path = inAppPath(b.data.slice(4));
                          if (path === null) openExternal(b.data.slice(4));
                          else {
                            navigate(path);
                            if (phone) onClose();
                          }
                        }}
                      >
                        {b.label}
                      </ButtonLink>
                    ) : (
                      <Button
                        key={b.data}
                        disabled={busy}
                        onClick={() => press(i, b.data, b.label)}
                      >
                        {b.label}
                      </Button>
                    ),
                  )}
                </div>
                )}
                <Sources buttons={m.buttons.flat()} />
              </>
            )}
          </div>
          {viewsOn && m.from === "bot" && m.views && m.views.length > 0 && (
            <Suspense fallback={null}>
              <ViewCards views={orderViews(m.views)} lazy={m.stored} onOpen={openView} />
            </Suspense>
          )}
          </Fragment>
        ))}
        {busy && viewsOn && shown.length > 0 && (
          <Suspense fallback={null}>
            <ViewCards views={orderViews(shown)} onOpen={openView} />
          </Suspense>
        )}
        {busy && (recovering ? <Typing note={STILL_WORKING_NOTE} /> : steps.length > 0 ? <Steps steps={steps} /> : <Typing />)}
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
            <Button variant="text" className="chat-cancel" aria-label="Cancel recording" onClick={voice.cancel}>
              <Icon name="x" />
            </Button>
            <Button variant="primary" className="chat-action" ref={stopButton} aria-label="Stop and send" onClick={voice.stop}>
              <Icon name="stop" />
            </Button>
          </>
        ) : busy ? (
          <Button variant="primary" className="chat-action" disabled={stopping} onClick={stop}>
            {stopping ? "Stopping…" : "Stop"}
          </Button>
        ) : draft.trim() ? (
          <Button variant="primary" className="chat-action" type="submit">
            Send
          </Button>
        ) : (
          <Button
            variant="primary"
            className={`chat-action${micAvailable ? "" : " chat-mic-off"}`}
            aria-label="Record a voice note"
            aria-disabled={busy || !micAvailable ? true : undefined}
            onClick={startVoice}
          >
            <Icon name="mic" />
          </Button>
        )}
      </form>
    </Overlay>
  );
}
