// A typed chat message sent to POST /api/chat/stream, read as server-sent events: what Kaya is
// doing while the turn runs ("step" events), then the replies, exactly as POST /api/chat gives them.
// EventSource can't POST or send the CSRF header, so this reads the response body by hand.

import { ApiError, csrfHeader, type ChatHistory, type Reply } from "./api";

export type ChatStep = { label: string; state: "running" | "done" };

/** One server-sent event: its name and its `data` lines joined by newlines. */
export type SseFrame = { event: string; data: string };

/** Reads server-sent events from text that arrives in pieces. Comment lines (starting with ":")
 * are skipped; so is a frame with no data. */
export class SseParser {
  private buffer = "";

  push(text: string): SseFrame[] {
    this.buffer += text;
    const frames: SseFrame[] = [];
    // A frame ends at a blank line; the line ending may be \n, \r\n or \r.
    for (;;) {
      const end = /\r\n\r\n|\n\n|\r\r/.exec(this.buffer);
      if (!end) break;
      const block = this.buffer.slice(0, end.index);
      this.buffer = this.buffer.slice(end.index + end[0].length);
      const frame = parseBlock(block);
      if (frame) frames.push(frame);
    }
    return frames;
  }
}

function parseBlock(block: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r\n|\n|\r/)) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length === 0 ? null : { event, data: data.join("\n") };
}

/** The stream never started: nothing was sent that the server acted on, so the message may be sent
 * the usual way (POST /api/chat) instead. */
export class StreamNotStarted extends Error {}

/** The stream started (so the server is running the turn) and then broke before the replies came.
 * The message must not be sent again: its replies will be in the chat history. `startedAt` is when
 * the server began, in ms, as best the response says. */
export class StreamInterrupted extends Error {
  constructor(public startedAt: number) {
    super("The reply stream broke");
  }
}

// Refusals the server means: sending the message the usual way would only get the same answer.
// Anything else that isn't a success (404 from a proxy that doesn't know the path, 502, 504...) falls back.
const definitive = (status: number) => status >= 400 && status < 500 && ![404, 405, 408].includes(status);

async function refusal(response: Response): Promise<ApiError> {
  const data: unknown = await response.json().catch(() => null);
  const detail = (data as { detail?: unknown } | null)?.detail;
  return new ApiError(response.status, typeof detail === "string" ? detail : response.statusText);
}

/** Send `message` and follow the turn. Calls `onStep` as Kaya works and resolves with the replies.
 * Rejects with StreamNotStarted (send it the usual way), StreamInterrupted (do not send it again;
 * look in the chat history), or an ApiError (the server refused, or the turn failed: show it). */
export async function streamChat(message: string, onStep: (step: ChatStep) => void): Promise<Reply[]> {
  if (typeof ReadableStream === "undefined") throw new StreamNotStarted();
  let response: Response;
  try {
    response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...csrfHeader() },
      credentials: "same-origin",
      body: JSON.stringify({ message }),
    });
  } catch {
    throw new StreamNotStarted();
  }
  if (!response.ok) {
    if (definitive(response.status)) throw await refusal(response);
    throw new StreamNotStarted();
  }
  const streaming = (response.headers.get("Content-Type") ?? "").startsWith("text/event-stream");
  if (!streaming || !response.body) {
    // Some other answer in place of the stream (a proxy's page): the turn did not start.
    await response.body?.cancel().catch(() => undefined);
    throw new StreamNotStarted();
  }

  // From here the server is running the turn.
  const started = Date.parse(response.headers.get("Date") ?? "") || Date.now();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
        const data: unknown = JSON.parse(frame.data);
        if (frame.event === "step") onStep(data as ChatStep);
        else if (frame.event === "replies") return data as Reply[];
        else if (frame.event === "error") {
          const detail = (data as { detail?: unknown }).detail;
          throw new ApiError(0, typeof detail === "string" ? detail : "Something went wrong");
        }
      }
    }
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new StreamInterrupted(started);
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  throw new StreamInterrupted(started);
}

/** How the chat waits for a turn whose stream broke: look at the history this often, this many times. */
export const RECOVER_EVERY_MS = 3_000;
export const RECOVER_TRIES = 40;

/** Kaya's replies to `message` in the chat history, if the turn that began at `since` has finished
 * (the history keeps a turn's lines together when it ends); else null. */
export function repliesAfter(history: ChatHistory, message: string, since: number): Reply[] | null {
  const lines = history.lines;
  // The newest line of the person's that says this, sent after the turn began (a little slack for clocks).
  let at = -1;
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i];
    if (line.role === "user" && line.text === message && Date.parse(line.at) >= since - 120_000) {
      at = i;
      break;
    }
  }
  if (at === -1) return null;
  const replies = lines.slice(at + 1).filter((l) => l.role === "nexus");
  if (replies.length === 0) return null;
  const out: Reply[] = replies.map((l) => ({ text: l.text, buttons: [] }));
  // A confirmation still waiting is the last reply's, with its buttons.
  const last = out[out.length - 1];
  if (history.pending && history.pending.text === last.text) last.buttons = history.pending.buttons;
  return out;
}
