// When the chat docks as a column beside the panel stage: the server has panels on and the window is wide.

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, type AppConfig } from "../api";

/** Narrower than this, the chat stays a drawer and no stage shows (DESIGN.md: 1024px is the stacked
 * dashboard; the docked layout needs a little more for rail, chat column and stage). */
export const DOCK_MIN_WIDTH = 1100;

const QUERY = `(min-width: ${DOCK_MIN_WIDTH}px)`;

/** Whether the window is wide enough for the docked layout; always false where matchMedia is missing. */
export function useWideScreen(): boolean {
  const supported = typeof window !== "undefined" && typeof window.matchMedia === "function";
  const [wide, setWide] = useState(() => (supported ? window.matchMedia(QUERY).matches : false));
  useEffect(() => {
    if (!supported) return;
    const media = window.matchMedia(QUERY);
    const update = () => setWide(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [supported]);
  return wide;
}

/** True when the chat is a fixed column on the left and the stage fills the main area. With the flag off
 * (or `/config` unreachable) it is false and everything behaves as before. */
export function usePanelsDocked(): boolean {
  const wide = useWideScreen();
  const config = useQuery({ queryKey: ["app-config"], queryFn: () => api<AppConfig>("/config"), retry: false, staleTime: 5 * 60_000 });
  return wide && config.data?.panels_enabled === true;
}
