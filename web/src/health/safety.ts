import type { SafetyNote } from "./bodyApi";

/** The reason codes the API sends in `safety.gates`, as plain sentences. The one place they are worded. */
export const REASON_TEXT: Record<string, string> = {
  ok: "",
  under_18: "Weight-loss goals aren't available under 18.",
  low_bmi: "Weight-loss goals aren't available when BMI is below 18.5.",
  ed_history: "A weight-loss goal is off because you told us about an eating-disorder history.",
  ed_overridden: "You confirmed a weight-loss goal despite an eating-disorder history.",
  age_unknown: "Add your birth year to set a weight-loss goal.",
  bmi_unknown: "Add your height and a weigh-in to set a weight-loss goal.",
  rate_defaulted: "The weekly rate was set to a standard one.",
  rate_raised_to_minimum: "The weekly rate was raised to the smallest one that shows a change.",
  rate_hard_cap: "The weekly rate was lowered to the most Nexus will set.",
  rate_lean_limit: "The weekly rate was lowered to suit your build.",
  rate_not_applicable: "A weekly rate doesn't apply to this goal.",
  rate_slowed_for_floor: "The weekly rate was slowed so the daily target stays above its minimum.",
  floor_applied: "The daily target was raised to its minimum.",
  protein_raised: "The protein target was raised to its minimum.",
  protein_lowered: "The protein target was lowered to its maximum.",
  suspended_ed_signal: "Calorie targets are paused.",
  suspended_numbers_free: "Calorie targets are off while numbers are hidden.",
  suspended_ed_history: "Calorie targets are off because of the history you told us about.",
};

export const reasonText = (code: string): string => REASON_TEXT[code] ?? "";

/** The link for a signpost's contact: an email, or the first number as a phone call. Anything else has none. */
export function contactHref(contact: string): string | null {
  const first = contact.split(",")[0].trim();
  if (/^\S+@\S+\.\S+$/.test(first)) return `mailto:${first}`;
  const digits = first.replace(/\s+/g, "");
  return /^\+?\d{3,}$/.test(digits) ? `tel:${digits}` : null;
}

/** Whether a read asks for the soft check-in (a signal was first seen by it). */
export const wantsCheckIn = (s: SafetyNote | undefined): s is SafetyNote => !!s && (s.new_signals.length > 0 || !!s.check_in);

const SEEN = "nexus-health-checkin-seen";
const seenNow = new Set<string>();

/** The check-in is shown once for these signals on this day; the key says which. */
export const checkInKey = (s: SafetyNote, day: string): string => `${day}:${[...s.new_signals].sort().join(",")}`;

export function checkInSeen(key: string): boolean {
  if (seenNow.has(key)) return true;
  try {
    return (JSON.parse(window.localStorage.getItem(SEEN) ?? "[]") as string[]).includes(key);
  } catch {
    return false;
  }
}

export function markCheckInSeen(key: string): void {
  seenNow.add(key);
  try {
    const kept = (JSON.parse(window.localStorage.getItem(SEEN) ?? "[]") as string[]).slice(-20);
    window.localStorage.setItem(SEEN, JSON.stringify([...kept, key]));
  } catch {
    // Without storage it is still seen for this visit.
  }
}
