import { useEffect, useRef, useState } from "react";

import { PANEL_TITLES } from "../panels/links";
import type { PanelEntry } from "../panels/stageReducer";
import { usePanelStageContext, type PanelStage as Stage } from "../panels/usePanelStage";
import { PanelCard, useTimezone } from "./PanelCard";

const EMPTY = "Ask Nexus about your money or a trip and the right view opens here.";

/** A panel is new (or Prime changed it, or it was reopened) when its id, or the time it opened or last
 * changed, is not what was announced before. */
const stamp = (p: PanelEntry) => `${p.openedAt}:${p.updatedAt}`;

/** Says "<Title> opened" in a polite live region when a panel opens. Never moves focus. */
function useAnnouncement(panels: PanelEntry[]): string {
  const [text, setText] = useState("");
  const seen = useRef<Map<string, string> | null>(null);
  useEffect(() => {
    const now = new Map(panels.map((p) => [p.id, stamp(p)]));
    const before = seen.current;
    seen.current = now;
    if (before === null) return; // what was there when the stage mounted is not news
    const fresh = [...panels].reverse().find((p) => before.get(p.id) !== stamp(p));
    if (!fresh) return;
    const title = PANEL_TITLES[fresh.event.kind];
    const said = before.has(fresh.id) && before.get(fresh.id)?.split(":")[0] === String(fresh.openedAt) ? `${title} updated` : `${title} opened`;
    // The same words twice in a row are not read again, so a trailing space alternates.
    setText((previous) => (previous.trim() === said ? `${said} ` : said));
  }, [panels]);
  return text;
}

/** What Prime has opened beside the chat: the expanded panel large, the others compact, an empty state,
 * and the recently closed ones to bring back. `away`: the page is showing instead; the cards are out of sight and
 * out of the tab order, but the live region still says when Prime opens one. */
export function PanelStage({ away = false }: { away?: boolean }) {
  const stage = usePanelStageContext();
  const timezone = useTimezone();
  const region = useRef<HTMLElement>(null);
  const { panels, history } = stage.state;
  const announcement = useAnnouncement(panels);
  // Dismissing removes the button that had focus: put it on the stage, not on the page's top.
  const withFocus: Stage = {
    ...stage,
    dismiss: (id) => {
      stage.dismiss(id);
      region.current?.focus();
    },
  };
  const expanded = panels.filter((p) => p.expanded);
  const rest = panels.filter((p) => !p.expanded);
  return (
    <section className={`panel-stage${away ? " panel-stage-away" : ""}`} aria-label="Panels" ref={region} tabIndex={-1}>
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      <div className="panel-stage-content" hidden={away}>
        {panels.length === 0 ? (
          <p className="panel-empty">{EMPTY}</p>
        ) : (
          <>
            {expanded.map((entry) => (
              <PanelCard key={entry.id} entry={entry} stage={withFocus} timezone={timezone} />
            ))}
            {rest.length > 0 && (
              <div className="panel-compact-grid">
                {rest.map((entry) => (
                  <PanelCard key={entry.id} entry={entry} stage={withFocus} timezone={timezone} />
                ))}
              </div>
            )}
          </>
        )}
        {history.length > 0 && (
          <section className="panel-history" aria-labelledby="panel-history-title">
            <h3 id="panel-history-title">Recently closed</h3>
            <ul>
              {history.slice(0, 6).map((entry) => {
                const title = PANEL_TITLES[entry.event.kind];
                return (
                  <li key={entry.id}>
                    <span className="wrap">
                      {title} <span className="caption">· {entry.event.topic}</span>
                    </span>
                    <button type="button" className="btn btn-small" aria-label={`Reopen ${title}: ${entry.event.topic}`} onClick={() => stage.restore(entry.id)}>
                      Reopen
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
      </div>
    </section>
  );
}
