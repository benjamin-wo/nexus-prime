import { describe, expect, it } from "vitest";

import type { VoiceDials, VoicePresetId } from "./api";
import { previewReplies } from "./voice";

const PRESETS: VoicePresetId[] = ["default", "chill", "direct", "hype", "cheeky"];
const dials = (over: Partial<VoiceDials> = {}): VoiceDials => ({ emoji: "some", length: "normal", humour: "light", ...over });
const EMOJI = /\p{Extended_Pictographic}/gu;
const count = (text: string) => text.match(EMOJI)?.length ?? 0;

describe("previewReplies", () => {
  it("gives three replies to the three things said", () => {
    const replies = previewReplies("default", dials());
    expect(replies.map((r) => r.said)).toEqual(["grab 12", "rent paid", "how's my food budget?"]);
    for (const r of replies) expect(r.text.length).toBeGreaterThan(10);
  });

  it("words each preset differently", () => {
    const first = PRESETS.map((p) => previewReplies(p, dials({ emoji: "none", humour: "light" }))[0].text);
    expect(new Set(first).size).toBe(PRESETS.length);
  });

  it("says the logged expense the way the brief describes, at each preset's own dials", () => {
    const at = (preset: VoicePresetId, d: VoiceDials) => previewReplies(preset, d)[0].text;
    expect(at("default", dials({ emoji: "some", humour: "off" }))).toBe("Grab 12.00 ✅ Transport's at 108.30 this month.");
    expect(at("direct", dials({ emoji: "none", length: "short", humour: "off" }))).toBe("Grab 12 logged.");
    expect(at("chill", dials({ emoji: "some" }))).toBe("done — grab 12 👍 transport's at 108 this month");
    expect(at("hype", dials({ emoji: "lots" }))).toBe("Logged! 🙌 Grab 12. Transport's sitting at 108, nicely under control 💪");
    expect(at("cheeky", dials({ emoji: "some" }))).toBe("Grab again? 😏 12 logged. Transport's at 108 this month.");
  });

  it("emoji none strips every emoji, for every preset, length and humour", () => {
    for (const preset of PRESETS) {
      for (const length of ["short", "normal", "detailed"] as const) {
        for (const humour of ["off", "light", "playful"] as const) {
          for (const r of previewReplies(preset, { emoji: "none", length, humour })) {
            expect(count(r.text), `${preset}/${length}/${humour}: ${r.text}`).toBe(0);
            expect(r.text).not.toMatch(/\s{2,}|\s[.,!]|,$/);
          }
        }
      }
    }
  });

  it("emoji some keeps one and lots keeps at least two", () => {
    for (const preset of PRESETS) {
      for (const r of previewReplies(preset, dials({ emoji: "some" }))) expect(count(r.text), r.text).toBe(1);
      for (const r of previewReplies(preset, dials({ emoji: "lots" }))) expect(count(r.text), r.text).toBeGreaterThanOrEqual(2);
    }
  });

  it("length short drops the second clause and detailed adds one", () => {
    for (const preset of PRESETS) {
      const [short, normal, detailed] = (["short", "normal", "detailed"] as const).map((length) =>
        previewReplies(preset, dials({ length, humour: "off", emoji: "none" })),
      );
      for (let i = 0; i < 3; i += 1) {
        expect(short[i].text.length, `${preset} ${i}`).toBeLessThan(normal[i].text.length);
        expect(detailed[i].text.length, `${preset} ${i}`).toBeGreaterThan(normal[i].text.length);
        expect(normal[i].text.startsWith(short[i].text.replace(/[.]$/, ""))).toBe(true);
        expect(detailed[i].text.startsWith(normal[i].text)).toBe(true);
      }
    }
    expect(previewReplies("default", dials({ length: "short", emoji: "none" }))[0].text).toBe("Grab 12.00.");
    expect(previewReplies("chill", dials({ length: "short", emoji: "none" }))[0].text).toBe("done — grab 12");
  });

  it("humour off drops the cheeky voice's joke, and playful adds a quip unless short", () => {
    expect(previewReplies("cheeky", dials({ humour: "off", emoji: "none" }))[0].text).toBe("Grab 12 logged. Transport's at 108 this month.");
    const normal = previewReplies("direct", dials({ humour: "light", emoji: "none" }))[0].text;
    expect(previewReplies("direct", dials({ humour: "playful", emoji: "none" }))[0].text).toBe(`${normal} Your wallet felt that.`);
    expect(previewReplies("direct", dials({ humour: "playful", emoji: "none", length: "short" }))[0].text).toBe("Grab 12 logged.");
  });
});
