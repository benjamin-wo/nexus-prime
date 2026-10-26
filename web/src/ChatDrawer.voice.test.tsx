import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatDrawer } from "./components/ChatDrawer";
import { mockApi, renderWithProviders } from "./testing";

// A stand-in for the browser's recorder: start() begins, stop() hands over one chunk then stops.
class FakeRecorder {
  static types = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
  static isTypeSupported(type: string) {
    return FakeRecorder.types.includes(type);
  }
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(
    public stream: MediaStream,
    options?: { mimeType?: string },
  ) {
    this.mimeType = options?.mimeType ?? "";
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["voice"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

const track = { stop: vi.fn() };
const stream = { getTracks: () => [track] } as unknown as MediaStream;

function mic(getUserMedia: () => Promise<MediaStream> = async () => stream) {
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: vi.fn(getUserMedia) }, configurable: true });
}

beforeEach(() => {
  track.stop.mockClear();
  FakeRecorder.types = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  Reflect.deleteProperty(navigator, "mediaDevices");
});

const CONFIRM = [{ text: "Delete Grab 12.00?", buttons: [[{ label: "Confirm", data: "hitl:abc:y" }]] }];

describe("ChatDrawer voice notes", () => {
  it("shows the mic when the input is empty and Send once there is text", async () => {
    mic();
    mockApi({ "GET /chat/history": () => ({ lines: [], more: false, pending: null }) });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    expect(screen.getByRole("button", { name: "Record a voice note" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Message"), "hi");
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record a voice note" })).not.toBeInTheDocument();
  });

  it("records, counts the seconds, and sends the note as a webm upload", async () => {
    mic();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = mockApi({ "POST /chat/voice": () => CONFIRM });
    const onChanged = vi.fn();
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={onChanged} />);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    expect(await screen.findByRole("button", { name: "Stop and send" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel recording" })).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toBeDisabled();
    expect(screen.getByText("0:00")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(3200));
    expect(screen.getByText("0:03")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stop and send" }));

    expect(await screen.findByText("Delete Grab 12.00?")).toBeInTheDocument();
    expect(screen.getByText("🎙 Voice note…")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Confirm" })).toBeInTheDocument();
    const sent = calls.filter((c) => c.path === "/chat/voice");
    expect(sent).toHaveLength(1);
    const audio = (sent[0].body as FormData).get("audio") as File;
    expect(audio.name).toBe("voice.webm");
    expect(audio.type).toBe("audio/webm;codecs=opus");
    expect(audio.size).toBeGreaterThan(0);
    expect(track.stop).toHaveBeenCalled(); // the mic is let go
    expect(screen.getByLabelText("Message")).toBeEnabled();
    expect(onChanged).toHaveBeenCalled();
  });

  it("names the file voice.m4a when mp4 is all the browser has", async () => {
    FakeRecorder.types = ["audio/mp4"];
    mic();
    const calls = mockApi({ "POST /chat/voice": () => CONFIRM });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop and send" }));
    await screen.findByText("Delete Grab 12.00?");
    expect(((calls.find((c) => c.path === "/chat/voice")?.body as FormData).get("audio") as File).name).toBe("voice.m4a");
  });

  it("uses ogg when webm is not supported", async () => {
    FakeRecorder.types = ["audio/ogg;codecs=opus", "audio/mp4"];
    mic();
    const calls = mockApi({ "POST /chat/voice": () => CONFIRM });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop and send" }));
    await screen.findByText("Delete Grab 12.00?");
    expect(((calls.find((c) => c.path === "/chat/voice")?.body as FormData).get("audio") as File).name).toBe("voice.ogg");
  });

  it("throws the note away on cancel, and lets the mic go", async () => {
    mic();
    const calls = mockApi({ "POST /chat/voice": () => CONFIRM });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Cancel recording" }));
    expect(await screen.findByRole("button", { name: "Record a voice note" })).toBeInTheDocument();
    expect(track.stop).toHaveBeenCalled();
    expect(calls.filter((c) => c.path === "/chat/voice")).toHaveLength(0);
    expect(screen.queryByText("🎙 Voice note…")).not.toBeInTheDocument();
  });

  it("stops and sends by itself at two minutes", async () => {
    mic();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const calls = mockApi({ "POST /chat/voice": () => CONFIRM });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await screen.findByRole("button", { name: "Stop and send" });
    act(() => vi.advanceTimersByTime(119_000));
    expect(calls.filter((c) => c.path === "/chat/voice")).toHaveLength(0);
    act(() => vi.advanceTimersByTime(1_500));
    expect(await screen.findByText("Delete Grab 12.00?")).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/chat/voice")).toHaveLength(1);
  });

  it("says why when the server refuses the note, and drops the placeholder", async () => {
    mic();
    mockApi({
      "POST /chat/voice": () =>
        new Response(JSON.stringify({ detail: "That's too long — keep voice notes under 2 minutes." }), { status: 413 }),
    });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop and send" }));
    expect(await screen.findByText("That's too long — keep voice notes under 2 minutes.")).toBeInTheDocument();
    expect(screen.queryByText("🎙 Voice note…")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record a voice note" })).toBeEnabled();
  });

  it("falls back to a plain line when the refusal has no words", async () => {
    mic();
    mockApi({ "POST /chat/voice": () => new Response("", { status: 503 }) });
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    await user.click(await screen.findByRole("button", { name: "Stop and send" }));
    expect(await screen.findByText(/Voice notes aren't available right now/)).toBeInTheDocument();
  });

  it("explains once, and offers no more, when the mic permission is denied", async () => {
    mic(() => Promise.reject(new DOMException("denied", "NotAllowedError")));
    const calls = mockApi({});
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Record a voice note" }));
    expect(await screen.findByText("Mic isn't available here — send a voice note in the Telegram chat instead.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record a voice note" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("button", { name: "Stop and send" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/chat/voice")).toHaveLength(0);
  });

  it.each([
    ["no getUserMedia", () => vi.stubGlobal("MediaRecorder", FakeRecorder)],
    [
      "no MediaRecorder",
      () => Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia: async () => stream }, configurable: true }),
    ],
  ])("shows a disabled mic and the hint when the browser has %s", async (_name, setup) => {
    setup();
    mockApi({});
    renderWithProviders(<ChatDrawer onClose={() => {}} onChanged={() => {}} />);
    const user = userEvent.setup();
    const button = screen.getByRole("button", { name: "Record a voice note" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByText(/Mic isn't available here/)).not.toBeInTheDocument();
    await user.click(button);
    expect(screen.getByText("Mic isn't available here — send a voice note in the Telegram chat instead.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop and send" })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
  });
});
