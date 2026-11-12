import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ChatHistory, Reply } from "./api";
import { ChatDrawer } from "./components/ChatDrawer";
import { renderWithProviders } from "./testing";

type Call = { method: string; path: string; body: unknown };

const frame = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

/** A live event stream the test writes to by hand. */
function openStream() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } }),
    send: (text: string) => act(async () => controller.enqueue(encoder.encode(text))),
    fail: () => act(async () => controller.error(new Error("connection reset"))),
  };
}

/** fetch for the chat: the stream, the plain endpoint, stop and the history, each by "METHOD /path". */
function chatApi(routes: Record<string, () => Response | Promise<Response>>): Call[] {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(String(input), "http://localhost");
    const method = init?.method ?? "GET";
    const path = url.pathname.replace(/^\/api/, "");
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (path === "/chat/history" && !routes["GET /chat/history"]) return json({ lines: [], more: false, pending: null });
    const route = routes[`${method} ${path}`];
    return route ? route() : json({ detail: "not mocked" }, 404);
  });
  return calls;
}

async function send(text: string) {
  const user = userEvent.setup(vi.isFakeTimers() ? { advanceTimers: vi.advanceTimersByTime.bind(vi) } : {});
  await user.type(screen.getByLabelText("Message"), text);
  await user.click(screen.getByRole("button", { name: "Send" }));
  return user;
}

afterEach(() => vi.useRealTimers());

describe("ChatDrawer streaming a typed message", () => {
  it("lists what Kaya is doing as it goes, then shows the replies", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const stream = openStream();
    const calls = chatApi({ "POST /chat/stream": () => stream.response });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    await send("lunch 12 and split with ann");

    const live = document.querySelector('[aria-live="polite"]') as HTMLElement;
    expect(await screen.findByRole("status", { name: "Kaya is typing" })).toBeInTheDocument();

    await stream.send(frame("step", { label: "Logging the expense", state: "running" }));
    const steps = await screen.findByRole("status", { name: "What Kaya is doing" });
    expect(live).toContainElement(steps); // inside the polite live region
    expect(within(steps).getByText("Logging the expense…")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Kaya is typing" })).not.toBeInTheDocument();
    expect(steps.querySelector(".step-spin")).not.toBeNull();

    await stream.send(frame("step", { label: "Logging the expense", state: "done" }));
    await stream.send(frame("step", { label: "Splitting the bill", state: "running" }));
    await waitFor(() => expect(within(steps).getByText("Splitting the bill…")).toBeInTheDocument());
    expect(steps.querySelectorAll(".step-check")).toHaveLength(1);
    expect(steps.querySelectorAll(".step-spin")).toHaveLength(1);

    const replies: Reply[] = [{ text: "Logged and split.", buttons: [[{ label: "Undo", data: "act:undo" }]] }];
    await stream.send(frame("step", { label: "Splitting the bill", state: "done" }) + frame("replies", replies));
    expect(await screen.findByText("Logged and split.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "What Kaya is doing" })).not.toBeInTheDocument();
    // Sent once, to the stream only.
    expect(calls.filter((c) => c.path.startsWith("/chat") && c.method === "POST").map((c) => c.path)).toEqual(["/chat/stream"]);
    expect(calls.find((c) => c.path === "/chat/stream")?.body).toEqual({ message: "lunch 12 and split with ann" });
  });

  it("swaps Send for a Stop button that asks the server to stop and keeps reading until the replies come", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const stream = openStream();
    const calls = chatApi({
      "POST /chat/stream": () => stream.response,
      "POST /chat/stop": () => new Response(null, { status: 204 }),
    });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = await send("research my whole trip");

    const stop = await screen.findByRole("button", { name: "Stop" });
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    await stream.send(frame("step", { label: "Researching the trip", state: "running" }));
    await user.click(stop);
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/chat/stop")).toBe(true));
    expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();

    // The turn ends at its next step; its replies arrive on the same stream.
    await stream.send(
      frame("step", { label: "Researching the trip", state: "done" }) +
        frame("replies", [{ text: "Stopped, as you asked. Nothing was changed.", buttons: [] }]),
    );
    expect(await screen.findByText("Stopped, as you asked. Nothing was changed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stop/ })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/chat/stream")).toHaveLength(1);
  });

  it("falls back to the usual request when the stream does not start, and sends the message once there", async () => {
    const calls = chatApi({
      "POST /chat/stream": () => json({ detail: "bad gateway" }, 502),
      "POST /chat": () => json([{ text: "Noted.", buttons: [] }]),
    });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    await send("hello");
    expect(await screen.findByText("Noted.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/chat/stream", "/chat"]);
  });

  it("falls back when the browser has no streaming", async () => {
    const noted = json([{ text: "Noted.", buttons: [] }]); // made before the browser "loses" streams
    const history = json({ lines: [], more: false, pending: null });
    const calls = chatApi({ "POST /chat": () => noted, "GET /chat/history": () => history });
    vi.stubGlobal("ReadableStream", undefined);
    try {
      renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
      await send("hello");
      expect(await screen.findByText("Noted.")).toBeInTheDocument();
      expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/chat"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("shows a refusal the server means without sending the message another way", async () => {
    const calls = chatApi({ "POST /chat/stream": () => json({ detail: "Too many at once. Try again in a few minutes." }, 429) });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    await send("hello");
    expect(await screen.findByText("Sorry: Too many at once. Try again in a few minutes.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/chat/stream"]);
  });

  it("shows the words of an error event", async () => {
    const stream = openStream();
    chatApi({ "POST /chat/stream": () => stream.response });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    await send("hello");
    await stream.send(frame("error", { detail: "Something went wrong on our side. Please try again." }));
    expect(await screen.findByText("Sorry: Something went wrong on our side. Please try again.")).toBeInTheDocument();
  });

  it("does not send the message again when the stream breaks mid-turn: it waits and reads the history", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const stream = openStream();
    let finished = false;
    const calls = chatApi({
      "POST /chat/stream": () => stream.response,
      "GET /chat/history": () =>
        json({
          lines: finished
            ? [
                { id: 1, role: "user", text: "plan my trip", channel: "web", at: new Date().toISOString() },
                { id: 2, role: "nexus", text: "Here is the plan.", channel: "web", at: new Date().toISOString() },
              ]
            : [],
          more: false,
          pending: null,
        } satisfies ChatHistory),
    });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    await send("plan my trip");
    await stream.send(frame("step", { label: "Researching the trip", state: "running" }));
    await stream.fail();

    expect(await screen.findByText("Still working… the reply will appear here")).toBeInTheDocument();
    // Not finished at the first look: it keeps waiting.
    await act(async () => void (await vi.advanceTimersByTimeAsync(3_000)));
    expect(screen.getByText("Still working… the reply will appear here")).toBeInTheDocument();
    finished = true;
    await act(async () => void (await vi.advanceTimersByTimeAsync(3_000)));
    expect(await screen.findByText("Here is the plan.")).toBeInTheDocument();
    expect(screen.queryByText("Still working… the reply will appear here")).not.toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/chat/stream"]);
  });
});
