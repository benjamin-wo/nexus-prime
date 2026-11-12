import type { VoiceDials, VoicePresetId } from "./api";

/** The three made-up exchanges the "How Nexus talks" card previews. Written here, in the browser:
 * no API call, so the preview follows every tap at once. */

/** An emoji that the Emoji dial may drop; `plain` is what stands in its place (usually a full stop). */
type Slot = { emoji: string; plain: string };
type Piece = string | Slot;

type Sample = {
  /** The clause every length keeps. */
  lead: Piece[];
  /** Used instead of `lead` when Humour is off, for a preset whose lead is a joke. */
  dryLead?: Piece[];
  /** The second clause: Short drops it. */
  detail: Piece[];
  /** What Detailed adds. */
  extra: string;
};

type Scenario = {
  /** What the person typed. */
  said: string;
  /** One more emoji for Lots when a preset's own text has fewer than two. */
  bonus: string;
  /** What Playful adds (unless Short). */
  quip: string;
  samples: Record<VoicePresetId, Sample>;
};

const e = (emoji: string, plain = ""): Slot => ({ emoji, plain });

const SCENARIOS: Scenario[] = [
  {
    said: "grab 12",
    bonus: "💸",
    quip: "Your wallet felt that.",
    samples: {
      default: {
        lead: ["Grab 12.00", e("✅", ".")],
        detail: ["Transport's at 108.30 this month."],
        extra: "That leaves 41.70 of your 150.00 transport budget.",
      },
      chill: {
        lead: ["done — grab 12", e("👍", ",")],
        detail: ["transport's at 108 this month"],
        extra: "so about 42 left in the transport budget.",
      },
      direct: {
        lead: ["Grab 12 logged.", e("✅")],
        detail: ["Transport: 108.30 this month."],
        extra: "41.70 left of 150.00.",
      },
      hype: {
        lead: ["Logged!", e("🙌"), "Grab 12."],
        detail: ["Transport's sitting at 108, nicely under control", e("💪", ".")],
        extra: "That's 42 still to play with this month.",
      },
      cheeky: {
        lead: ["Grab again?", e("😏"), "12 logged."],
        dryLead: ["Grab 12 logged.", e("✅")],
        detail: ["Transport's at 108 this month."],
        extra: "Still 42 left in the transport budget, no judgement.",
      },
    },
  },
  {
    said: "rent paid",
    bonus: "🏠",
    quip: "Your landlord is thrilled.",
    samples: {
      default: {
        lead: ["Rent logged: 1,800.00", e("🏠", ".")],
        detail: ["Housing is done for the month."],
        extra: "The next one is due on the 1st.",
      },
      chill: {
        lead: ["rent's sorted — 1,800", e("🏠", ",")],
        detail: ["that's housing done for the month"],
        extra: "next one's due on the 1st.",
      },
      direct: {
        lead: ["Rent 1,800.00 logged.", e("✅")],
        detail: ["Housing done for the month."],
        extra: "Next due on the 1st.",
      },
      hype: {
        lead: ["Rent's paid!", e("🎉"), "1,800 logged."],
        detail: ["Housing is done for the month", e("🏡", "!")],
        extra: "The next one is on the 1st.",
      },
      cheeky: {
        lead: ["Rent paid, 1,800. Look at you, adulting.", e("😎")],
        dryLead: ["Rent paid, 1,800.", e("✅")],
        detail: ["Housing's sorted for the month."],
        extra: "The next one is on the 1st, no pressure.",
      },
    },
  },
  {
    said: "how's my food budget?",
    bonus: "📊",
    quip: "Future you says thanks.",
    samples: {
      default: {
        lead: ["You've used 280.00 of your 400.00 food budget", e("🍜", ".")],
        detail: ["That leaves 120.00 for the last 8 days."],
        extra: "At this pace you'll finish about 23 under.",
      },
      chill: {
        lead: ["food's at 280 of 400", e("🍜", ",")],
        detail: ["so about 120 left for the last 8 days"],
        extra: "you're running a bit under pace, nice.",
      },
      direct: {
        lead: ["Food: 280.00 of 400.00.", e("📊")],
        detail: ["120.00 left, 8 days to go."],
        extra: "On pace to finish about 23 under.",
      },
      hype: {
        lead: ["Food's looking great!", e("🍜"), "280 of 400 used."],
        detail: ["120 left for the last 8 days, you've totally got this", e("🔥", "!")],
        extra: "At this pace you'll finish about 23 under.",
      },
      cheeky: {
        lead: ["Ah, the food budget.", e("😅"), "280 of 400 gone."],
        dryLead: ["Food: 280 of 400 used.", e("📊")],
        detail: ["120 left for the last 8 days."],
        extra: "At this pace you'll finish about 23 under, so the noodles can stay.",
      },
    },
  },
];

export type PreviewReply = { said: string; text: string };

/** Words for one sample: the dials decide which clauses and how many emoji. */
function compose(sample: Sample, scenario: Scenario, dials: VoiceDials): string {
  const { emoji, length, humour } = dials;
  const pieces: Piece[] = [...(humour === "off" && sample.dryLead ? sample.dryLead : sample.lead)];
  if (length !== "short") pieces.push(...sample.detail);
  let seen = 0;
  let text = "";
  for (const piece of pieces) {
    let part: string;
    if (typeof piece === "string") part = piece;
    else {
      // "Some" keeps the first emoji, "Lots" all of them, "None" none.
      const keep = emoji === "lots" || (emoji === "some" && seen === 0);
      if (keep) seen += 1;
      part = keep ? ` ${piece.emoji}` : piece.plain;
    }
    // Words are spaced apart; an emoji brings its own space and a full stop or comma none.
    text += part === "" || part.startsWith(" ") || /^[.,!]/.test(part) ? part : `${text ? " " : ""}${part}`;
  }
  // A short reply that ends on a comma (the chill voice's run-on) just stops.
  text = text.trim().replace(/,$/, "");
  const more: string[] = [];
  if (length === "detailed") more.push(sample.extra);
  if (humour === "playful" && length !== "short") more.push(scenario.quip);
  let out = [text, ...more].join(" ");
  // Lots with little of its own: one more at the end.
  if (emoji === "lots" && seen < 2) out += ` ${scenario.bonus}`;
  return out;
}

/** The three sample replies for a voice: what Nexus would say with this preset and these dials. */
export function previewReplies(preset: VoicePresetId, dials: VoiceDials): PreviewReply[] {
  return SCENARIOS.map((scenario) => ({ said: scenario.said, text: compose(scenario.samples[preset], scenario, dials) }));
}
