import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, type ChatHistory } from "./api";
import { repliesAfter, SseParser, streamChat, StreamInterrupted, StreamNotStarted, type ChatStep } from "./chatStream";

describe("SseParser", () => {
  it("reads whole frames", () => {
    const frames = new SseParser().push('event: step\ndata: {"label":"A","state":"running"}\n\nevent: replies\ndata: []\n\n');
    expect(frames).toEqual([
      { event: "step", data: '{"label":"A","state":"running"}' },
      { event: "replies", data: "[]" },
    ]);
  });

  it("waits for the rest of a frame that arrives in pieces", () => {
    const parser = new SseParser();
    expect(parser.push("event: ste")).toEqual([]);
    expect(parser.push("p\ndata: 1")).toEqual([]);
    expect(parser.push("\n")).toEqual([]);
    expect(parser.push("\nevent: replies\ndata: 2\n\n")).toEqual([
      { event: "step", data: "1" },
      { event: "replies", data: "2" },
    ]);
  });

  it("skips comments and frames with no data, and takes any line ending", () => {
    const frames = new SseParser().push(": open\r\n\r\nevent: step\r\ndata: x\r\n\r\n: keep-alive\n\nevent: empty\n\n");
    expect(frames).toEqual([{ event: "step", data: "x" }]);
  });

  it("joins several data lines and defaults the event name", () => {
    expect(new SseParser().push("data: a\ndata: b\n\n")).toEqual([{ event: "message", data: "a\nb" }]);
  });
});

function sseBody() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    send: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
    fail: () => controller.error(new Error("connection reset")),
  };
}

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

afterEach(() => vi.unstubAllGlobals());

describe("streamChat", () => {
  it("reports each step as it arrives and resolves with the replies", async () => {
    const stream = sseBody();
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(stream.response);
    const steps: ChatStep[] = [];
    const done = streamChat("coffee 5", (s) => steps.push(s));
    stream.send(": open\n\n" + frame("step", { label: "Logging the expense", state: "running" }));
    await vi.waitFor(() => expect(steps).toHaveLength(1));
    stream.send(frame("step", { label: "Logging the expense", state: "done" }));
    stream.send(frame("replies", [{ text: "Logged.", buttons: [] }]));
    expect(await done).toEqual([{ text: "Logged.", buttons: [] }]);
    expect(steps.map((s) => s.state)).toEqual(["running", "done"]);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/chat/stream");
    expect(init).toMatchObject({ method: "POST", credentials: "same-origin", body: '{"message":"coffee 5"}' });
    expect((init?.headers as Record<string, string>)["X-CSRF-Token"]).toBeDefined();
  });

  it("is not started when the network fails or the proxy answers with an error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(streamChat("hi", () => {})).rejects.toBeInstanceOf(StreamNotStarted);

    for (const status of [404, 502, 504]) {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status }));
      await expect(streamChat("hi", () => {})).rejects.toBeInstanceOf(StreamNotStarted);
    }

    // 200, but not a stream (a proxy's page).
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>", { status: 200, headers: { "Content-Type": "text/html" } }));
    await expect(streamChat("hi", () => {})).rejects.toBeInstanceOf(StreamNotStarted);

  });

  it("does not even ask when the browser cannot stream", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    vi.stubGlobal("ReadableStream", undefined);
    await expect(streamChat("hi", () => {})).rejects.toBeInstanceOf(StreamNotStarted);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows a refusal the server means instead of trying another way", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Too many at once." }), { status: 429, headers: { "Content-Type": "application/json" } }),
    );
    const error = await streamChat("hi", () => {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, message: "Too many at once." });
  });

  it("raises the error event's words as an ApiError", async () => {
    const stream = sseBody();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(stream.response);
    const done = streamChat("hi", () => {});
    stream.send(frame("error", { detail: "Something went wrong on our side. Please try again." }));
    await expect(done).rejects.toMatchObject({ message: "Something went wrong on our side. Please try again." });
  });

  it("is interrupted, not not-started, when the stream breaks after it began", async () => {
    const broken = sseBody();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(broken.response);
    const first = streamChat("hi", () => {});
    broken.send(frame("step", { label: "Working on it", state: "running" }));
    broken.fail();
    await expect(first).rejects.toBeInstanceOf(StreamInterrupted);

    const ended = sseBody();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(ended.response);
    const second = streamChat("hi", () => {});
    ended.end(); // closed with no replies
    await expect(second).rejects.toBeInstanceOf(StreamInterrupted);
  });
});

describe("repliesAfter", () => {
  const at = "2026-09-28T02:00:00Z";
  const since = Date.parse(at);
  const history = (lines: ChatHistory["lines"], pending: ChatHistory["pending"] = null): ChatHistory => ({ lines, more: false, pending });

  it("finds Kaya's replies once the turn's lines are in the history", () => {
    const lines: ChatHistory["lines"] = [
      { id: 1, role: "user", text: "hi", channel: "web", at: "2026-09-27T01:00:00Z" },
      { id: 2, role: "nexus", text: "Hello.", channel: "web", at: "2026-09-27T01:00:01Z" },
    ];
    // Only the earlier turn is there: this one has not finished.
    expect(repliesAfter(history(lines), "hi", since)).toBeNull();
    lines.push(
      { id: 3, role: "user", text: "hi", channel: "web", at },
      { id: 4, role: "nexus", text: "Hello again.", channel: "web", at },
    );
    expect(repliesAfter(history(lines), "hi", since)).toEqual([{ text: "Hello again.", buttons: [] }]);
  });

  it("gives a waiting confirmation its buttons", () => {
    const pending = { text: "Delete it?", buttons: [[{ label: "Confirm", data: "hitl:a:y" }]] };
    const lines: ChatHistory["lines"] = [
      { id: 3, role: "user", text: "delete it", channel: "web", at },
      { id: 4, role: "nexus", text: "Delete it?", channel: "web", at },
    ];
    expect(repliesAfter(history(lines, pending), "delete it", since)).toEqual([pending]);
  });
});
