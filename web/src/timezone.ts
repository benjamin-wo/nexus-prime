import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { type Me, setTimezone, type TimezoneSource } from "./api";

/** The part of /me that says which zone Nexus is on, and why. Older answers may lack the last three. */
export type ZoneState = Partial<Pick<Me["user"], "home_timezone" | "timezone_source" | "timezone_set_at">> & Pick<Me["user"], "timezone">;

/** A zone picked by hand is kept for this long before the phone may move it again. */
export const MANUAL_HOLD_MS = 24 * 60 * 60 * 1000;

/** "Europe/Madrid" is "Madrid", "America/Argentina/Buenos_Aires" is "Buenos Aires". */
export function friendlyZone(zone: string): string {
  const city = zone.split("/").pop() ?? zone;
  return city.replace(/_/g, " ");
}

/** The zone's offset from UTC now: "UTC+2", "UTC+5:30", "UTC-3", "UTC". Empty when the browser doesn't know the zone. */
export function zoneOffset(zone: string, at: Date = new Date()): string {
  try {
    const name = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "longOffset" })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName")?.value;
    const match = /^(?:GMT|UTC)(?:([+\-−])(\d{1,2})(?::(\d{2}))?)?$/.exec(name ?? "");
    if (!match) return "";
    const [, sign, hours, minutes] = match;
    if (!sign || (Number(hours) === 0 && Number(minutes ?? 0) === 0)) return "UTC";
    return `UTC${sign === "+" ? "+" : "-"}${Number(hours)}${minutes && minutes !== "00" ? `:${minutes}` : ""}`;
  } catch {
    return "";
  }
}

/** "Madrid · UTC+2". */
export function describeZone(zone: string, at: Date = new Date()): string {
  const offset = zoneOffset(zone, at);
  return offset ? `${friendlyZone(zone)} · ${offset}` : friendlyZone(zone);
}

/** The small note under the zone: what put Nexus on it. */
export function sourceNote(source: TimezoneSource | undefined): string {
  switch (source) {
    case "phone":
      return "from your phone";
    case "chat":
      return "you set it";
    case "trip":
      return "from your trip";
    default:
      return "home";
  }
}

/** The browser's own zone, or null when it won't say. */
export function browserZone(): string | null {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return typeof zone === "string" && zone.trim() ? zone : null;
  } catch {
    return null;
  }
}

/** Whether to tell the server the phone's zone: when it differs from Nexus's zone, or the server
 * hasn't recorded the phone as the source. A zone the person picked themselves in the last 24 hours
 * (source "chat") is left alone. */
export function shouldReportZone(phone: string | null | undefined, state: ZoneState, now: number = Date.now()): boolean {
  if (!phone || !phone.trim()) return false;
  if (state.timezone_source === "chat" && state.timezone_set_at) {
    const setAt = Date.parse(state.timezone_set_at);
    if (!Number.isNaN(setAt) && now - setAt < MANUAL_HOLD_MS) return false;
  }
  return phone !== state.timezone || state.timezone_source !== "phone";
}

/** Once per page load, after sign-in: tells Nexus the zone this browser is in. It never delays the
 * page and a failure is dropped; the next load tries again. */
export function useReportTimeZone(user: ZoneState): void {
  const client = useQueryClient();
  const done = useRef(false);
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const phone = browserZone();
    if (!phone || !shouldReportZone(phone, user)) return;
    setTimezone(phone, "phone")
      .then((answer) => {
        void client.invalidateQueries({ queryKey: ["me"] });
        // Today moves with the zone: what the home feed and the day's cards say.
        if (answer?.changed) for (const key of ["home", "investments", "summary", "transactions"]) void client.invalidateQueries({ queryKey: [key] });
      })
      .catch(() => undefined);
  }, [client, user]);
}

const COMMON_ZONES = [
  "UTC",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Sao_Paulo",
  "Atlantic/Reykjavik",
  "Europe/London",
  "Europe/Lisbon",
  "Europe/Madrid",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Athens",
  "Europe/Istanbul",
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Bangkok",
  "Asia/Singapore",
  "Asia/Hong_Kong",
  "Asia/Shanghai",
  "Asia/Tokyo",
  "Asia/Seoul",
  "Australia/Perth",
  "Australia/Sydney",
  "Pacific/Auckland",
];

/** Every zone the browser knows, or a short common list when it can't say. The zones in `keep` are always in it. */
export function zoneChoices(keep: string[] = []): string[] {
  let all: string[];
  try {
    const supported = (Intl as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.("timeZone");
    all = supported && supported.length ? supported : COMMON_ZONES;
  } catch {
    all = COMMON_ZONES;
  }
  return [...new Set([...all, ...keep.filter(Boolean)])].sort((a, b) => friendlyZone(a).localeCompare(friendlyZone(b)));
}

/** The zones that match what was typed: any part of the city, region or IANA name. */
export function filterZones(zones: string[], query: string): string[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return zones;
  return zones.filter((zone) => {
    const hay = `${friendlyZone(zone)} ${zone.replace(/_/g, " ")}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}
