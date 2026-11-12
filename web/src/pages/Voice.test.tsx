import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { VoicePreset, VoiceSettings } from "../api";
import { mockApi, renderWithProviders } from "../testing";
import { VoiceCard } from "./Voice";

const presets: VoicePreset[] = [
  { id: "default", label: "Default", blurb: "Clear and friendly.", emoji: "some", length: "normal", humour: "off" },
  { id: "chill", label: "Chill friend", blurb: "Relaxed.", emoji: "some", length: "normal", humour: "light" },
  { id: "direct", label: "Straight to the point", blurb: "Just the facts.", emoji: "none", length: "short", humour: "off" },
  { id: "hype", label: "Hype", blurb: "Big energy.", emoji: "lots", length: "normal", humour: "light" },
  { id: "cheeky", label: "Cheeky", blurb: "A little teasing.", emoji: "some", length: "normal", humour: "light" },
];
const voice = (over: Partial<VoiceSettings> = {}): VoiceSettings => ({ preset: "default", emoji: "some", length: "normal", humour: "off", note: null, presets, ...over });

/** A PUT handler that behaves like the server: a new preset takes its dials, dials and note are kept. */
function server(start: VoiceSettings) {
  let now = start;
  return (body: unknown) => {
    const b = body as Record<string, string>;
    const preset = presets.find((p) => p.id === b.preset);
    now = { ...now, ...(preset ? { preset: preset.id, emoji: preset.emoji, length: preset.length, humour: preset.humour } : {}) };
    for (const k of ["emoji", "length", "humour"]) if (b[k]) now = { ...now, [k]: b[k] };
    if (b.note !== undefined) now = { ...now, note: b.note === "" ? null : b.note };
    return now;
  };
}

const card = () => screen.getByRole("region", { name: "How Nexus talks" });
const pressed = (name: RegExp | string) => screen.getByRole("button", { name, pressed: true });
const replies = () => screen.getAllByTestId("voice-reply").map((el) => el.textContent);

describe("VoiceCard", () => {
  it("renders the current settings: the vibe, the dials, the note and a preview", async () => {
    mockApi({ "GET /settings/voice": () => voice({ preset: "direct", emoji: "none", length: "short", humour: "off", note: "call me boss" }) });
    renderWithProviders(<VoiceCard />);
    expect(screen.getByText("Pick a vibe, then fine-tune. Only changes wording — never what Nexus can do.")).toBeInTheDocument();
    const buttons = within(await screen.findByRole("group", { name: "Vibe" })).getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      "DefaultClear and friendly.",
      "Chill friendRelaxed.",
      "Straight to the pointJust the facts.",
      "HypeBig energy.",
      "CheekyA little teasing.",
    ]);
    expect(pressed(/^Straight to the point/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { pressed: true })).toHaveLength(4);
    expect(pressed("None")).toBeInTheDocument();
    expect(pressed("Short")).toBeInTheDocument();
    expect(pressed("Off")).toBeInTheDocument();
    expect(screen.getByLabelText("Anything else?")).toHaveValue("call me boss");
    expect(screen.getByTestId("voice-note-count")).toHaveTextContent("12/200");
    expect(replies()[0]).toBe("Grab 12 logged.");
    expect(card()).toHaveTextContent("Your note applies in chat");
  });

  it("changing the vibe PUTs it, shows it at once and takes the preset's dials", async () => {
    const calls = mockApi({ "GET /settings/voice": () => voice(), "PUT /settings/voice": server(voice()) });
    renderWithProviders(<VoiceCard />);
    await userEvent.click(await screen.findByRole("button", { name: /^Hype/ }));
    // Optimistic: pressed and previewed before the server has answered.
    expect(pressed(/^Hype/)).toBeInTheDocument();
    expect(pressed("Lots")).toBeInTheDocument();
    expect(replies()[0]).toContain("Logged! 🙌");
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT")).toEqual([{ method: "PUT", path: "/settings/voice", body: { preset: "hype" } }]));
    expect(pressed(/^Hype/)).toBeInTheDocument();
  });

  it("changing a dial PUTs only that dial and the preview follows", async () => {
    const calls = mockApi({ "GET /settings/voice": () => voice(), "PUT /settings/voice": server(voice()) });
    renderWithProviders(<VoiceCard />);
    await screen.findByRole("button", { name: /^Default/ });
    expect(replies()[0]).toBe("Grab 12.00 ✅ Transport's at 108.30 this month.");
    await userEvent.click(screen.getByRole("button", { name: "None" }));
    expect(replies()[0]).toBe("Grab 12.00. Transport's at 108.30 this month.");
    await userEvent.click(screen.getByRole("button", { name: "Short" }));
    expect(replies()[0]).toBe("Grab 12.00.");
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ emoji: "none" }, { length: "short" }]));
  });

  it("puts the screen back and says so when a change is refused", async () => {
    mockApi({
      "GET /settings/voice": () => voice(),
      "PUT /settings/voice": () => new Response(JSON.stringify({ detail: "Try again in a minute" }), { status: 429 }),
    });
    renderWithProviders(<VoiceCard />);
    await userEvent.click(await screen.findByRole("button", { name: /^Cheeky/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Try again in a minute");
    expect(pressed(/^Default/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Cheeky/, pressed: false })).toBeInTheDocument();
  });

  it("counts the note as it is typed, stops at 200 and saves on Enter", async () => {
    const calls = mockApi({ "GET /settings/voice": () => voice(), "PUT /settings/voice": server(voice()) });
    renderWithProviders(<VoiceCard />);
    const input = await screen.findByLabelText("Anything else?");
    expect(input).toHaveAttribute("placeholder", "e.g. call me boss, no exclamation marks");
    expect(screen.getByTestId("voice-note-count")).toHaveTextContent("0/200");
    await userEvent.type(input, "call me boss");
    expect(screen.getByTestId("voice-note-count")).toHaveTextContent("12/200");
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
    await userEvent.type(input, "{Enter}");
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ note: "call me boss" }]));
    expect(input).toHaveValue("call me boss");
    expect(input).toHaveAttribute("maxlength", "200");
    await userEvent.clear(input);
    await userEvent.paste("x".repeat(250));
    expect(screen.getByTestId("voice-note-count")).toHaveTextContent("200/200");
  });

  it("saves the note when the field is left, clears it with an empty one, and sends nothing when unchanged", async () => {
    const calls = mockApi({ "GET /settings/voice": () => voice({ note: "boss" }), "PUT /settings/voice": server(voice({ note: "boss" })) });
    renderWithProviders(<VoiceCard />);
    const input = await screen.findByLabelText("Anything else?");
    await userEvent.click(input);
    await userEvent.tab();
    expect(calls.filter((c) => c.method === "PUT")).toHaveLength(0);
    await userEvent.clear(input);
    await userEvent.tab();
    await waitFor(() => expect(calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ note: "" }]));
    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("says when it can't load", async () => {
    mockApi({});
    renderWithProviders(<VoiceCard />);
    expect(await screen.findByText("Couldn't load how Nexus talks.")).toBeInTheDocument();
  });
});
