import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { api, type Me, type Page, type Setup } from "../api";
import { Block } from "./Block";
import { Icon } from "./Icon";
import { Kaya } from "./Kaya";

/** Done: a tick. To do: an empty ring. The state is also said in words for a screen reader. */
function Tick({ done }: { done: boolean }) {
  return (
    <span className={`row-icon${done ? " in" : ""}`} aria-hidden="true">
      {done ? <Icon name="check" size={18} /> : <span className="ring" />}
    </span>
  );
}

/** Home's "Just ask Kaya" box is where a first expense is typed on this page: bring the person to it. */
function focusAsk() {
  const box = document.getElementById("ask-input");
  if (!box) return;
  box.scrollIntoView({ block: "center", behavior: "smooth" });
  box.focus({ preventScroll: true });
}

/** One row: a tick, what it is, and (until it is done) one small action. */
function Step({ done, label, children }: { done: boolean; label: string; children: ReactNode }) {
  return (
    <li className={`row start-row${done ? " is-done" : ""}`}>
      <Tick done={done} />
      <span className="row-main">
        <span className="wrap">{label}</span>
        <span className="sr-only">{done ? "Done" : "To do"}</span>
      </span>
      {!done && children}
    </li>
  );
}

/**
 * Home's one first-run guide: connect Telegram, log a first expense, set a monthly budget, get receipts
 * in automatically. Each is a row with a tick and one action. Done is worked out from what the app
 * already knows: a linked chat (`/me`), any transaction, and the budget and email steps of `/setup`.
 * It goes away by itself once all four are done, and a small Hide puts it away for good with
 * `POST /setup/dismiss` (kept on the user, so it holds on every device). A demo never sees it: its
 * account is filled in already. While anything it needs is still loading, or fails to load, it stays
 * out rather than flash steps that are not true.
 */
export function GetStarted({ me }: { me: Me }) {
  const client = useQueryClient();
  const away = Boolean(me.demo);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // `/setup` answers whether it was put away, and the budget and email steps.
  const setup = useQuery({
    queryKey: ["setup"],
    queryFn: () => api<Setup>("/setup"),
    enabled: !away,
  }).data;
  // The bot to open is the one the app signs in with (also used by the login page).
  const config = useQuery({
    queryKey: ["config"],
    queryFn: () => api<{ bot_username: string }>("/config"),
    enabled: !away,
  }).data;
  // One entry is enough to know there is one. Other pages' writes refresh "transactions" by prefix.
  const entries = useQuery({
    queryKey: ["transactions", "any"],
    queryFn: () => api<Page>("/transactions?limit=1"),
    enabled: !away,
  }).data;

  if (away || !setup || setup.dismissed || !entries) return null;
  const done = (key: string) => setup.items.find((i) => i.key === key)?.done === true;
  const linked = me.user.telegram_linked ?? true; // an older server doesn't say: don't nag
  const steps = [linked, entries.total > 0, done("budget"), done("receipts")];
  if (steps.every(Boolean)) return null;
  const [hasTelegram, hasEntry, hasBudget, hasReceipts] = steps;

  async function hide() {
    setBusy(true);
    setError(null);
    try {
      await api("/setup/dismiss", { method: "POST" });
      await client.invalidateQueries({ queryKey: ["setup"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't hide that");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Block
      id="get-started"
      title={
        <span className="title-kaya">
          <Kaya size={30} lazy />
          Get started
        </span>
      }
      className="start-card"
      action={
        <span className="start-head">
          <span className="caption">
            {steps.filter(Boolean).length} of {steps.length}
          </span>
          <button type="button" className="btn btn-ghost btn-small start-hide" disabled={busy} onClick={() => void hide()}>
            <Icon name="x" size={16} />
            <span className="sr-only">Hide</span>
          </button>
        </span>
      }
    >
      <ul className="rows" aria-label="First steps">
        <Step done={hasTelegram} label="Connect Telegram">
          {config && (
            <a className="btn btn-soft btn-small" href={`https://t.me/${config.bot_username}`} target="_blank" rel="noopener noreferrer">
              Open the bot<span className="sr-only"> in Telegram</span>
            </a>
          )}
        </Step>
        <Step done={hasEntry} label="Log your first expense">
          <button type="button" className="btn btn-soft btn-small" onClick={focusAsk}>
            Log one<span className="sr-only"> expense</span>
          </button>
        </Step>
        <Step done={hasBudget} label="Set a monthly budget">
          <Link className="btn btn-soft btn-small" to="/accounting/budgets">
            Set one<span className="sr-only"> budget</span>
          </Link>
        </Step>
        <Step done={hasReceipts} label="Get receipts in automatically">
          <Link className="btn btn-soft btn-small" to="/settings/email">
            Connect<span className="sr-only"> email</span>
          </Link>
        </Step>
      </ul>
      <p className="caption start-note">Log in Telegram or the chat button; review here.</p>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Block>
  );
}
