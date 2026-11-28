import { useQuery } from "@tanstack/react-query";
import { type RefObject, useEffect, useState } from "react";

import { api } from "../api";
import type { CardView, ViewAnswer } from "./types";

type Config = { bot_username: string; views_enabled?: boolean };

/** `/api/config`: the bot the app signs in with, and whether Prime shows views as cards in the chat.
 * An older server, or a failed read, means views are off: the chat is what it was. */
export function useViewsEnabled(): boolean {
  const config = useQuery({
    queryKey: ["config"],
    queryFn: () => api<Config>("/config"),
    staleTime: 5 * 60_000,
  });
  return config.data?.views_enabled === true;
}

/** Params as the query string `GET /api/views/{kind}` reads: text as it is, a list or object as JSON. */
export function viewQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    search.set(key, typeof value === "object" ? JSON.stringify(value) : String(value));
  }
  const q = search.toString();
  return q ? `?${q}` : "";
}

/** The figures behind one card, fetched fresh. The frame's own summary stands in while they load. */
export function useViewFigures(view: CardView, enabled = true) {
  return useQuery<ViewAnswer>({
    queryKey: ["view", view.kind, view.params],
    queryFn: () => api<ViewAnswer>(`/views/${view.kind}${viewQuery(view.params)}`),
    enabled,
    staleTime: 30_000,
    placeholderData: view.summary
      ? { view_id: view.view_id ?? view.kind, kind: view.kind, params: view.params, caption: view.caption ?? "", summary: view.summary }
      : undefined,
  });
}

/** True once the element has come into view (and stays true). Where there is no IntersectionObserver
 * the element counts as in view at once. */
export function useInView(ref: RefObject<Element | null>, skip = false): boolean {
  const [seen, setSeen] = useState(skip || typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (seen) return;
    const el = ref.current;
    if (!el) return;
    const watcher = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true);
        watcher.disconnect();
      }
    });
    watcher.observe(el);
    return () => watcher.disconnect();
  }, [ref, seen]);
  return seen;
}

/** At most three views, the focus first, each id once (the later one wins: a newer card updates in place). */
export function orderViews(views: CardView[]): CardView[] {
  const byId = new Map<string, CardView>();
  for (const v of views) byId.set(v.view_id ?? `${v.kind}:${JSON.stringify(v.params)}`, v);
  const all = [...byId.values()];
  return [...all.filter((v) => v.focus), ...all.filter((v) => !v.focus)].slice(0, 3);
}
