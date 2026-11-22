import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import { api, type Me, type Page, type Setup } from "../api";
import { Button, ButtonLink, Row, RowList, Section } from "./ui";

/** One row: what it is and, at the right, "Done" or (until it is done) a "Set up" text button. The state is also
 * said in words for a screen reader. */
function Step({ done, label, children }: { done: boolean; label: string; children: ReactNode }) {
  return (
    <Row
      className={`start-row${done ? " is-done" : ""}`}
      title={label}
      sub={done ? undefined : <span className="sr-only">To do</span>}
      trailing={done ? <span className="start-done">Done</span> : undefined}
      actions={done ? undefined : children}
    />
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
export function GetStarted({ me, onLog }: { me: Me; onLog: () => void }) {
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
    <Section
      id="get-started"
      title="Get started"
      className="start-card"
      action={
        <span className="start-head">
          <span className="caption">
            {steps.filter(Boolean).length} of {steps.length}
          </span>
          <Button variant="text" size="sm" className="start-hide" disabled={busy} onClick={() => void hide()}>
            Hide
          </Button>
        </span>
      }
    >
      <RowList aria-label="First steps">
        <Step done={hasTelegram} label="Connect Telegram">
          {config && (
            <ButtonLink variant="text" href={`https://t.me/${config.bot_username}`} target="_blank" rel="noopener noreferrer">
              Set up<span className="sr-only"> Telegram</span>
            </ButtonLink>
          )}
        </Step>
        <Step done={hasEntry} label="Log your first expense">
          <Button variant="text" onClick={onLog}>
            Set up<span className="sr-only"> your first expense</span>
          </Button>
        </Step>
        <Step done={hasBudget} label="Set a monthly budget">
          <ButtonLink variant="text" to="/accounting/budgets">
            Set up<span className="sr-only"> a monthly budget</span>
          </ButtonLink>
        </Step>
        <Step done={hasReceipts} label="Get receipts in automatically">
          <ButtonLink variant="text" to="/settings/email">
            Set up<span className="sr-only"> email receipts</span>
          </ButtonLink>
        </Step>
      </RowList>
      <p className="caption start-note">Log in Telegram or the chat button; review here.</p>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Section>
  );
}
