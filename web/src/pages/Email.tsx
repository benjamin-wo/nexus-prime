import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  api,
  type EmailConnection,
  type EmailOverview,
  type EmailStatus,
  type InboundEmail,
  type Me,
} from "../api";
import { BackLink } from "../components/BackLink";
import { formatDate } from "../format";
import { Button, Section } from "../components/ui";

import "./settings.css";

const LABELS: Record<EmailStatus, string> = {
  pending: "Waiting for you",
  logged: "Logged",
  skipped: "Skipped",
  not_receipt: "Not a receipt",
  no_amount: "No amount found",
  duplicate: "Already logged",
  failed: "Couldn't be read",
};

function EmailRow({ email, me, onChanged }: { email: InboundEmail; me: Me; onChanged: () => void }) {
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const needsAmount = !email.amount;
  // Waiting for an answer: these can also be dismissed.
  const skippable = email.status === "pending" || email.status === "failed";
  const twin = email.status === "pending" ? email.duplicate_of : null;
  // Its merchant or subject names a wallet: it may have been a move. Not when it looks like
  // a payment already recorded; that question comes first.
  const wallet = email.status === "pending" && !twin ? email.move_wallet : null;

  async function act(path: string, body?: unknown) {
    setError(null);
    try {
      await api(`/email/${email.id}/${path}`, { method: "POST", body: body ?? {} });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't do that");
    }
  }

  function logWithAmount(event: FormEvent) {
    event.preventDefault();
    void act("log", { amount: amount.trim() });
  }

  // "Transfer" keeps the wallet the email named; a figure typed in is sent along.
  const move = (figure?: string) => act("move", figure ? { amount: figure } : {});

  return (
    <li className="budget email-row">
      <div className="budget-head">
        <h3 className="wrap">
          {email.received && email.merchant ? `From ${email.merchant}` : (email.merchant ?? email.subject)}
        </h3>
        {email.amount && (
          <span className={email.received ? "num amount-in" : "num"}>
            {email.received ? "+" : ""}
            {Number(email.amount).toFixed(2)} {email.currency}
          </span>
        )}
      </div>
      <p className="caption wrap">
        {email.sender} · {formatDate(email.received_at, me.user.timezone)}
        {email.merchant ? ` · ${email.subject}` : ""}
      </p>
      {twin && <p className="caption email-twin">Looks like {twin}, already recorded or in another email. Same payment?</p>}
      {wallet && (
        <p className="caption email-twin">
          Was this a transfer {email.received ? "from" : "to"} {wallet}?
        </p>
      )}
      <div className="budget-foot">
        <span className={`caption email-status email-${email.status}`}>
          {LABELS[email.status]}
          {email.reason && email.status !== "pending" ? `: ${email.reason}` : ""}
        </span>
        {email.actionable && !needsAmount && (
          <span className="quick">
            {twin && (
              <Button variant="primary" onClick={() => act("same")}>
                Same one
              </Button>
            )}
            {wallet && (
              <Button variant="primary" onClick={() => move()}>
                Transfer
              </Button>
            )}
            <Button variant={twin || wallet ? undefined : "primary"} onClick={() => act("log")}>
              {twin ? "It's another" : wallet ? (email.received ? "Income" : "Expense") : "Log it"}
            </Button>
            {skippable && (
              <Button onClick={() => act("skip")}>
                Skip
              </Button>
            )}
          </span>
        )}
        {email.status === "logged" && email.transaction_id && (
          <Link className="caption" to="/accounting/ledger">
            In your ledger
          </Link>
        )}
      </div>
      {email.actionable && needsAmount && (
        <form className="quick email-amount" onSubmit={logWithAmount} aria-label={`Log ${email.subject}`}>
          <label className="field">
            Amount ({me.user.home_currency})
            <input
              className="input"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              required
            />
          </label>
          {wallet && (
            <Button variant="primary" disabled={!amount.trim()} onClick={() => move(amount.trim())}>
              Transfer
            </Button>
          )}
          <Button type="submit" disabled={!amount.trim()}>
            {wallet ? (email.received ? "Income" : "Expense") : "Log it"}
          </Button>
          {skippable && (
            <Button onClick={() => act("skip")}>
              Skip
            </Button>
          )}
        </form>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

function ConnectionRow({
  connection: c,
  me,
  confirming,
  onConfirm,
  onCancel,
  onDisconnect,
  error,
}: {
  connection: EmailConnection;
  me: Me;
  confirming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  onDisconnect: () => void;
  error?: string | null;
}) {
  const [copied, setCopied] = useState(false);
  const forward = c.provider === "forward";

  async function copy() {
    try {
      await navigator.clipboard.writeText(c.address);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  let seen = "Not checked yet";
  if (forward) {
    seen = c.last_received
      ? `Last email received ${formatDate(c.last_received, me.user.timezone)}`
      : "Nothing received yet";
  } else if (c.last_checked) {
    seen = `Last checked ${formatDate(c.last_checked, me.user.timezone)}`;
  }

  return (
    <li className="budget">
      <div className="budget-head">
        <h3 className="wrap">{c.address}</h3>
        <span className={`caption email-${c.status}`}>{c.status === "active" ? "Working" : "Needs reconnecting"}</span>
      </div>
      {forward && (
        <p className="caption">
          Your forwarding address: forward receipts here.{" "}
          <Button variant="text" onClick={copy}>
            {copied ? "Copied" : "Copy address"}
          </Button>
        </p>
      )}
      <div className="budget-foot">
        <span className="caption">{seen}</span>
        {confirming ? (
          <span className="quick">
            <span>{forward ? "Stop using this address?" : "Stop reading this mailbox?"}</span>
            <Button variant="danger" onClick={onDisconnect}>
              Disconnect
            </Button>
            <Button onClick={onCancel}>
              Keep
            </Button>
          </span>
        ) : (
          <Button variant="text" onClick={onConfirm}>
            Disconnect
          </Button>
        )}
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/** Every email Nexus checked in the last 30 days, and what became of it. */
export function EmailPage({ me }: { me: Me }) {
  const client = useQueryClient();
  const overview = useQuery({ queryKey: ["email"], queryFn: () => api<EmailOverview>("/email") });
  const [confirming, setConfirming] = useState<string | null>(null);
  // Which mailbox could not be disconnected, and why.
  const [failed, setFailed] = useState<{ id: string; message: string } | null>(null);

  function refresh() {
    for (const key of ["email", "transactions", "summary", "budgets"]) void client.invalidateQueries({ queryKey: [key] });
  }

  async function disconnect(id: string) {
    setConfirming(null);
    setFailed(null);
    try {
      await api(`/email/connections/${id}`, { method: "DELETE" });
      refresh();
    } catch (e) {
      setFailed({ id, message: e instanceof Error ? e.message : "Couldn't disconnect. Try again." });
    }
  }

  const data = overview.data;
  const waiting = data?.emails.filter((e) => e.status === "pending").length ?? 0;
  return (
    <>
      <div className="page-head">
        <div>
          <BackLink to="/settings">Back to Settings</BackLink>
          <h1>Receipts by email</h1>
          <p className="muted">Receipts found in your email. Nothing is logged until you say so.</p>
        </div>
      </div>
      {overview.isLoading && <p className="state">Loading…</p>}
      {overview.isError && <p className="state error-text">Couldn't load your email.</p>}
      {data && data.connections.length === 0 && (
        <p className="empty-line">
          No email is connected. To log receipts from email automatically, ask Nexus in chat: "how can I log my
          expenses automatically?"
        </p>
      )}
      {data && data.connections.length > 0 && (
        <div className="plan-grid">
          <Section id="mailboxes" title="Connected">
            <ul className="budgets">
              {data.connections.map((c) => (
                <ConnectionRow
                  key={c.id}
                  connection={c}
                  me={me}
                  confirming={confirming === c.id}
                  onConfirm={() => setConfirming(c.id)}
                  onCancel={() => setConfirming(null)}
                  onDisconnect={() => disconnect(c.id)}
                  error={failed?.id === c.id ? failed.message : null}
                />
              ))}
            </ul>
            <p className="caption">
              Disconnecting removes Nexus's access (a forwarding address stops working). Expenses already logged
              stay.
            </p>
          </Section>
          <Section id="checked" title="Checked emails">
            <p className="caption set-intro">{waiting > 0 ? `${waiting} waiting for you` : "Last 30 days"}</p>
            {data.emails.length === 0 ? (
              <p className="state">No receipt-like emails yet. New ones are checked every 15 minutes.</p>
            ) : (
              <ul className="budgets">
                {data.emails.map((e) => (
                  <EmailRow key={e.id} email={e} me={me} onChanged={refresh} />
                ))}
              </ul>
            )}
          </Section>
        </div>
      )}
    </>
  );
}
